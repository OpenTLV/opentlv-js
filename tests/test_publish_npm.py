# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""npm receives only the approved, attested release archive, once, with provenance from this workflow."""

import base64
import copy
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ci  # noqa: E402
import package  # noqa: E402
import publish_npm  # noqa: E402
import release  # noqa: E402

IDENTITY = {"repository": release.REPOSITORY, "commit": "a" * 40, "dirty": False,
            "hosted": True, "run_id": "123", "run_attempt": "1"}
NPM = {"package": package.NAME, "environment": "npm", "latest": "0.1.0"}
ENVIRONMENT = {"name": "npm", "can_admins_bypass": False,
               "protection_rules": [{"type": "required_reviewers", "reviewers": [{"type": "User"}]}],
               "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}
BRANCHES = {"branch_policies": [{"name": "main", "type": "branch"}]}


def archive(path, version="0.2.0", **changes):
    manifest = {"name": package.NAME, "version": version, "repository": package.REPOSITORY, **changes}
    data = json.dumps(manifest).encode()
    with tarfile.open(path, "w:gz") as bundle:
        info = tarfile.TarInfo("package/package.json")
        info.size = len(data)
        bundle.addfile(info, io.BytesIO(data))


def statement(plan, **changes):
    value = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": f"pkg:npm/%40opentlv/opentlv@{plan['version']}", "digest": {"sha512": plan["sha512"]}}],
        "predicateType": publish_npm.SLSA,
        "predicate": {
            "buildDefinition": {
                "externalParameters": {"workflow": {"ref": "refs/heads/main",
                                                    "repository": "https://github.com/OpenTLV/opentlv-js",
                                                    "path": ".github/workflows/js-release.yml"}},
                "internalParameters": {"github": {"event_name": "workflow_dispatch"}},
                "resolvedDependencies": [{"uri": "git+https://github.com/OpenTLV/opentlv-js@refs/heads/main",
                                          "digest": {"gitCommit": IDENTITY["commit"]}}]},
            "runDetails": {"metadata": {"invocationId":
                                        "https://github.com/OpenTLV/opentlv-js/actions/runs/123/attempts/2"}}}}
    for path, replacement in changes.items():
        target = value
        *parents, key = path.split(".")
        for parent in parents:
            target = target[parent]
        target[key] = replacement
    payload = base64.b64encode(json.dumps(value).encode()).decode()
    return {"attestations": [{"predicateType": publish_npm.SLSA, "bundle": {"dsseEnvelope": {"payload": payload}}}]}


