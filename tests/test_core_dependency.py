# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Dependency identity/checksum regressions using isolated Git fixtures."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import core_dependency as core


class CoreSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name)
        self.git("init", "-q")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "core.abbrev", "9")
        for name in ("CMakeLists.txt", "cmake/version.cmake", "tlv/core.c"):
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("// fixture\n", encoding="utf-8")
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-qm", "fixture")
        self.git("tag", "0.7.1")
        self.git("checkout", "--detach", "-q")
        self.lock = dict(repository="https://github.com/OpenTLV/opentlv.git",
                         commit=self.git("rev-parse", "HEAD"), tree=self.git("rev-parse", "HEAD^{tree}"))
        receipt = core.inspect(self.source, "local-development", self.lock)
        self.lock.update(source_sha256=receipt["source_sha256"], version_inputs=receipt["version_inputs"])

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.source), *args],
                                       stderr=subprocess.PIPE).decode().strip()

    def inspect(self, mode="pinned-source"):
        return core.inspect(self.source, mode, self.lock)

    def test_clean_pinned_source(self):
        receipt = self.inspect()
        self.assertEqual(receipt["commit"], self.lock["commit"])
        self.assertEqual(receipt["input_count"], 3)
        self.assertFalse((self.source / "bindings").exists())
        self.assertFalse(receipt["dirty"])
        self.assertFalse(receipt["release_verified"])

    def test_wrong_commit_tree_checksum_or_version(self):
        original = copy.deepcopy(self.lock)
        for key in ("commit", "tree", "source_sha256", "version_inputs"):
            with self.subTest(key=key):
                self.lock = copy.deepcopy(original)
                self.lock[key] = {} if key == "version_inputs" else "0" * len(original[key])
                with self.assertRaises(ValueError):
                    self.inspect()

    def test_modified_source_rejected(self):
        (self.source / "tlv/core.c").write_text("// changed\n")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.inspect()

    def test_untracked_build_input_rejected_even_if_ignored(self):
        (self.source / ".git/info/exclude").write_text("injected.c\n")
        (self.source / "tlv/injected.c").write_text("// injected\n")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.inspect()

    def test_missing_input_rejected(self):
        (self.source / "CMakeLists.txt").unlink()
        with self.assertRaisesRegex(ValueError, "Missing Core build input"):
            self.inspect()

    def test_local_override_records_dirty_checksum(self):
        before = self.inspect("local-development")
        (self.source / "tlv/core.c").write_text("// local edit\n")
        after = self.inspect("local-development")
        self.assertEqual(after["mode"], "local-development")
        self.assertTrue(after["dirty"])
        self.assertNotEqual(before["source_sha256"], after["source_sha256"])
        self.assertFalse(after["release_verified"])

    def test_new_semantic_tag_rejected(self):
        self.git("tag", "0.8.0")
        with self.assertRaisesRegex(ValueError, "version inputs"):
            self.inspect()

    def test_non_checkout_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "Git checkout"):
                core.inspect(Path(directory), "local-development", self.lock)

    def test_unknown_mode_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown Core selection mode"):
            self.inspect("binary")

    def test_worktree_supported(self):
        destination = self.source / "worktree"
        self.git("worktree", "add", "--detach", "-q", str(destination))
        self.assertEqual(core.inspect(destination, "pinned-source", self.lock)["commit"], self.lock["commit"])

    def test_symlink_rejected(self):
        link = self.source / "tlv/link.c"
        try:
            link.symlink_to(self.source / "tlv/core.c")
        except OSError:
            self.skipTest("Symlink creation unavailable")
        with self.assertRaisesRegex(ValueError, "symlinks"):
            self.inspect()


class SourceLockTests(unittest.TestCase):
    def test_migration_lock_checksum_matches_recorded_baseline_inputs(self):
        inventory = json.loads((core.ROOT / "migration/source-inventory.json").read_text())
        files = {entry["path"]: entry["sha256"] for entry in inventory["files"]
                 if any(entry["path"] == prefix or entry["path"].startswith(prefix + "/")
                        for prefix in core.INPUTS)}
        lock = core.load_lock(core.ROOT / "ci/migration-core-source.json")
        self.assertEqual(lock["commit"], inventory["commit"])
        self.assertEqual(lock["tree"], inventory["tree"])
        self.assertEqual(core.source_digest(files), lock["source_sha256"])

    def test_current_lock_pins_the_core_release_commit(self):
        lock = core.load_lock()
        self.assertEqual(lock["commit"], "345c77acb29266036df5f27d04ce315bb61853cc")
        self.assertEqual(lock["version_inputs"], {
            "tag": "v0.8.0", "tag_commit": lock["commit"], "revision": 0,
            "short_commit": lock["commit"][:9], "branch": "HEAD", "tags_at_commit": ["v0.8.0"]})


if __name__ == "__main__":
    unittest.main()
