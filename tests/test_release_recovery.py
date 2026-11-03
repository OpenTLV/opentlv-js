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


TAG = "v0.2.1"
REQUEST = {"tag": TAG, "identity": IDENTITY}
NONE = {"present": False, "requested": False, "release_id": None}
CLEAN = {"present": True, "requested": False, "release_id": None}
REQUESTED = {"present": True, "requested": True, "release_id": None}
RECORDED = {"present": True, "requested": True, "release_id": 42}


def journal(attempt="2", **changes):
    return {"schema": 1, "tag": TAG, "commit": IDENTITY["commit"], "run_id": "123",
            "payload_attempt": "2", "attempt": attempt, "draft_requested": False, "release_id": None,
            **changes}


class Recovery(unittest.TestCase):
    def state(self, journal_state, tagged=True, listed=(), published=None, sha=IDENTITY["commit"]):
        replies = [{"object": {"sha": IDENTITY["commit"]}},
                   [{"ref": "refs/tags/" + TAG}] if tagged else [], {"sha": sha}]
        with mock.patch.object(release, "api", side_effect=replies), \
                mock.patch.object(release, "pages", return_value=list(listed)), \
                mock.patch.object(release, "published_release", return_value=published) as exact:
            try:
                return release.release_state(TAG, IDENTITY["commit"], journal_state)
            finally:
                self.exact = exact

    def test_recorded_draft_id_is_used_although_the_list_does_not_show_it(self):
        self.assertEqual(self.state(RECORDED), (True, 42))
        self.exact.assert_not_called()
        self.assertEqual(self.state(RECORDED, listed=[{"tag_name": TAG, "id": 42}]), (True, 42))
        for listed in ([{"tag_name": TAG, "id": 99}], [{"tag_name": TAG, "id": 42}] * 2):
            with self.subTest(listed=listed), self.assertRaises(ValueError):
                self.state(RECORDED, listed=listed)
        with self.assertRaisesRegex(ValueError, "lost its tag"):
            self.state(RECORDED, tagged=False)

    def test_requested_draft_without_recorded_id_never_creates_another(self):
        # The first attempt sent the creation, but its response was lost or malformed.
        for listed in ([], [{"tag_name": TAG, "id": 42}]):
            for tagged in (True, False):
                with self.subTest(listed=listed, tagged=tagged), \
                        self.assertRaisesRegex(ValueError, "without recording its release ID"):
                    self.state(REQUESTED, tagged=tagged, listed=listed)

    def test_tag_without_journal_is_resolved_only_through_the_exact_published_release(self):
        public = {"id": 42, "tag_name": TAG, "draft": False}
        self.assertEqual(self.state(NONE, published=public), (True, 42))
        self.exact.assert_called_once_with(TAG)
        for published in ({**public, "id": "42"}, {**public, "id": None}, {**public, "tag_name": "v0.2.0"}):
            with self.subTest(published=published), self.assertRaises(ValueError):
                self.state(NONE, published=published)
        with self.assertRaisesRegex(ValueError, "conflicting|Conflicting"):
            self.state(NONE, published=public, listed=[{"tag_name": TAG, "id": 99}])
        # A lost runner leaves no journal: an unlisted draft may exist, so nothing is created.
        with self.assertRaisesRegex(ValueError, "no publication journal"):
            self.state(NONE)

    def test_journaled_tag_only_attempt_may_create_its_draft(self):
        self.assertEqual(self.state(CLEAN), (True, None))
        with self.assertRaisesRegex(ValueError, "unrecorded release"):
            self.state(CLEAN, listed=[{"tag_name": TAG, "id": 42}])

    def test_untagged_foreign_or_duplicate_states_are_rejected(self):
        self.assertEqual(self.state(NONE, tagged=False), (False, None))
        cases = (dict(tagged=False, listed=[{"tag_name": TAG, "id": 42}]),
                 dict(listed=[{"tag_name": TAG, "id": 42}] * 2),
                 dict(sha="b" * 40))
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                self.state(RECORDED, **case)
        with mock.patch.object(release, "api", return_value={"object": {"sha": "b" * 40}}), \
                self.assertRaisesRegex(ValueError, "Main moved"):
            release.release_state(TAG, IDENTITY["commit"], NONE)

    def test_exact_published_release_lookup_distinguishes_absence_from_errors(self):
        found = mock.Mock(returncode=0, stdout='{"id": 42}', stderr="")
        missing = mock.Mock(returncode=1, stdout='{"message":"Not Found"}', stderr="gh: Not Found (HTTP 404)")
        failed = mock.Mock(returncode=1, stdout="", stderr="gh: Server Error (HTTP 502)")
        with mock.patch("builtins.print"), \
                mock.patch.object(release.subprocess, "run", side_effect=[found, missing, failed]) as run:
            self.assertEqual(release.published_release(TAG), {"id": 42})
            self.assertIsNone(release.published_release(TAG))
            with self.assertRaises(release.subprocess.CalledProcessError):
                release.published_release(TAG)
        self.assertEqual(run.call_args.args[0],
                         ["gh", "api", f"repos/{release.REPOSITORY}/releases/tags/{TAG}"])

    def test_journals_merge_only_this_run_and_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(release.load_journal(root, REQUEST), NONE)
            release.write(root / "js-draft-2/draft.json", journal())
            self.assertEqual(release.load_journal(root, REQUEST), CLEAN)
            release.write(root / "js-draft-3/draft.json", journal("3", draft_requested=True))
            self.assertEqual(release.load_journal(root, REQUEST), REQUESTED)
            release.write(root / "js-draft-4/draft.json", journal("4", draft_requested=True, release_id=42))
            self.assertEqual(release.load_journal(root, REQUEST), RECORDED)
            release.write(root / "js-draft-5/draft.json", journal("5", draft_requested=True, release_id=99))
            with self.assertRaisesRegex(ValueError, "different releases"):
                release.load_journal(root, REQUEST)
        for name, record in (("js-draft-3", journal()), ("js-draft-2", journal(tag="v0.2.0")),
                             ("js-draft-2", journal(commit="b" * 40)), ("js-draft-2", journal(run_id="456")),
                             ("js-draft-2", journal(payload_attempt="1")), ("js-draft-2", journal(schema=2)),
                             ("js-draft-2", journal(draft_requested="yes")),
                             ("js-draft-2", journal(release_id=42)),
                             ("js-draft-2", journal(draft_requested=True, release_id="42")),
                             ("js-draft-2", journal(draft_requested=True, release_id=0)),
                             ("js-draft-2", [journal()])):
            with self.subTest(name=name, record=record), tempfile.TemporaryDirectory() as temp:
                release.write(Path(temp) / name / "draft.json", record)
                with self.assertRaisesRegex(ValueError, "journal"):
                    release.load_journal(Path(temp), REQUEST)

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

    def test_malformed_or_incomplete_creation_responses_never_reach_upload(self):
        created = {"id": 42, "tag_name": TAG, "draft": True, "prerelease": False,
                   "html_url": "https://github.com/OpenTLV/opentlv-js/releases/untagged-example"}
        responses = ["", "not json", "{", "null", "[]", '"42"', "42", json.dumps([created]), "{}",
                     *(json.dumps({key: value for key, value in created.items() if key != missing})
                       for missing in ("id", "tag_name", "draft", "prerelease")),
                     *(json.dumps({**created, **change}) for change in (
                         {"id": None}, {"id": "42"}, {"id": True}, {"id": 0}, {"id": -1}, {"id": 4.2},
                         {"tag_name": "wrong"}, {"draft": False}, {"draft": "true"}, {"prerelease": True},
                         {"prerelease": None}))]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = root / "payload"
            payload.mkdir()
            (payload / "release-notes.md").write_text("notes", encoding="utf-8")
            (payload / "package.tgz").write_bytes(b"archive")
            # The last case: the request itself fails, with no response to interpret.
            for response in (*responses, release.subprocess.CalledProcessError(1, "gh")):
                side_effect = response if isinstance(response, Exception) else [response]
                with self.subTest(response=response), mock.patch.object(release, "ROOT", root), \
                        mock.patch.object(release, "run", side_effect=side_effect) as run, \
                        mock.patch.object(release, "upload_asset") as upload, \
                        self.assertRaises((ValueError, release.subprocess.CalledProcessError)):
                    release.create_draft(payload, REQUEST, journal())
                upload.assert_not_called()
                self.assertEqual(run.call_count, 1)
                # The retry sees the request without an ID and refuses to create another draft.
                recorded = release.read(root / release.JOURNAL)
                self.assertIs(recorded["draft_requested"], True)
                self.assertIsNone(recorded["release_id"])

    def test_created_id_is_journaled_before_any_upload_and_partial_upload_stops(self):
        created = {"id": 42, "tag_name": TAG, "draft": True, "prerelease": False}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = root / "payload"
            payload.mkdir()
            (payload / "release-notes.md").write_text("notes", encoding="utf-8")
            (payload / "package.tgz").write_bytes(b"archive")
            seen = []

            def upload(identifier, path):
                seen.append(release.read(root / release.JOURNAL)["release_id"])
                if len(seen) == 2:
                    raise OSError("interrupted")
            with mock.patch.object(release, "ROOT", root), \
                    mock.patch.object(release, "run", return_value=json.dumps(created)) as run, \
                    mock.patch.object(release, "upload_asset", side_effect=upload), self.assertRaises(OSError):
                release.create_draft(payload, REQUEST, journal())
            self.assertEqual(run.call_count, 1)
            self.assertEqual(seen, [42, 42])
            self.assertEqual(release.read(root / release.JOURNAL),
                             journal(draft_requested=True, release_id=42))

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