class Gate(unittest.TestCase):
    def test_environment_requires_reviewer_main_only_and_no_bypass(self):
        with mock.patch.object(release, "api", side_effect=[ENVIRONMENT, BRANCHES]):
            publish_npm.check_environment()
        for change in ({"protection_rules": []},
                       {"protection_rules": [{"type": "required_reviewers", "reviewers": []}]},
                       {"protection_rules": [{"type": "wait_timer", "wait_timer": 5}]},
                       {"can_admins_bypass": True}, {"deployment_branch_policy": None},
                       {"deployment_branch_policy": {"protected_branches": True, "custom_branch_policies": False}}):
            with self.subTest(change=change), \
                    mock.patch.object(release, "api", side_effect=[{**ENVIRONMENT, **change}, BRANCHES]), \
                    self.assertRaises(ValueError):
                publish_npm.check_environment()
        for branches in ([], [{"name": "main", "type": "branch"}, {"name": "dev", "type": "branch"}],
                         [{"name": "*", "type": "branch"}], [{"name": "main", "type": "tag"}]):
            with self.subTest(branches=branches), \
                    mock.patch.object(release, "api", side_effect=[ENVIRONMENT, {"branch_policies": branches}]), \
                    self.assertRaises(ValueError):
                publish_npm.check_environment()

    def test_registry_needs_the_bootstrapped_package_and_a_newer_version(self):
        published = {"versions": {"0.1.0": {}}, "dist-tags": {"latest": "0.1.0"}}
        with mock.patch.object(publish_npm, "registry", return_value=published):
            self.assertEqual(publish_npm.check_registry("0.2.0"), "0.1.0")
            self.assertEqual(publish_npm.check_registry("0.1.1"), "0.1.0")
            for version, message in (("0.1.0", "already has"), ("0.0.9", "newer"), ("0.2.0-rc.1", "stable")):
                with self.subTest(version=version), self.assertRaisesRegex(ValueError, message):
                    publish_npm.check_registry(version)
        with mock.patch.object(publish_npm, "registry", return_value=None), \
                self.assertRaisesRegex(ValueError, "manually"):
            publish_npm.check_registry("0.2.0")

    def test_preflight_checks_privacy_before_any_remote_state(self):
        public = package.metadata(package.ROOT)
        self.assertNotIn("private", public)
        with mock.patch.object(package, "metadata", return_value={**public, "private": True}), \
                mock.patch.object(publish_npm, "check_environment") as environment, \
                mock.patch.object(publish_npm, "registry") as registry, \
                self.assertRaisesRegex(ValueError, "private"):
            publish_npm.preflight("0.2.0")
        environment.assert_not_called()
        registry.assert_not_called()
        with mock.patch.object(package, "metadata", return_value=public), \
                mock.patch.object(publish_npm, "check_environment") as environment, \
                mock.patch.object(publish_npm, "check_registry", return_value="0.1.0"):
            self.assertEqual(publish_npm.preflight("0.2.0"), NPM)
            environment.assert_called_once_with()

    def test_approval_of_the_npm_environment_is_required(self):
        reviews = [{"state": "rejected", "environments": [{"name": "npm"}], "user": {"login": "x"}},
                   {"state": "approved", "environments": [{"name": "other"}], "user": {"login": "y"}}]
        with mock.patch.object(release, "api", return_value=reviews), self.assertRaisesRegex(ValueError, "approval"):
            publish_npm.check_approval("123")
        approved = reviews + [{"state": "approved", "environments": [{"name": "npm"}], "user": {"login": "owner"}}]
        with mock.patch.object(release, "api", return_value=approved) as api:
            self.assertEqual(publish_npm.check_approval("123"), ["owner"])
            api.assert_called_once_with(f"repos/{release.REPOSITORY}/actions/runs/123/approvals")

    def test_toolchain_is_pinned_for_trusted_publishing(self):
        for node, npm, ok in (("v22.14.0", publish_npm.NPM_CLI, True), ("v22.22.2", publish_npm.NPM_CLI, True),
                              ("v22.13.1", publish_npm.NPM_CLI, False), ("v24.15.0", publish_npm.NPM_CLI, False),
                              ("v22.22.2", "10.9.4", False)):
            with self.subTest(node=node, npm=npm), mock.patch.object(release, "run", side_effect=[node, npm]):
                if ok:
                    self.assertEqual(publish_npm.toolchain(), {"node": node, "npm": npm})
                else:
                    with self.assertRaises(ValueError):
                        publish_npm.toolchain()


