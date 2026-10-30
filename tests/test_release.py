# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Release failures must precede writes; only the tested, current archive may ship."""

import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import core_dependency as core  # noqa: E402
import release  # noqa: E402

IDENTITY = {"repository": release.REPOSITORY, "commit": "a" * 40, "dirty": False,
            "hosted": True, "run_id": "123", "run_attempt": "2"}
LOCK_KEYS = ("repository", "commit", "tree", "source_sha256", "version_inputs")


def workflow(name):
    return (release.ROOT / ".github/workflows" / name).read_text(encoding="utf-8")


class Preflight(unittest.TestCase):
    def test_version_and_notes_match_the_first_release(self):
        self.assertEqual(release.version_for("v0.1.0"), "0.1.0")
        for tag in ("", "v0.8.0", "0.1.0", "V0.1.0", "v0.1", "v0.1.0-dev.0", "v00.1.0", " v0.1.0",
                    "../main"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                release.version_for(tag)

    def test_release_requires_a_closed_changelog_section(self):
        changelog = (release.ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        for text in (changelog.replace("## [0.1.0] - 2026-10-28", "## [Unreleased]"),
                     changelog.replace("## [0.1.0] - 2026-10-28", "## [0.1.0]")):
            original = Path.read_text
            with self.subTest(text=text[:200]), \
                    mock.patch.object(Path, "read_text", lambda self, *args, **kwargs: text
                                      if self.name == "CHANGELOG.md" else original(self, *args, **kwargs)), \
                    self.assertRaisesRegex(ValueError, "changelog"):
                release.version_for("v0.1.0")

    def test_core_lock_must_be_the_exact_release_commit(self):
        lock = core.load_lock()
        self.assertEqual(release.core_release(lock), lock)
        self.assertEqual(lock["version_inputs"]["tag"], "v0.8.0")
        inputs = lock["version_inputs"]
        for change in ({"revision": 40}, {"tag": "0.8.0"}, {"tag_commit": "b" * 40},
                       {"tags_at_commit": []}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "Core must"):
                release.core_release(dict(lock, version_inputs=dict(inputs, **change)))
        # The migration baseline was an untagged development commit.
        with self.assertRaisesRegex(ValueError, "Core must"):
            release.core_release(core.load_lock(release.ROOT / "ci/migration-core-source.json"))

    def test_dispatch_requires_official_main_workflow_and_commit(self):
        env = {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
               "GITHUB_SHA": IDENTITY["commit"],
               "GITHUB_WORKFLOW_REF": release.SIGNER + "@refs/heads/main",
               "GITHUB_WORKFLOW_SHA": IDENTITY["commit"]}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(release, "identity", return_value=IDENTITY):
            self.assertEqual(release.hosted_identity(), IDENTITY)
            for name in env:
                with mock.patch.dict(os.environ, {name: "other"}), self.assertRaises(ValueError):
                    release.hosted_identity()
        for key, value in (("dirty", True), ("hosted", False), ("repository", "fork/repo")):
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(release, "identity", return_value={**IDENTITY, key: value}), \
                    self.assertRaises(ValueError):
                release.hosted_identity()

    def test_main_identity_and_latest_failed_attempt(self):
        good = {"head_sha": IDENTITY["commit"], "event": "push", "head_branch": "main",
                "path": ".github/workflows/js-main.yml", "status": "completed",
                "repository": {"full_name": release.REPOSITORY},
                "head_repository": {"full_name": release.REPOSITORY},
                "conclusion": "success", "id": 100, "run_attempt": 2, "html_url": "main-url"}
        release.check_main(good, IDENTITY["commit"])
        for key in ("head_sha", "event", "head_branch", "path", "status", "conclusion"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                release.check_main({**good, key: "wrong"}, IDENTITY["commit"])
        with mock.patch.object(release, "pages", return_value=[good]):
            self.assertEqual(release.main_evidence(IDENTITY["commit"]),
                             {"run_id": 100, "run_attempt": 2, "url": "main-url"})
        with mock.patch.object(release, "pages", return_value=[
                good, {**good, "id": 101, "conclusion": "failure"}]), self.assertRaises(ValueError):
            release.main_evidence(IDENTITY["commit"])

    def test_unused_tag_rejects_existing_tag_draft_or_changed_main(self):
        main = {"object": {"sha": IDENTITY["commit"]}}
        with mock.patch.object(release, "api", side_effect=[main, []]), \
                mock.patch.object(release, "pages", return_value=[]):
            release.unused_tag("v0.1.0", IDENTITY["commit"])
        for refs, releases in (([{"ref": "refs/tags/v0.1.0"}], []),
                               ([], [{"tag_name": "v0.1.0", "draft": True}])):
            with mock.patch.object(release, "api", side_effect=[main, refs]), \
                    mock.patch.object(release, "pages", return_value=releases), \
                    self.assertRaises(ValueError):
                release.unused_tag("v0.1.0", IDENTITY["commit"])
        with mock.patch.object(release, "api", return_value={"object": {"sha": "b" * 40}}), \
                self.assertRaisesRegex(ValueError, "Main moved"):
            release.unused_tag("v0.1.0", IDENTITY["commit"])

    def test_gates_are_attempt_scoped_complete_and_unique(self):
        good = [{"name": name, "status": "completed", "conclusion": "success"}
                for name in sorted(release.FULL_GATES)]
        with mock.patch.object(release, "pages", return_value=good) as pages:
            release.check_gates("123", "2", release.FULL_GATES)
            pages.assert_called_once_with(
                f"repos/{release.REPOSITORY}/actions/runs/123/attempts/2/jobs", "jobs")
        for jobs in ([], good[:1], good + good[:1], [good[0], {**good[1], "conclusion": "skipped"}],
                     [good[0], {**good[1], "status": "in_progress"}]):
            with mock.patch.object(release, "pages", return_value=jobs), self.assertRaises(ValueError):
                release.check_gates("123", "2", release.FULL_GATES)


class Payload(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.evidence = self.root / "evidence"
        self.output = self.root / "release"
        lock = core.load_lock()
        self.request = {"schema": 1, "tag": "v0.1.0", "version": "0.1.0",
                        "identity": copy.deepcopy(IDENTITY), "core": lock,
                        "main": {"run_id": 100, "run_attempt": 1, "url": "main-url"},
                        "notes_sha256": release.digest(release.NOTES)}
        self.archive = self.evidence / "package/opentlv-opentlv-0.1.0.tgz"
        self.archive.parent.mkdir(parents=True)
        files = {"package.json": b'{"version":"0.1.0"}\n', "dist/opentlv-core.wasm": b"\0asm"}
        self.write_archive(self.archive, files)
        self.package = {"version": "0.1.0", "archive_sha256": release.digest(self.archive),
                        "files": {name: release.hashlib.sha256(data).hexdigest()
                                  for name, data in files.items()}}
        selection = dict(mode="pinned-source", dirty=False, **{key: lock[key] for key in LOCK_KEYS})
        self.records = {}
        for tier, configuration in release.RECORDS:
            record = {"schema": 1, "tier": tier, "configuration": configuration, "status": "passed",
                      "hosted": True, "repository": release.REPOSITORY, "sha": IDENTITY["commit"],
                      "checkout_commit": IDENTITY["commit"], "checkout_dirty": False,
                      "run_id": "123", "run_attempt": "2", "toolchain": {"node": "v22.16.0"},
                      "reproducibility_verified": tier == "release", "release_verified": False,
                      "builds": {name: {"core": copy.deepcopy(selection),
                                        "package": copy.deepcopy(self.package)}
                                 for name in (("first", "second") if tier == "release" else ("first",))}}
            if configuration == "Release":
                record["migration_compatibility"] = {"status": "passed"}
            self.records[(tier, configuration)] = record
            release.write(self.evidence / f"records/js-evidence-{tier}-{configuration}-2/result.json",
                          record)
        release.write(self.evidence / "request.json", self.request)
        for name in ("validate_request", "check_gates"):
            patcher = mock.patch.object(release, name)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def write_archive(path, files):
        with tarfile.open(path, "w:gz") as bundle:
            for name, data in files.items():
                info = tarfile.TarInfo("package/" + name)
                info.size = len(data)
                bundle.addfile(info, io.BytesIO(data))

    def assemble(self):
        release.assemble(self.evidence, self.output)

    def test_exact_tested_archive_and_complete_evidence(self):
        self.assemble()
        self.assertEqual(release.verify_payload(self.output), self.request)
        self.assertEqual(self.archive.read_bytes(), (self.output / self.archive.name).read_bytes())
        self.assertEqual({path.name for path in self.output.iterdir()},
                         {self.archive.name, "release-manifest.json", "release-notes.md", "SHA256SUMS"})
        release.check_gates.assert_called_with("123", "2", release.FULL_GATES)

    def test_incomplete_stale_unreproduced_or_foreign_core_evidence_is_rejected(self):
        for kind in ("missing", "attempt", "dirty", "failed", "core", "version", "reproduced",
                     "second", "migration", "node"):
            records = copy.deepcopy(self.records)
            full = records[("full", "Release")]
            repro = records[("release", "Release")]
            if kind == "missing":
                records.pop(("full", "Debug"))
            elif kind == "attempt":
                full["run_attempt"] = "1"
            elif kind == "dirty":
                full["checkout_dirty"] = True
            elif kind == "failed":
                records[("full", "Debug")]["status"] = "failed"
            elif kind == "core":
                full["builds"]["first"]["core"]["commit"] = "0" * 40
            elif kind == "version":
                repro["builds"]["second"]["package"]["version"] = "0.1.0-dev.0"
            elif kind == "reproduced":
                repro["reproducibility_verified"] = False
            elif kind == "second":
                repro["builds"]["second"]["package"]["archive_sha256"] = "0" * 64
            elif kind == "migration":
                full.pop("migration_compatibility")
            else:
                full["toolchain"]["node"] = "v20.0.0"
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                release.check_full(records, self.request)

    def test_missing_or_changed_archive_cannot_assemble(self):
        self.archive.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "tested package"):
            self.assemble()
        self.assertFalse(self.output.exists())
        self.archive.unlink()
        with self.assertRaisesRegex(ValueError, "archive set"):
            self.assemble()

    def test_recomputed_checksums_cannot_hide_replaced_archive(self):
        self.assemble()
        (self.output / self.archive.name).write_bytes(b"tampered")
        (self.output / "SHA256SUMS").write_text("".join(
            f"{release.digest(path)}  {path.name}\n" for path in sorted(self.output.iterdir())
            if path.name != "SHA256SUMS"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "tested package"):
            release.verify_payload(self.output)

    def test_changed_notes_extra_assets_and_checksums_are_rejected(self):
        self.assemble()
        for filename in ("release-notes.md", "SHA256SUMS", "extra.txt"):
            path = self.output / filename
            original = path.read_bytes() if path.exists() else None
            path.write_bytes(b"changed")
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                release.verify_payload(self.output)
            if original is None:
                path.unlink()
            else:
                path.write_bytes(original)

    def test_attestation_failure_precedes_any_publication_write(self):
        self.assemble()
        with mock.patch.object(release, "run", side_effect=subprocess.CalledProcessError(1, "gh")) as run, \
                mock.patch.object(release, "unused_tag") as unused, \
                self.assertRaises(subprocess.CalledProcessError):
            release.publish(self.output)
        self.assertEqual(run.call_args.args[1:3], ("attestation", "verify"))
        unused.assert_not_called()

    def published(self, draft=True):
        return {"id": 42, "html_url": "https://github.com/OpenTLV/opentlv-js/releases/tag/v0.1.0",
                "tag_name": "v0.1.0", "draft": draft, "prerelease": False,
                "body": release.NOTES.read_text(encoding="utf-8"),
                "assets": [{"name": path.name, "size": path.stat().st_size, "state": "uploaded",
                            "digest": "sha256:" + release.digest(path)}
                           for path in self.output.iterdir()]}

    def test_remote_asset_metadata_is_checked(self):
        self.assemble()
        published = self.published()
        release.verify_published_assets(published, self.output, self.request, True)
        for key, value in (("digest", "sha256:" + "0" * 64), ("size", 0), ("state", "new")):
            changed = copy.deepcopy(published)
            changed["assets"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                release.verify_published_assets(changed, self.output, self.request, True)
        for changed in ({**published, "assets": published["assets"][:-1]},
                        {**published, "body": "other"}, {**published, "prerelease": True}):
            with self.assertRaises(ValueError):
                release.verify_published_assets(changed, self.output, self.request, True)

    def test_publication_verifies_draft_before_making_it_public(self):
        self.assemble()
        draft = self.published()
        for corrupt in (False, True):
            remote = copy.deepcopy(draft)
            if corrupt:
                remote["assets"][0]["digest"] = "sha256:" + "0" * 64
            replies = [remote, {"sha": IDENTITY["commit"]},
                       self.published(draft=False), {"sha": IDENTITY["commit"]}]
            with self.subTest(corrupt=corrupt), mock.patch.object(release, "run") as run, \
                    mock.patch.object(release, "unused_tag"), \
                    mock.patch.object(release, "pages", return_value=[draft]), \
                    mock.patch.object(release, "api", side_effect=replies), \
                    mock.patch.object(release, "ROOT", self.root), mock.patch("builtins.print"):
                if corrupt:
                    with self.assertRaisesRegex(ValueError, "digest"):
                        release.publish(self.output)
                else:
                    release.publish(self.output)
                    published = json.loads((self.root / "build/published.json").read_text())
                    self.assertEqual(published["url"], draft["html_url"])
                calls = [call.args for call in run.call_args_list]
                self.assertTrue(all(args[1:3] == ("attestation", "verify") for args in calls[:4]))
                self.assertEqual(calls[4][1:4], ("api", "--method", "POST"))
                self.assertIn("--draft", calls[5])
                edits = [args for args in calls if args[1:3] == ("release", "edit")]
                self.assertEqual(len(edits), 0 if corrupt else 1)


class Workflow(unittest.TestCase):
    def test_no_tag_push_can_trigger_checks_or_publication(self):
        names = sorted(path.name for path in (release.ROOT / ".github/workflows").glob("*.yml"))
        self.assertIn("js-release.yml", names)
        for name in names:
            text = workflow(name)
            with self.subTest(workflow=name):
                self.assertNotIn("tags:", text)
                if "\n  push:" in text:
                    self.assertEqual(name, "js-main.yml")
                    self.assertIn("  push:\n    branches: [main]\n", text)
                if name != "js-release.yml":
                    self.assertNotIn("contents: write", text)
                    self.assertNotIn("release.py", text)

    def test_release_runs_full_before_attesting_and_publishing(self):
        text = workflow("js-release.yml")
        self.assertIn("on:\n  workflow_dispatch:\n    inputs:\n      tag:", text)
        self.assertIn("        required: true\n        type: string\n", text)
        self.assertNotIn("push:", text)
        self.assertIn("  full:\n    needs: prepare\n    uses: ./.github/workflows/js-full.yml\n", text)
        self.assertIn("  assemble:\n    needs: [prepare, full]\n", text)
        self.assertIn("  publish:\n    needs: [full, assemble]\n", text)
        self.assertEqual(text.count("contents: write"), 1)
        self.assertLess(text.index("  publish:"), text.index("contents: write"))
        self.assertLess(text.index("actions/attest-build-provenance@v3"), text.index("  publish:"))
        for command in ("prepare", "assemble", "publish"):
            self.assertIn(f"run: python3 -B scripts/release.py {command}\n", text)

    def test_full_includes_double_build_and_uploads_the_tested_archive(self):
        full = workflow("js-full.yml")
        self.assertIn("  checks:\n    uses: ./.github/workflows/js-checks.yml\n    with:\n      tier: full\n", full)
        self.assertIn("  reproducibility:\n    uses: ./.github/workflows/js-checks.yml\n"
                      "    with:\n      tier: release\n", full)
        checks = workflow("js-checks.yml")
        self.assertIn("if: success() && inputs.tier == 'release'", checks)
        self.assertIn("name: js-package-${{ github.run_attempt }}", checks)
        self.assertIn("path: build/ci/release/Release/first-package/opentlv-opentlv-*.tgz", checks)


if __name__ == "__main__":
    unittest.main()
