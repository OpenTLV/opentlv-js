# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Recovery binds original evidence to the same run without repeating partial writes."""

import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import publish_npm  # noqa: E402
import release  # noqa: E402

IDENTITY = {"repository": release.REPOSITORY, "commit": "a" * 40, "dirty": False,
            "hosted": True, "run_id": "123", "run_attempt": "2"}


class Recovery(unittest.TestCase):
    def test_release_state_rejects_foreign_tag_or_duplicate_releases(self):
        tag = "v0.2.1"
        ref = {"ref": "refs/tags/" + tag}
        draft = {"tag_name": tag, "id": 42}
        cases = [([], [], "a" * 40, (False, None)),
                 ([ref], [], "a" * 40, (True, None)),
                 ([ref], [draft], "a" * 40, (True, 42)),
                 ([ref], [draft, draft], "a" * 40, None),
                 ([], [draft], "a" * 40, None),
                 ([ref], [draft], "b" * 40, None)]
        for refs, releases, sha, expected in cases:
            with self.subTest(refs=refs, releases=releases, sha=sha), \
                    mock.patch.object(release, "api", side_effect=[
                        {"object": {"sha": IDENTITY["commit"]}}, refs, {"sha": sha}]), \
                    mock.patch.object(release, "pages", return_value=releases):
                if expected is None:
                    with self.assertRaises(ValueError):
                        release.release_state(tag, IDENTITY["commit"])
                else:
                    self.assertEqual(release.release_state(tag, IDENTITY["commit"]), expected)
        with mock.patch.object(release, "api", return_value={"object": {"sha": "b" * 40}}), \
                self.assertRaisesRegex(ValueError, "Main moved"):
            release.release_state(tag, IDENTITY["commit"])

    def test_publish_retry_revalidates_original_source_main_and_npm_request(self):
        request = {"identity": IDENTITY, "tag": "v0.2.1", "version": "0.2.1",
                   "core": release.core.load_lock(), "notes_sha256": release.digest(release.NOTES),
                   "main": {"run_id": 10, "run_attempt": 1}, "npm": {"latest": "0.2.0"}}
        with mock.patch.object(release, "hosted_identity", return_value=IDENTITY) as hosted, \
                mock.patch.object(release, "version_for", return_value="0.2.1"), \
                mock.patch.object(release, "main_evidence", return_value=request["main"]) as main, \
                mock.patch.object(release, "check_gates") as gates, \
                mock.patch.object(publish_npm, "preflight", return_value=request["npm"]) as npm:
            release.validate_publish_request(request)
            hosted.return_value = {**IDENTITY, "run_attempt": "3"}
            release.validate_publish_request(request)
            gates.assert_called_with(10, 1, release.MAIN_GATES)
            npm.assert_called_with("0.2.1")
            for change in ({"run_attempt": "1"}, {"run_id": "456"}, {"commit": "b" * 40},
                           {"dirty": True}, {"repository": "other"}, {"hosted": False}):
                hosted.return_value = {**IDENTITY, **change}
                with self.subTest(change=change), self.assertRaises(ValueError):
                    release.validate_publish_request(request)
            hosted.return_value = IDENTITY
            for field in ("version", "core", "notes_sha256"):
                with self.subTest(field=field), self.assertRaises(ValueError):
                    release.validate_publish_request({**request, field: "changed"})
            main.return_value = {"run_id": 11, "run_attempt": 1}
            with self.assertRaisesRegex(ValueError, "Main evidence changed"):
                release.validate_publish_request(request)
            main.return_value = request["main"]
            npm.return_value = {"latest": "0.3.0"}
            with self.assertRaisesRegex(ValueError, "npm release request changed"):
                release.validate_publish_request(request)

    def test_create_identity_and_partial_upload_failure_stop_before_publication(self):
        created = {"id": 42, "tag_name": "v0.2.1", "draft": True, "prerelease": False,
                   "html_url": "https://github.com/OpenTLV/opentlv-js/releases/untagged-example"}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "release-notes.md").write_text("notes", encoding="utf-8")
            (root / "package.tgz").write_bytes(b"archive")
            for change in ({"id": None}, {"id": "42"}, {"id": True}, {"id": -1},
                           {"tag_name": "wrong"}, {"draft": False}, {"prerelease": True}):
                with self.subTest(change=change), \
                        mock.patch.object(release, "run", return_value=json.dumps({**created, **change})), \
                        mock.patch.object(release, "upload_asset") as upload, self.assertRaises(ValueError):
                    release.create_draft(root, {"tag": "v0.2.1"})
                upload.assert_not_called()
            with mock.patch.object(release, "run", return_value=json.dumps(created)) as run, \
                    mock.patch.object(release, "upload_asset", side_effect=[None, OSError("interrupted")]), \
                    self.assertRaises(OSError):
                release.create_draft(root, {"tag": "v0.2.1"})
            self.assertEqual(run.call_count, 1)

    def test_upload_uses_exact_id_filename_and_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "archive name.tgz"
            path.write_bytes(b"tested archive")
            with mock.patch.dict(os.environ, {"GH_TOKEN": "test-token"}), \
                    mock.patch.object(release.urllib.request, "urlopen") as urlopen:
                urlopen.return_value.__enter__.return_value = io.BytesIO(b'{}')
                release.upload_asset(42, path)
            request = urlopen.call_args.args[0]
            self.assertEqual(request.full_url,
                             f"https://uploads.github.com/repos/{release.REPOSITORY}/releases/42/"
                             "assets?name=archive%20name.tgz")
            self.assertEqual(request.data, path.read_bytes())
            self.assertEqual(request.method, "POST")

    def test_artifact_selection_rejects_ambiguous_or_wrong_attempt_payloads(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(ValueError):
                release.select_payload(root)
            first = root / "js-release-2/release-manifest.json"
            release.write(first, {"request": {"identity": IDENTITY}})
            self.assertEqual(release.select_payload(root), first.parent)
            release.write(root / "js-release-3/release-manifest.json", {"request": {"identity": IDENTITY}})
            with self.assertRaisesRegex(ValueError, "exactly one"):
                release.select_payload(root)
            first.unlink()
            with self.assertRaisesRegex(ValueError, "attempt differs"):
                release.select_payload(root)

    def test_npm_selects_original_payload_after_github_publication_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "js-release-2").mkdir()
            record = {"identity": {**IDENTITY, "run_attempt": "3"}, "payload_identity": IDENTITY}
            path = root / "js-published-3/published.json"
            release.write(path, record)
            self.assertEqual(publish_npm.select(root, "123"), (record, root / "js-release-2"))
            for change in ({"run_attempt": "4"}, {"run_id": "456"}, {"commit": "b" * 40}):
                release.write(path, {**record, "payload_identity": {**IDENTITY, **change}})
                with self.subTest(change=change), self.assertRaisesRegex(ValueError, "payload identity"):
                    publish_npm.select(root, "123")

    def test_npm_checks_exact_release_id_without_relying_on_list_visibility(self):
        request = {"tag": "v0.2.1", "identity": IDENTITY, "core": {"commit": "core"}}
        published = {"id": 42, "html_url": "release-url", "assets": [{"name": "archive"}]}
        record = {"release_id": 42, "url": "release-url", "tag": "v0.2.1", "assets": ["archive"],
                  "core": request["core"], "identity": {**IDENTITY, "run_attempt": "3"},
                  "payload_identity": IDENTITY}
        with mock.patch.object(release, "pages", side_effect=AssertionError("No list lookup")), \
                mock.patch.object(release, "api", side_effect=[published, {"sha": IDENTITY["commit"]}]), \
                mock.patch.object(release, "verify_published_assets") as verify:
            self.assertEqual(publish_npm.check_github_release(Path("payload"), request, record), "release-url")
        verify.assert_called_once_with(published, Path("payload"), request, False)


if __name__ == "__main__":
    unittest.main()