class Prepare(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.input = self.root / "build/npm-input"
        self.assets = self.input / "js-release-1"
        self.assets.mkdir(parents=True)
        self.archive = self.assets / "opentlv-opentlv-0.2.0.tgz"
        archive(self.archive)
        self.request = {"tag": "v0.2.0", "version": "0.2.0", "identity": dict(IDENTITY), "core": {"commit": "c"},
                        "npm": NPM}
        self.record = {"url": "https://github.com/OpenTLV/opentlv-js/releases/tag/v0.2.0", "tag": "v0.2.0",
                       "identity": dict(IDENTITY), "core": {"commit": "c"},
                       "assets": [self.archive.name, "SHA256SUMS"]}
        release.write(self.input / "js-published-1/published.json", self.record)
        self.hashes = publish_npm.hashes(self.archive)
        self.output = self.root / "output.txt"
        current = {**IDENTITY, "run_attempt": "2"}
        patches = {
            (release, "hosted_identity"): mock.Mock(return_value=current),
            (release, "verify_attestations"): mock.DEFAULT,
            (publish_npm, "toolchain"): mock.Mock(return_value={"node": "v22.22.2", "npm": publish_npm.NPM_CLI}),
            (publish_npm, "check_github_release"): mock.Mock(return_value=self.record["url"]),
            (publish_npm, "check_environment"): mock.DEFAULT,
            (publish_npm, "check_approval"): mock.Mock(return_value=["owner"]),
            (publish_npm, "ROOT"): self.root, (publish_npm, "WORK"): self.root / "build/npm"}
        self.mocks = {}
        for (target, name), value in patches.items():
            patcher = mock.patch.object(target, name, value)
            self.mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(self.output)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def prepare(self, published):
        with mock.patch.object(release, "verify_payload", side_effect=lambda directory, validate: self.request), \
                mock.patch.object(publish_npm, "registry", return_value=published):
            publish_npm.prepare(self.input)
        return json.loads((self.root / "build/npm/plan.json").read_text())

    def test_new_version_uploads_the_released_archive(self):
        plan = self.prepare({"versions": {"0.1.0": {}}, "dist-tags": {"latest": "0.1.0"}})
        self.assertTrue(plan["upload"])
        self.assertEqual(plan["integrity"], self.hashes["integrity"])
        self.assertEqual(plan["approved_by"], ["owner"])
        self.assertEqual((self.root / "build/npm" / self.archive.name).read_bytes(), self.archive.read_bytes())
        self.assertEqual(self.output.read_text(), f"upload=true\narchive=build/npm/{self.archive.name}\n")
        self.mocks["verify_attestations"].assert_called_once_with(self.assets, IDENTITY["commit"])

    def test_retry_confirms_identical_bytes_but_never_replaces_them(self):
        same = {"versions": {"0.2.0": {"dist": {"integrity": self.hashes["integrity"],
                                               "shasum": self.hashes["shasum"]}}}}
        self.assertFalse(self.prepare(same)["upload"])
        self.assertIn("upload=false\n", self.output.read_text())
        shutil_root = self.root / "build/npm"
        for path in shutil_root.iterdir():
            path.unlink()
        shutil_root.rmdir()
        other = copy.deepcopy(same)
        other["versions"]["0.2.0"]["dist"]["shasum"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "different bytes"):
            self.prepare(other)
        self.assertFalse(shutil_root.exists())

    def test_missing_package_needs_the_manual_bootstrap(self):
        with self.assertRaisesRegex(ValueError, "manually"):
            self.prepare(None)

    def test_private_or_foreign_archive_is_rejected(self):
        for changes in ({"private": True}, {"name": "opentlv-js"}, {"version": "0.1.0"},
                        {"repository": {"type": "git", "url": "git+https://github.com/fork/opentlv-js.git"}}):
            archive(self.archive, **changes)
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "trusts"):
                self.prepare({"versions": {}})

    def test_publication_must_come_from_this_run(self):
        record = self.input / "js-published-1/published.json"
        release.write(record, {**self.record, "identity": {**IDENTITY, "run_id": "999"}})
        with self.assertRaisesRegex(ValueError, "this run"):
            publish_npm.select(self.input, "123")
        release.write(record, self.record)
        release.write(self.input / "js-published-2/published.json", self.record)
        with self.assertRaisesRegex(ValueError, "one GitHub release"):
            publish_npm.select(self.input, "123")

    def test_request_binds_the_preparing_attempt(self):
        current = {**IDENTITY, "run_attempt": "2"}
        with mock.patch.object(release, "version_for", return_value="0.2.0"), \
                mock.patch.object(release, "core_release", return_value={"commit": "c"}):
            publish_npm.check_request(self.request, current)
            for request, changed in ((dict(self.request, npm=None), current),
                                     (self.request, {**current, "commit": "b" * 40}),
                                     (self.request, {**current, "run_id": "124"}),
                                     (self.request, {**current, "run_attempt": "0"}),
                                     (dict(self.request, core={"commit": "d"}), current)):
                with self.subTest(request=request, current=changed), self.assertRaises(ValueError):
                    publish_npm.check_request(request, changed)


