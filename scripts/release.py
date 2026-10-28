# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Publish the tested JS/WASM archive from a clean main dispatch and Full attempt."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import core_dependency as core
import package

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "OpenTLV/opentlv-js"
WORKFLOW = ".github/workflows/js-release.yml"
SIGNER = REPOSITORY + "/" + WORKFLOW
NOTES = ROOT / "ci/release-notes.md"
TAG = r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
MAIN_GATES = {"checks / JS quality gate"}
FULL_GATES = {"full / checks / JS quality gate", "full / reproducibility / JS quality gate"}
# Every Full tier/configuration record the release requires from its own attempt.
RECORDS = (("full", "Release"), ("full", "Debug"), ("release", "Release"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def run(*args, capture=False):
    command = [str(value) for value in args]
    print("+ " + " ".join(command), flush=True)
    result = subprocess.run(command, cwd=ROOT, check=True, text=True, encoding="utf-8",
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else None


def api(endpoint):
    return json.loads(run("gh", "api", endpoint, capture=True))


def pages(endpoint, key=None):
    result = []
    for page in range(1, 101):
        separator = "&" if "?" in endpoint else "?"
        data = api(endpoint + f"{separator}per_page=100&page={page}")
        items = data[key] if key else data
        result.extend(items)
        if len(items) < 100:
            return result
    raise ValueError("GitHub pagination limit exceeded")


def version_for(tag):
    require(re.fullmatch(TAG, tag), "Use a stable vMAJOR.MINOR.PATCH tag")
    version = package.metadata(ROOT)["version"]
    require(tag == "v" + version, "Tag differs from the package.json version")
    catalog = read(ROOT / "docs-examples.json")
    require(catalog.get("component_version") == version, "Documentation catalog version differs")
    notes = NOTES.read_text(encoding="utf-8")
    require(notes.startswith(f"# OpenTLV JS {tag}\n") and re.search(r"^- \S", notes, re.MULTILINE),
            "Missing versioned release notes")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    require(re.search(rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.MULTILINE),
            "Close the changelog under the release version and date")
    return version


def identity():
    return {"repository": os.environ.get("GITHUB_REPOSITORY"),
            "commit": run("git", "rev-parse", "HEAD", capture=True),
            "dirty": bool(run("git", "status", "--porcelain", capture=True)),
            "hosted": os.environ.get("GITHUB_ACTIONS") == "true",
            "run_id": os.environ.get("GITHUB_RUN_ID"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT")}


def hosted_identity():
    current = identity()
    require(current["hosted"] and not current["dirty"] and current["repository"] == REPOSITORY,
            "Release requires the official clean hosted checkout")
    require(os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch" and
            os.environ.get("GITHUB_REF") == "refs/heads/main" and
            os.environ.get("GITHUB_SHA") == current["commit"] and
            os.environ.get("GITHUB_WORKFLOW_REF") == SIGNER + "@refs/heads/main" and
            os.environ.get("GITHUB_WORKFLOW_SHA") == current["commit"],
            "Release requires a main dispatch with matching workflow SHA")
    return current


def unused_tag(tag, commit):
    require(api(f"repos/{REPOSITORY}/git/ref/heads/main")["object"]["sha"] == commit,
            "Main moved; validate and release the new commit")
    refs = api(f"repos/{REPOSITORY}/git/matching-refs/tags/{tag}")
    require(not any(ref["ref"] == "refs/tags/" + tag for ref in refs), "Tag already exists")
    releases = pages(f"repos/{REPOSITORY}/releases")
    require(not any(item["tag_name"] == tag for item in releases), "Release already exists")


def check_main(run_info, commit):
    require(run_info.get("head_sha") == commit and run_info.get("event") == "push" and
            run_info.get("head_branch") == "main" and
            run_info.get("path") == ".github/workflows/js-main.yml" and
            run_info.get("repository", {}).get("full_name") == REPOSITORY and
            run_info.get("head_repository", {}).get("full_name") == REPOSITORY and
            run_info.get("status") == "completed" and run_info.get("conclusion") == "success",
            "Successful Main CI on the release commit is required")


def main_evidence(commit):
    runs = pages(f"repos/{REPOSITORY}/actions/workflows/js-main.yml/runs"
                 f"?head_sha={commit}&event=push&branch=main", "workflow_runs")
    require(runs, "Main CI is missing on the release commit")
    latest = max(runs, key=lambda item: item["id"])
    check_main(latest, commit)
    return {"run_id": latest["id"], "run_attempt": latest["run_attempt"], "url": latest["html_url"]}


def check_gates(run_id, attempt, names):
    jobs = pages(f"repos/{REPOSITORY}/actions/runs/{run_id}/attempts/{attempt}/jobs", "jobs")
    gates = [job for job in jobs if job["name"] in names]
    require(len(gates) == len(names) and {job["name"] for job in gates} == names and
            all(job.get("status") == "completed" and job.get("conclusion") == "success"
                for job in gates), "Missing successful attempt-bound quality gate")


def core_release(lock):
    """Require the Core lock to name an exact release tag, not a development build."""
    inputs = lock["version_inputs"]
    require(re.fullmatch(TAG, inputs["tag"]) and inputs["revision"] == 0 and
            inputs["tag_commit"] == lock["commit"] and inputs["tag"] in inputs["tags_at_commit"],
            "Core must be locked to an exact vMAJOR.MINOR.PATCH release commit")
    return lock


def preflight(tag):
    version = version_for(tag)
    current = hosted_identity()
    unused_tag(tag, current["commit"])
    main = main_evidence(current["commit"])
    check_gates(main["run_id"], main["run_attempt"], MAIN_GATES)
    return {"schema": 1, "tag": tag, "version": version, "identity": current,
            "core": core_release(core.load_lock()), "main": main, "notes_sha256": digest(NOTES)}


def validate_request(request):
    require(request == preflight(request["tag"]), "Release request, Main evidence or source changed")


def check_record(record, tier, configuration, request):
    current = request["identity"]
    require(record.get("schema") == 1 and record.get("status") == "passed" and
            record.get("tier") == tier and record.get("configuration") == configuration and
            record.get("hosted") is True and record.get("repository") == REPOSITORY and
            record.get("sha") == current["commit"] and
            record.get("checkout_commit") == current["commit"] and
            record.get("checkout_dirty") is False and
            record.get("run_id") == current["run_id"] and
            record.get("run_attempt") == current["run_attempt"] and
            record.get("toolchain", {}).get("node", "").startswith("v22."),
            f"Stale or failed {tier} / {configuration} evidence")
    builds = record.get("builds", {})
    require(set(builds) == ({"first", "second"} if tier == "release" else {"first"}),
            f"Incomplete {tier} / {configuration} builds")
    lock = request["core"]
    for build in builds.values():
        selected = build["core"]
        require(selected["mode"] == "pinned-source" and selected["dirty"] is False and
                all(selected[key] == lock[key] for key in
                    ("repository", "commit", "tree", "source_sha256", "version_inputs")),
                "Build did not use the locked Core release source")
        require(build["package"]["version"] == request["version"], "Package version differs")
    if tier == "release":
        require(record.get("reproducibility_verified") is True and
                builds["first"]["package"] == builds["second"]["package"],
                "Release archives were not reproduced")
    if configuration == "Release":
        require(record.get("migration_compatibility", {}).get("status") == "passed",
                "Migration compatibility evidence is missing")


def check_full(records, request):
    require(set(records) == set(RECORDS), "Incomplete Full evidence")
    for (tier, configuration), record in records.items():
        check_record(record, tier, configuration, request)
    current = request["identity"]
    check_gates(current["run_id"], current["run_attempt"], FULL_GATES)
    return records[("release", "Release")]["builds"]["first"]["package"]


def load_records(directory):
    records = {}
    for path in sorted(directory.rglob("result.json")):
        record = read(path)
        key = (record.get("tier"), record.get("configuration"))
        require(key not in records, "Duplicate Full evidence")
        records[key] = record
    return records


def check_archive(path, tested):
    require(digest(path) == tested["archive_sha256"], "Archive differs from the tested package")
    package.verify_archive(path, tested["files"])


def assemble(evidence, output):
    request = read(evidence / "request.json")
    validate_request(request)
    records = load_records(evidence / "records")
    tested = check_full(records, request)
    name = f"opentlv-js-{request['version']}.tgz"
    require({path.name for path in (evidence / "package").iterdir()} == {name},
            "Unexpected package archive set")
    check_archive(evidence / "package" / name, tested)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(evidence / "package" / name, output / name)
    shutil.copyfile(NOTES, output / "release-notes.md")
    write(output / "release-manifest.json", {
        "schema": 1, "request": request, "package": tested,
        "records": [records[key] for key in RECORDS]})
    (output / "SHA256SUMS").write_text("".join(
        f"{digest(path)}  {path.name}\n" for path in sorted(output.iterdir())), encoding="utf-8")


def verify_payload(directory):
    manifest = read(directory / "release-manifest.json")
    require(manifest.get("schema") == 1, "Unsupported release manifest")
    request = manifest["request"]
    validate_request(request)
    require(len(manifest["records"]) == len(RECORDS), "Incomplete Full evidence")
    records = {(record.get("tier"), record.get("configuration")): record
               for record in manifest["records"]}
    tested = check_full(records, request)
    require(manifest["package"] == tested, "Release package identity differs")
    archive = f"opentlv-js-{request['version']}.tgz"
    names = {archive, "release-manifest.json", "release-notes.md"}
    require({path.name for path in directory.iterdir()} == names | {"SHA256SUMS"},
            "Unexpected release asset set")
    expected_sums = "".join(f"{digest(directory / name)}  {name}\n" for name in sorted(names))
    require((directory / "SHA256SUMS").read_text(encoding="utf-8") == expected_sums,
            "Release checksums differ")
    require(digest(directory / "release-notes.md") == request["notes_sha256"], "Release notes changed")
    check_archive(directory / archive, tested)
    return request


def verify_published_assets(release, directory, request, draft):
    require(release.get("tag_name") == request["tag"] and release.get("draft") is draft and
            release.get("prerelease") is False and
            release.get("body", "").strip() == NOTES.read_text(encoding="utf-8").strip(),
            "Published release metadata differs")
    assets = release.get("assets", [])
    paths = {path.name: path for path in directory.iterdir()}
    require(len(assets) == len(paths) and {asset["name"] for asset in assets} == set(paths),
            "Published release asset set differs")
    for asset in assets:
        path = paths[asset["name"]]
        require(asset.get("state") == "uploaded" and asset.get("size") == path.stat().st_size and
                asset.get("digest") == "sha256:" + digest(path), "Published asset digest differs")


def publish(directory):
    request = verify_payload(directory)
    commit = request["identity"]["commit"]
    for path in sorted(directory.iterdir()):
        run("gh", "attestation", "verify", path, "--repo", REPOSITORY,
            "--signer-workflow", SIGNER, "--source-digest", commit)
    # Final read before the first write; never overwrite an existing tag/release.
    unused_tag(request["tag"], commit)
    run("gh", "api", "--method", "POST", f"repos/{REPOSITORY}/git/refs",
        "-f", "ref=refs/tags/" + request["tag"], "-f", "sha=" + commit)
    run("gh", "release", "create", request["tag"], "--repo", REPOSITORY, "--verify-tag",
        "--draft", "--title", "OpenTLV JS " + request["tag"],
        "--notes-file", directory / "release-notes.md", *sorted(directory.iterdir()))
    matches = [item for item in pages(f"repos/{REPOSITORY}/releases")
               if item["tag_name"] == request["tag"]]
    require(len(matches) == 1, "Missing or duplicate draft release")
    release = api(f"repos/{REPOSITORY}/releases/{matches[0]['id']}")
    verify_published_assets(release, directory, request, True)
    require(api(f"repos/{REPOSITORY}/commits/{request['tag']}")["sha"] == commit,
            "Release tag changed")
    run("gh", "release", "edit", request["tag"], "--repo", REPOSITORY, "--draft=false")
    release = api(f"repos/{REPOSITORY}/releases/{release['id']}")
    verify_published_assets(release, directory, request, False)
    require(api(f"repos/{REPOSITORY}/commits/{request['tag']}")["sha"] == commit,
            "Published tag changed")
    write(ROOT / "build/published.json", {"url": release["html_url"], "tag": request["tag"],
                                        "identity": request["identity"], "core": request["core"],
                                        "assets": [asset["name"] for asset in release["assets"]]})
    print(release["html_url"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "assemble", "publish"))
    args = parser.parse_args()
    if args.command == "prepare":
        output = ROOT / "build/request.json"
        output.unlink(missing_ok=True)
        write(output, preflight(os.environ["RELEASE_TAG"]))
    elif args.command == "assemble":
        assemble(ROOT / "build/evidence", ROOT / "build/release")
    else:
        (ROOT / "build/published.json").unlink(missing_ok=True)
        publish(ROOT / "build/release")


if __name__ == "__main__":
    main()
