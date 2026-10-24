# SPDX-License-Identifier: MIT
# Copyright (c) 2026 OpenTLV
"""Ensure relocated sources still fail closed against the immutable baseline."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import verify_migration as migration


class MigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in (*migration.TRANSFERRED.values(), "migration/source-inventory.json",
                     "migration/build-adaptations.json"):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(migration.ROOT / name, target)

    def verify(self):
        with patch.object(migration, "ROOT", self.root), redirect_stdout(io.StringIO()):
            migration.verify()

    def test_relocated_sources_match_original_inventory(self):
        self.verify()

    def test_missing_relocated_file_fails(self):
        for name in migration.TRANSFERRED.values():
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_bytes()
                path.unlink()
                with self.assertRaisesRegex(ValueError, "Transfer file set differs"):
                    self.verify()
                path.write_bytes(original)

    def test_changed_source_or_build_definition_fails(self):
        for name in migration.TRANSFERRED.values():
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_bytes()
                path.write_bytes(original + b"\n// unrecorded edit\n")
                with self.assertRaisesRegex(ValueError, "differ|Unrecorded"):
                    self.verify()
                path.write_bytes(original)

    def test_extra_transferred_source_fails(self):
        (self.root / "src/extra.mjs").write_text("export const extra = true;\n")
        with self.assertRaisesRegex(ValueError, "unexpected=.*extra.mjs"):
            self.verify()

    def test_old_source_tree_cannot_coexist(self):
        old = self.root / "bindings/wasm/js"
        old.mkdir(parents=True)
        shutil.copyfile(self.root / "src/opentlv.mjs", old / "opentlv.mjs")
        with self.assertRaisesRegex(ValueError, "Obsolete bindings/wasm"):
            self.verify()

    def test_baseline_destination_cannot_be_rewritten(self):
        path = self.root / "migration/source-inventory.json"
        data = json.loads(path.read_text())
        for entry in data["files"]:
            if entry["path"] == "bindings/wasm/js/opentlv.mjs":
                entry["migration_destination"] = "src/opentlv.mjs"
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "destination"):
            self.verify()

    def test_symlinked_source_fails(self):
        path = self.root / "src/opentlv.mjs"
        original = self.root / "original.mjs"
        path.rename(original)
        try:
            path.symlink_to(original)
        except OSError as error:
            self.skipTest(f"Symlinks unavailable: {error}")
        with self.assertRaisesRegex(ValueError, "Symlinked"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