class Confirm(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        path = self.work / "opentlv-opentlv-0.2.0.tgz"
        archive(path)
        self.plan = {"version": "0.2.0", "tag": "v0.2.0", "release": "url", "identity": dict(IDENTITY),
                     "approved_by": ["owner"], "upload": True, **publish_npm.hashes(path)}
        release.write(self.work / "plan.json", self.plan)
        self.attestations = {"url": f"{publish_npm.REGISTRY}/-/npm/v1/attestations/@opentlv%2fopentlv@0.2.0",
                             "provenance": {"predicateType": publish_npm.SLSA}}
        self.info = {"name": package.NAME, "version": "0.2.0",
                     "dist": {"integrity": self.plan["integrity"], "shasum": self.plan["shasum"],
                              "attestations": self.attestations}}
        for name, value in (("WORK", self.work), ("audit", mock.DEFAULT)):
            patcher = mock.patch.object(publish_npm, name, value)
            self.addCleanup(patcher.stop)
            patcher.start()

    def registry(self, info, bundle, latest="0.2.0"):
        def reply(url):
            if url.endswith("/0.2.0"):
                return info
            if "/-/npm/v1/attestations/" in url:
                return bundle
            return {"dist-tags": {"latest": latest}}
        return mock.patch.object(publish_npm, "registry", side_effect=reply)

    def test_receipt_records_the_provenance_of_this_run(self):
        with self.registry(self.info, statement(self.plan)):
            publish_npm.confirm(attempts=1)
        receipt = json.loads((self.work / "receipt.json").read_text())
        self.assertEqual(receipt["provenance"], "https://github.com/OpenTLV/opentlv-js/actions/runs/123/attempts/2")
        self.assertEqual((receipt["integrity"], receipt["approved_by"]), (self.plan["integrity"], ["owner"]))
        publish_npm.audit.assert_called_once()

    def test_foreign_or_missing_provenance_is_rejected(self):
        for changes in ({"subject": [{"name": "pkg:npm/%40opentlv/opentlv@0.2.0", "digest": {"sha512": "0"}}]},
                        {"predicate.buildDefinition.externalParameters.workflow.path": ".github/workflows/other.yml"},
                        {"predicate.buildDefinition.externalParameters.workflow.ref": "refs/heads/feature"},
                        {"predicate.buildDefinition.internalParameters.github.event_name": "push"},
                        {"predicate.buildDefinition.resolvedDependencies": [{"digest": {"gitCommit": "b" * 40}}]},
                        {"predicate.runDetails.metadata.invocationId":
                         "https://github.com/OpenTLV/opentlv-js/actions/runs/999/attempts/1"}):
            with self.subTest(changes=changes), self.registry(self.info, statement(self.plan, **changes)), \
                    self.assertRaisesRegex(ValueError, "provenance"):
                publish_npm.confirm(attempts=1)
        with self.registry(self.info, {"attestations": []}), self.assertRaisesRegex(ValueError, "provenance"):
            publish_npm.confirm(attempts=1)
        publish_npm.audit.assert_not_called()

    def test_registry_must_serve_the_planned_bytes_as_latest(self):
        changed = copy.deepcopy(self.info)
        changed["dist"]["integrity"] = "sha512-other"
        with self.registry(changed, statement(self.plan)), self.assertRaisesRegex(ValueError, "bytes differ"):
            publish_npm.confirm(attempts=1)
        unattested = copy.deepcopy(self.info)
        unattested["dist"].pop("attestations")
        for info, latest in ((None, "0.2.0"), (unattested, "0.2.0"), (self.info, "0.1.0")):
            with self.subTest(info=info, latest=latest), self.registry(info, statement(self.plan), latest), \
                    self.assertRaisesRegex(ValueError, "does not serve"):
                publish_npm.confirm(attempts=1)
        self.assertFalse((self.work / "receipt.json").exists())


class Verify(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        served = self.root / "served"
        served.mkdir()
        path = served / "opentlv-opentlv-0.2.0.tgz"
        archive(path)
        with tarfile.open(path, "r:gz") as bundle:
            files = {"package.json": package.digest(bundle.extractfile("package/package.json").read())}
        (served / "release-notes.md").write_text("# OpenTLV JS v0.2.0\n\n- Notes\n", encoding="utf-8")
        release.write(served / "release-manifest.json", {
            "schema": 1, "package": {"archive_sha256": release.digest(path), "files": files},
            "request": {"tag": "v0.2.0", "version": "0.2.0", "identity": dict(IDENTITY),
                        "notes_sha256": release.digest(served / "release-notes.md")}})
        (served / "SHA256SUMS").write_text("".join(
            f"{release.digest(item)}  {item.name}\n" for item in sorted(served.iterdir())), encoding="utf-8")
        self.github = {"draft": False, "prerelease": False,
                       "html_url": "https://github.com/OpenTLV/opentlv-js/releases/tag/v0.2.0",
                       "assets": [{"name": item.name, "size": item.stat().st_size,
                                   "digest": "sha256:" + release.digest(item), "browser_download_url": item.as_uri()}
                                  for item in sorted(served.iterdir())]}
        self.served = served
        self.expected = publish_npm.hashes(path)
        self.plan = {**self.expected, "version": "0.2.0", "identity": dict(IDENTITY)}
        self.info = {"name": package.NAME, "version": "0.2.0", "repository": package.REPOSITORY,
                     "dist": {"integrity": self.expected["integrity"], "shasum": self.expected["shasum"]}}
        self.replies = {"tag": self.github, "commit": {"sha": IDENTITY["commit"]}, "info": self.info,
                        "packument": {"dist-tags": {"latest": "0.2.0"}}, "attestations": statement(self.plan)}
        runner = mock.Mock()
        runner.return_value.run.side_effect = lambda name, *args, **kwargs: {
            "node-version": "v22.16.0", "npm-version": "10.9.2"}[name]
        runner.return_value.env, runner.return_value.commands = {}, []
        for target, name, value in ((publish_npm, "audit", mock.DEFAULT), (publish_npm, "registry", self.registry),
                                    (package, "check_clean_consumer", mock.Mock(return_value="Chrome")),
                                    (publish_npm.shutil, "which", mock.Mock(return_value="/bin/npm")),
                                    (ci, "Runner", runner)):
            patcher = mock.patch.object(target, name, value)
            self.addCleanup(patcher.stop)
            patcher.start()
        self.runs = 0

    def registry(self, url):
        for suffix, key in (("/releases/tags/v0.2.0", "tag"), ("/commits/v0.2.0", "commit"), ("%2fopentlv/0.2.0", "info"),
                            ("%2fopentlv", "packument"), ("@opentlv%2fopentlv@0.2.0", "attestations")):
            if url.endswith(suffix):
                return copy.deepcopy(self.replies[key])
        raise AssertionError(url)

    def verify(self, unattested=False):
        self.runs += 1
        return publish_npm.verify("0.2.0", self.root / f"verify-{self.runs}", unattested)

    def test_manual_first_version_is_accepted_only_without_provenance_by_request(self):
        with self.assertRaisesRegex(ValueError, "provenance"):
            self.verify()
        receipt = json.loads(self.verify(unattested=True).read_text())
        self.assertIsNone(receipt["provenance"])
        self.assertEqual((receipt["integrity"], receipt["browser"], receipt["commit"]),
                         (self.expected["integrity"], "Chrome", IDENTITY["commit"]))
        runner, npm, spec, files, common = package.check_clean_consumer.call_args.args
        self.assertEqual((npm, spec), ("/bin/npm", "@opentlv/opentlv@0.2.0"))
        self.assertEqual(files, {"package.json": mock.ANY})
        self.assertEqual(common[common.index("--registry") + 1], publish_npm.REGISTRY + "/")
        publish_npm.audit.assert_called_with({"version": "0.2.0", "integrity": self.expected["integrity"]})

    def test_later_versions_cannot_skip_provenance(self):
        self.assertEqual(publish_npm.UNATTESTED, "0.2.0")
        for version in ("0.2.1", "0.3.0", "1.0.0", "0.1.0"):
            output = self.root / f"later-{version}"
            with self.subTest(version=version), mock.patch.object(publish_npm, "registry") as registry, \
                    self.assertRaisesRegex(ValueError, "Only the manually published first version 0.2.0"):
                publish_npm.verify(version, output, unattested=True)
            registry.assert_not_called()
            self.assertFalse(output.exists())

    def test_published_provenance_must_name_the_release_run(self):
        self.info["dist"]["attestations"] = {"url": f"{publish_npm.REGISTRY}/-/npm/v1/attestations/"
                                                    "@opentlv%2fopentlv@0.2.0",
                                             "provenance": {"predicateType": publish_npm.SLSA}}
        receipt = json.loads(self.verify().read_text())
        self.assertEqual(receipt["provenance"], "https://github.com/OpenTLV/opentlv-js/actions/runs/123/attempts/2")
        self.replies["attestations"] = statement(self.plan, **{
            "predicate.runDetails.metadata.invocationId":
                "https://github.com/OpenTLV/opentlv-js/actions/runs/999/attempts/1"})
        with self.assertRaisesRegex(ValueError, "provenance"):
            self.verify(unattested=True)

    def test_registry_or_release_differences_fail_before_installing(self):
        for key, change, message in (
                ("info", {"dist": {"integrity": "sha512-other", "shasum": "0" * 40}}, "bytes differ"),
                ("info", {"private": True}, "metadata"),
                ("info", {"repository": {"type": "git", "url": "git+https://github.com/fork/opentlv-js.git"}},
                 "metadata"),
                ("packument", {"dist-tags": {"latest": "0.1.0"}}, "latest"),
                ("commit", {"sha": "b" * 40}, "commit"),
                ("tag", {"draft": True}, "public GitHub release"),
                ("tag", {"assets": self.github["assets"][:3]}, "asset set")):
            original = copy.deepcopy(self.replies[key])
            self.replies[key].update(change)
            with self.subTest(key=key, change=change), self.assertRaisesRegex(ValueError, message):
                self.verify(unattested=True)
            self.replies[key] = original
        self.replies["info"] = None
        with self.assertRaisesRegex(ValueError, "npm has no"):
            self.verify(unattested=True)
        self.replies["info"] = self.info
        (self.served / "release-notes.md").write_text("# Changed\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "differs: release-notes.md"):
            self.verify(unattested=True)
        package.check_clean_consumer.assert_not_called()
        publish_npm.audit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
