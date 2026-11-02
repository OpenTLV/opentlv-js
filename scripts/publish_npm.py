# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Publish the attested GitHub release archive to npm by trusted publishing; never build or replace it."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

import core_dependency as core
import package
import release
from release import REPOSITORY, ROOT, read, require, write

REGISTRY = "https://registry.npmjs.org"
ENVIRONMENT = "npm"
# Trusted publishing needs npm 11.5.1 or later on Node 22.14 or later; npm 12 would need Node 22.22.2.
NPM_CLI = "11.21.1"
NODE_MINIMUM = (22, 14, 0)
PACKUMENT = f"{REGISTRY}/{package.NAME.replace('/', '%2f')}"
PURL = "pkg:npm/" + package.NAME.replace("@", "%40", 1)
SLSA = "https://slsa.dev/provenance/v1"
INPUT = ROOT / "build/npm-input"
WORK = ROOT / "build/npm"
BOOTSTRAP = ("npm has no @opentlv/opentlv package yet: publish the first version manually and configure "
             "the trusted publisher (docs/packaging.md#npm-publication)")


def registry(url):
    """Read registry JSON; a missing package or version is None, every other failure raises."""
    request = urllib.request.Request(url, headers={"Accept": "application/json", "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def stable(version):
    require(isinstance(version, str) and re.fullmatch(release.TAG, "v" + version),
            f"npm versions must be stable MAJOR.MINOR.PATCH: {version}")
    return tuple(int(part) for part in version.split("."))


def check_environment():
    """Require the npm environment to deploy only from main and only after a reviewer approves."""
    environment = release.api(f"repos/{REPOSITORY}/environments/{ENVIRONMENT}")
    require(any(rule.get("type") == "required_reviewers" and rule.get("reviewers")
                for rule in environment.get("protection_rules", [])),
            "The npm environment must require a reviewer")
    require(environment.get("can_admins_bypass") is False,
            "Administrators must not bypass the npm environment approval")
    policy = environment.get("deployment_branch_policy") or {}
    require(policy.get("custom_branch_policies") is True and policy.get("protected_branches") is False,
            "The npm environment must deploy only from main")
    branches = release.api(f"repos/{REPOSITORY}/environments/{ENVIRONMENT}/deployment-branch-policies")
    require([(item.get("name"), item.get("type", "branch")) for item in branches.get("branch_policies", [])]
            == [("main", "branch")], "The npm environment must deploy only from main")


def check_registry(version):
    """Require an existing package without this version, so publication adds the newest version."""
    published = registry(PACKUMENT)
    require(published is not None, BOOTSTRAP)
    require(version not in published.get("versions", {}),
            f"npm already has {package.NAME}@{version}; release a new version")
    latest = published.get("dist-tags", {}).get("latest")
    require(latest is None or stable(version) > stable(latest),
            f"{version} must be newer than the npm latest version {latest}")
    return latest


def preflight(version):
    """Reject an npm release before Full CI unless the package, approval gate and registry allow it."""
    require(package.metadata(ROOT).get("private") is not True,
            "npm refuses private packages; remove private: true in the approved publication change")
    check_environment()
    return {"package": package.NAME, "environment": ENVIRONMENT, "latest": check_registry(version)}


def toolchain():
    node = release.run("node", "--version", capture=True)
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", node)
    require(match and match.group(1) == "22" and tuple(map(int, match.groups())) >= NODE_MINIMUM,
            "Trusted publishing requires Node 22.14 or later")
    require(release.run("npm", "--version", capture=True) == NPM_CLI,
            f"Trusted publishing requires the pinned npm {NPM_CLI}")
    return {"node": node, "npm": NPM_CLI}


def select(root, run_id):
    """The release assets of the attempt that published the GitHub release of this run."""
    records = sorted(root.glob("js-published-*/published.json"))
    require(len(records) == 1, "npm publication requires the one GitHub release published by this run")
    record = read(records[0])
    attempt = str(record.get("identity", {}).get("run_attempt"))
    require(record["identity"].get("run_id") == run_id and records[0].parent.name == "js-published-" + attempt,
            "The GitHub release was not published by this run")
    directory = root / ("js-release-" + attempt)
    require(directory.is_dir(), "Missing the release assets of the publishing attempt")
    return record, directory


def check_request(request, current):
    """Bind a later attempt to the release this run prepared; its tag now exists, so preflight cannot repeat."""
    identity = request["identity"]
    require(request.get("npm") is not None, "npm publication was not requested when the release was prepared")
    require(current["commit"] == identity["commit"] and current["run_id"] == identity["run_id"]
            and int(identity["run_attempt"]) <= int(current["run_attempt"]),
            "npm publication requires the release prepared by this run")
    require(release.version_for(request["tag"]) == request["version"]
            and release.core_release(core.load_lock()) == request["core"], "Release source changed")


def check_github_release(directory, request, record):
    """Require the public GitHub release and its tag to hold exactly these assets."""
    matches = [item for item in release.pages(f"repos/{REPOSITORY}/releases") if item["tag_name"] == request["tag"]]
    require(len(matches) == 1, "Missing or duplicate GitHub release")
    published = release.api(f"repos/{REPOSITORY}/releases/{matches[0]['id']}")
    release.verify_published_assets(published, directory, request, False)
    require(release.api(f"repos/{REPOSITORY}/commits/{request['tag']}")["sha"] == request["identity"]["commit"],
            "Release tag changed")
    require(record.get("url") == published["html_url"] and record.get("tag") == request["tag"]
            and record.get("identity") == request["identity"] and record.get("core") == request["core"]
            and sorted(record.get("assets", [])) == sorted(asset["name"] for asset in published["assets"]),
            "GitHub release record differs from the published release")
    return published["html_url"]


def check_approval(run_id):
    """Who approved the npm environment in this run; the job cannot run without it, the receipt names it."""
    reviews = release.api(f"repos/{REPOSITORY}/actions/runs/{run_id}/approvals")
    approved = sorted({review["user"]["login"] for review in reviews if review.get("state") == "approved"
                       and any(item.get("name") == ENVIRONMENT for item in review.get("environments", []))})
    require(approved, "npm publication requires an approval of the npm environment in this run")
    return approved


def check_manifest(archive, version):
    with tarfile.open(archive, "r:gz") as bundle:
        data = json.load(bundle.extractfile("package/package.json"))
    require(data.get("name") == package.NAME and data.get("version") == version
            and data.get("private") is not True and data.get("repository") == package.REPOSITORY,
            "The archive is not the public package npm trusts for this repository")


def hashes(path):
    data = path.read_bytes()
    sha512 = hashlib.sha512(data)
    return {"integrity": "sha512-" + base64.b64encode(sha512.digest()).decode(),
            "sha512": sha512.hexdigest(), "shasum": hashlib.sha1(data).hexdigest()}


def same_bytes(info, expected):
    dist = info.get("dist", {})
    return dist.get("integrity") == expected["integrity"] and dist.get("shasum") == expected["shasum"]


def prepare(root=INPUT):
    current = release.hosted_identity()
    tools = toolchain()
    record, directory = select(root, current["run_id"])
    request = release.verify_payload(directory, validate=lambda request: check_request(request, current))
    release.verify_attestations(directory, request["identity"]["commit"])
    url = check_github_release(directory, request, record)
    check_environment()
    approved = check_approval(current["run_id"])
    version = request["version"]
    archive = directory / f"{package.ARCHIVE_PREFIX}-{version}.tgz"
    check_manifest(archive, version)
    expected = hashes(archive)
    published = registry(PACKUMENT)
    require(published is not None, BOOTSTRAP)
    existing = published.get("versions", {}).get(version)
    if existing is None:
        check_registry(version)
    else:
        # Registry versions are immutable: a retry may confirm the same bytes, never replace them.
        require(same_bytes(existing, expected),
                f"npm already has different bytes for {package.NAME}@{version}; release a new version")
    require(not WORK.exists(), "npm work directory must be fresh")
    WORK.mkdir(parents=True)
    shutil.copyfile(archive, WORK / archive.name)
    upload = existing is None
    write(WORK / "plan.json", {
        "schema": 1, "package": package.NAME, "version": version, "tag": request["tag"],
        "archive": archive.name, **expected, "identity": request["identity"], "release": url,
        "approved_by": approved, "toolchain": tools, "upload": upload})
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"upload={'true' if upload else 'false'}\n")
        output.write(f"archive={(WORK / archive.name).relative_to(ROOT).as_posix()}\n")


def check_provenance(attestations, plan):
    """Require npm's SLSA provenance to name these bytes, this workflow, commit and run."""
    require(attestations.get("provenance", {}).get("predicateType") == SLSA
            and str(attestations.get("url", "")).startswith(f"{REGISTRY}/-/npm/v1/attestations/"),
            "npm lists no SLSA provenance for the published version")
    bundles = (registry(attestations["url"]) or {}).get("attestations", [])
    statements = [json.loads(base64.b64decode(item["bundle"]["dsseEnvelope"]["payload"]))
                  for item in bundles if item.get("predicateType") == SLSA]
    require(len(statements) == 1, "npm must hold exactly one SLSA provenance statement")
    statement = statements[0]
    require(statement.get("subject") == [{"name": f"{PURL}@{plan['version']}",
                                          "digest": {"sha512": plan["sha512"]}}],
            "npm provenance names other package bytes")
    build = statement["predicate"]["buildDefinition"]
    identity = plan["identity"]
    require(build["externalParameters"]["workflow"] == {
        "ref": "refs/heads/main", "repository": "https://github.com/" + REPOSITORY, "path": release.WORKFLOW}
            and build["internalParameters"]["github"]["event_name"] == "workflow_dispatch"
            and [item["digest"].get("gitCommit") for item in build["resolvedDependencies"]] == [identity["commit"]],
            "npm provenance names another workflow, event or commit")
    invocation = statement["predicate"]["runDetails"]["metadata"]["invocationId"]
    require(re.fullmatch(rf"https://github\.com/{REPOSITORY}/actions/runs/{identity['run_id']}/attempts/\d+",
                         invocation), "npm provenance names another workflow run")
    return invocation


def audit(plan):
    """Install the version from npm in a clean project and verify its registry signatures and attestations."""
    with tempfile.TemporaryDirectory(prefix="opentlv-npm-audit-") as temporary:
        project = Path(temporary) / "project"
        home = Path(temporary) / "home"
        project.mkdir()
        home.mkdir()
        (project / "package.json").write_text('{"private":true,"type":"module"}\n', encoding="utf-8")
        environment = package.clean_environment(os.environ, home)
        for command in (("install", "--save-exact", "--ignore-scripts", "--no-audit", "--no-fund",
                         f"{package.NAME}@{plan['version']}"), ("audit", "signatures")):
            arguments = ["npm", *command, "--registry", REGISTRY + "/"]
            print("+ " + " ".join(arguments), flush=True)
            subprocess.run(arguments, cwd=project, env=environment, check=True)
        lock = json.loads((project / "package-lock.json").read_text(encoding="utf-8"))
        installed = lock["packages"]["node_modules/" + package.NAME]
        require(installed.get("version") == plan["version"] and installed.get("integrity") == plan["integrity"],
                "The installed npm package differs from the released archive")


def confirm(attempts=20, delay=15):
    """Wait until npm serves exactly the planned bytes as latest with their provenance, then record a receipt."""
    plan = read(WORK / "plan.json")
    version = plan["version"]
    for attempt in range(attempts):
        info = registry(f"{PACKUMENT}/{version}")
        latest = (registry(PACKUMENT) or {}).get("dist-tags", {}).get("latest")
        if info is not None:
            require(info.get("name") == package.NAME and info.get("version") == version and same_bytes(info, plan),
                    "npm registry bytes differ from the released archive")
            if info["dist"].get("attestations") and latest == version:
                break
        if attempt + 1 < attempts:
            time.sleep(delay)
    else:
        raise ValueError("npm does not serve the published version as latest with its provenance")
    invocation = check_provenance(info["dist"]["attestations"], plan)
    audit(plan)
    identity = plan["identity"]
    write(WORK / "receipt.json", {
        "schema": 1, "kind": "js-npm-publication", "package": package.NAME, "version": version,
        "url": f"https://www.npmjs.com/package/{package.NAME}/v/{version}", "tag": plan["tag"],
        "release": plan["release"], "commit": identity["commit"], "run_id": int(identity["run_id"]),
        "run_attempt": int(identity["run_attempt"]), "integrity": plan["integrity"], "shasum": plan["shasum"],
        "provenance": invocation, "approved_by": plan["approved_by"], "uploaded": plan["upload"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "confirm"))
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    else:
        confirm()


if __name__ == "__main__":
    main()
