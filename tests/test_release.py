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
import publish_npm  # noqa: E402
import release  # noqa: E402

IDENTITY = {"repository": release.REPOSITORY, "commit": "a" * 40, "dirty": False,
            "hosted": True, "run_id": "123", "run_attempt": "2"}
LOCK_KEYS = ("repository", "commit", "tree", "source_sha256", "version_inputs")


def workflow(name):
    return (release.ROOT / ".github/workflows" / name).read_text(encoding="utf-8")


class Preflight(unittest.TestCase):
    def test_version_and_notes_match_the_release(self):
        version = release.package.metadata(release.ROOT)["version"]
        tag = "v" + version
        changelog = (release.ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        closed = changelog.replace("## [Unreleased]", f"## [{version}] - 2026-11-03")
        original = Path.read_text
        with mock.patch.object(Path, "read_text", lambda path, *args, **kwargs: closed
                               if path.name == "CHANGELOG.md" else original(path, *args, **kwargs)):
            self.assertEqual(release.version_for(tag), version)
        for invalid in ("", "v0.8.0", "0.1.0", "V0.1.0", "v0.1", "v0.1.0-dev.0", "v00.1.0",
                        " " + tag, "v0.1.0", "../main"):
            with self.subTest(tag=invalid), self.assertRaises(ValueError):
                release.version_for(invalid)

    def test_release_requires_a_closed_changelog_section(self):
        version = release.package.metadata(release.ROOT)["version"]
        original = Path.read_text
        for heading in ("## [Unreleased]", f"## [{version}]"):
            with mock.patch.object(Path, "read_text", lambda path, *args, **kwargs: heading
                                   if path.name == "CHANGELOG.md" else original(path, *args, **kwargs)), \
                    self.assertRaisesRegex(ValueError, "changelog"):
                release.version_for("v" + version)

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
        for name in ("validate_request", "validate_publish_request", "check_gates"):
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
                mock.patch.object(release, "release_state") as unused, \
                self.assertRaises(subprocess.CalledProcessError):
            release.publish(self.output, self.root / "journals")
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

    def publish(self, state=(False, None), remote=None, listed=None, fail=None):
        draft = remote or self.published()
        replies = [draft, {"sha": IDENTITY["commit"]},
                   self.published(draft=False), {"sha": IDENTITY["commit"]}]
        def command(*args, **kwargs):
            if args[1:4] == ("api", "--method", "POST") and args[4].endswith("/releases"):
                return json.dumps(self.published())
            if fail and args[1:4] == ("api", "--method", "PATCH"):
                raise subprocess.CalledProcessError(1, "gh")
            return None
        with mock.patch.object(release, "run", side_effect=command) as run, \
                mock.patch.object(release, "upload_asset") as upload, \
                mock.patch.object(release, "release_state", return_value=state), \
                mock.patch.object(release, "pages", return_value=listed or []), \
                mock.patch.object(release, "api", side_effect=replies), \
                mock.patch.object(release, "hosted_identity", return_value={**IDENTITY, "run_attempt": "3"}), \
                mock.patch.object(release, "ROOT", self.root), mock.patch("builtins.print"):
            try:
                release.publish(self.output, self.root / "journals")
            finally:
                self.calls = [call.args for call in run.call_args_list]
                self.uploads = upload.call_args_list

    def writes(self, method):
        return [args for args in self.calls if args[1:4] == ("api", "--method", method)]

    def test_creation_uses_returned_identity_despite_delayed_listing(self):
        self.assemble()
        self.publish()
        self.assertEqual(len(self.writes("POST")), 2)
        self.assertEqual({call.args[0] for call in self.uploads}, {42})
        self.assertEqual({call.args[1].name for call in self.uploads},
                         {path.name for path in self.output.iterdir()})
        self.assertEqual(self.writes("PATCH"), [("gh", "api", "--method", "PATCH",
                         f"repos/{release.REPOSITORY}/releases/42", "-F", "draft=false")])
        record = release.read(self.root / "build/published.json")
        self.assertEqual(record["release_id"], 42)
        self.assertEqual(record["identity"]["run_attempt"], "3")
        self.assertEqual(record["payload_identity"], IDENTITY)
        self.assertEqual(release.read(self.root / release.JOURNAL), {
            "schema": 1, "tag": self.request["tag"], "commit": IDENTITY["commit"], "run_id": "123",
            "payload_attempt": "2", "attempt": "3", "draft_requested": True, "release_id": 42})

    def test_untagged_attempt_journals_no_draft_before_its_first_write(self):
        self.assemble()
        journals = []

        def command(*args, **kwargs):
            journals.append(release.read(self.root / release.JOURNAL))
            raise subprocess.CalledProcessError(1, "gh")
        with mock.patch.object(release, "run", side_effect=lambda *args, **kwargs:
                               None if args[1:3] == ("attestation", "verify") else command(*args)), \
                mock.patch.object(release, "release_state", return_value=(False, None)), \
                mock.patch.object(release, "hosted_identity", return_value=IDENTITY), \
                mock.patch.object(release, "ROOT", self.root), self.assertRaises(subprocess.CalledProcessError):
            release.publish(self.output, self.root / "journals")
        self.assertEqual(len(journals), 1)
        self.assertIs(journals[0]["draft_requested"], False)
        self.assertIsNone(journals[0]["release_id"])

    def test_tag_only_retry_creates_only_the_draft(self):
        self.assemble()
        self.publish(state=(True, None))
        self.assertEqual(len(self.writes("POST")), 1)
        self.assertTrue(self.writes("POST")[0][4].endswith("/releases"))

    def test_matching_draft_retry_never_reuploads_assets(self):
        self.assemble()
        self.publish(state=(True, 42))
        self.assertEqual(self.writes("POST"), [])
        self.assertEqual(self.uploads, [])
        self.assertEqual(len(self.writes("PATCH")), 1)

    def test_public_release_retry_only_verifies_and_records(self):
        self.assemble()
        self.publish(state=(True, 42), remote=self.published(False))
        self.assertEqual(self.writes("POST") + self.writes("PATCH"), [])
        self.assertEqual(self.uploads, [])

    def test_partial_mismatched_or_conflicting_drafts_fail_without_writes(self):
        self.assemble()
        for kind in ("partial", "duplicate", "extra", "digest", "size", "state", "body",
                     "tag", "prerelease", "id", "listed_id", "listed_duplicate"):
            draft = self.published()
            listed = []
            if kind == "partial":
                draft["assets"].pop()
            elif kind in ("duplicate", "extra"):
                draft["assets"].append({**draft["assets"][0], "name":
                                        "extra" if kind == "extra" else draft["assets"][0]["name"]})
            elif kind in ("digest", "size", "state"):
                draft["assets"][0][kind] = "wrong"
            elif kind in ("body", "tag", "prerelease", "id"):
                draft[{"tag": "tag_name"}.get(kind, kind)] = "wrong"
            elif kind == "listed_id":
                listed = [{"tag_name": self.request["tag"], "id": 99}]
            else:
                listed = [draft, draft]
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.publish(state=(True, 42), remote=draft, listed=listed)
            self.assertEqual(self.writes("POST") + self.writes("PATCH"), [])
            self.assertEqual(self.uploads, [])

    def test_failed_publication_can_retry_the_same_verified_draft(self):
        self.assemble()
        with self.assertRaises(subprocess.CalledProcessError):
            self.publish(state=(True, 42), fail=True)
        self.assertFalse((self.root / "build/published.json").exists())
        self.publish(state=(True, 42))
        self.assertTrue((self.root / "build/published.json").exists())
        self.assertEqual(self.writes("POST"), [])



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

    def test_publish_job_keeps_the_draft_journal_of_every_attempt(self):
        text = workflow("js-release.yml")
        job = text[text.index("  publish:\n"):text.index("  npm:\n    name:")]
        steps = [job.index(marker) for marker in (
            "          pattern: js-release-*\n          path: build/publish-input\n",
            "          pattern: js-draft-*\n          path: build/publish-state-input\n",
            "run: python3 -B scripts/release.py publish\n",
            "        if: always()\n        with:\n          name: js-draft-${{ github.run_attempt }}\n"
            "          path: build/publish-state/draft.json\n          if-no-files-found: ignore\n",
            "          name: js-published-${{ github.run_attempt }}\n")]
        self.assertEqual(steps, sorted(steps))
        self.assertEqual(release.JOURNAL.as_posix(), "build/publish-state/draft.json")

    def test_npm_follows_the_github_release_behind_the_approved_environment(self):
        text = workflow("js-release.yml")
        self.assertIn("      npm:\n        description:", text)
        self.assertIn("        type: boolean\n        default: false\n", text)
        self.assertIn("          NPM_PUBLISH: ${{ inputs.npm }}\n", text)
        job = text[text.index("  npm:\n    name:"):]
        self.assertIn("    needs: [prepare, publish]\n    if: inputs.npm\n", job)
        self.assertIn("    environment:\n      name: npm\n", job)
        self.assertIn("      id-token: write\n", job)
        self.assertNotIn("contents: write", job)
        self.assertEqual(text.count("id-token: write"), 2)
        self.assertIn(f"npm@{publish_npm.NPM_CLI}\n", job)
        self.assertNotIn("registry-url", job)
        steps = [job.index(marker) for marker in (
            "run: python3 -B scripts/publish_npm.py prepare\n",
            "if: steps.prepare.outputs.upload == 'true'",
            '          npm publish "./$ARCHIVE" --access public --provenance --tag latest --ignore-scripts\n',
            "run: python3 -B scripts/publish_npm.py confirm\n")]
        self.assertEqual(steps, sorted(steps))
        self.assertIn("pattern: js-release-*\n", job)
        self.assertIn("pattern: js-published-*\n", job)

    def test_npm_request_is_recorded_and_revalidated(self):
        for value, expected in (("true", True), ("false", False)):
            with mock.patch.dict(os.environ, {"NPM_PUBLISH": value}):
                self.assertIs(release.npm_requested(), expected)
        with mock.patch.dict(os.environ, {"NPM_PUBLISH": "yes"}), self.assertRaises(ValueError):
            release.npm_requested()
        with mock.patch.object(release, "preflight", return_value={"tag": "v0.1.0", "npm": None}) as preflight:
            release.validate_request({"tag": "v0.1.0", "npm": None})
            preflight.assert_called_once_with("v0.1.0", False)
        registry = {"package": "@opentlv/opentlv", "environment": "npm", "latest": None}
        with mock.patch.object(release, "preflight", return_value={"tag": "v0.1.0", "npm": registry}) as preflight:
            release.validate_request({"tag": "v0.1.0", "npm": registry})
            preflight.assert_called_once_with("v0.1.0", True)
            with self.assertRaisesRegex(ValueError, "changed"):
                release.validate_request({"tag": "v0.1.0", "npm": None})

    def test_private_package_cannot_request_npm_before_full_ci(self):
        private = {**json.loads((release.ROOT / "package.json").read_text(encoding="utf-8")), "private": True}
        with mock.patch.object(release, "version_for", return_value="0.1.0"), \
                mock.patch.object(publish_npm.package, "metadata", return_value=private), \
                mock.patch.object(release, "hosted_identity", return_value=IDENTITY), \
                mock.patch.object(release, "unused_tag"), mock.patch.object(release, "check_gates"), \
                mock.patch.object(release, "main_evidence", return_value={"run_id": 1, "run_attempt": 1}), \
                mock.patch.object(publish_npm, "check_environment") as environment, \
                mock.patch.object(publish_npm, "registry") as registry:
            self.assertIsNone(release.preflight("v0.1.0")["npm"])
            with self.assertRaisesRegex(ValueError, "private"):
                release.preflight("v0.1.0", True)
            environment.assert_not_called()
            registry.assert_not_called()

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
