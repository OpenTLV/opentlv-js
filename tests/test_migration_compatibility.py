# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Reject actual binary/namespace drift even when bridge headers still match."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from migration_compatibility import compare_contracts, compare_additions, verify_historical_inputs
from migration_compatibility import BASELINE_LOCK, baseline_lock, stage_migration_sources
import source_evolution


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.declarations = ["void opentlv_wasm_free(void*)"]
        self.contract = {"modules": {"opentlv.mjs": {"loadOpenTLV": "function"}},
                         "exports": [{"name": "opentlv_wasm_free", "kind": "function"}],
                         "runtime": {"_opentlv_wasm_free": "function"},
                         "imports": [{"module": "env", "name": "resize", "kind": "function"}]}

    def test_equal_actual_contracts(self):
        compare_contracts(self.contract, copy.deepcopy(self.contract), self.declarations)

    def test_missing_extra_or_changed_boundary_fails(self):
        for field in ("modules", "exports", "imports", "runtime"):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.contract)
                changed[field] = {} if field in ("modules", "runtime") else []
                with self.assertRaisesRegex(ValueError, "contract differs"):
                    compare_contracts(self.contract, changed, self.declarations)
        extra = copy.deepcopy(self.contract)
        extra["exports"].append({"name": "opentlv_wasm_extra", "kind": "function"})
        with self.assertRaisesRegex(ValueError, "contract differs"):
            compare_contracts(self.contract, extra, self.declarations)

    def test_matching_binaries_cannot_hide_missing_or_extra_bridge_functions(self):
        for runtime in ({}, dict(self.contract["runtime"], _opentlv_wasm_extra="function"),
                        {"_opentlv_wasm_free": "number"}):
            with self.subTest(runtime=runtime):
                changed = dict(self.contract, runtime=runtime)
                with self.assertRaisesRegex(ValueError, "recorded bridge"):
                    compare_contracts(changed, changed, self.declarations)

    def test_post_migration_additions_are_explicit_and_do_not_hide_removals(self):
        current = copy.deepcopy(self.contract)
        current["runtime"]["_opentlv_wasm_fields"] = "function"
        compare_additions(self.contract, current, ["_opentlv_wasm_fields"])
        with self.assertRaisesRegex(ValueError, "Unreviewed"):
            compare_additions(self.contract, current, [])
        current["runtime"].pop("_opentlv_wasm_free")
        with self.assertRaisesRegex(ValueError, "Unreviewed"):
            compare_additions(self.contract, current, ["_opentlv_wasm_fields"])


class HistoricalInputsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.name = "bindings/wasm/CMakeLists.txt"
        self.path = self.root / self.name
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"baseline")
        self.inventory = {"files": [{"path": self.name,
                                     "sha256": hashlib.sha256(b"baseline").hexdigest()}]}

    def test_staged_project_restores_baseline_and_keeps_required_build_inputs(self):
        root = Path(__file__).resolve().parents[1]
        evolution = source_evolution.load(root)
        target = self.root / "standalone"
        stage_migration_sources(root, target, evolution)
        self.assertTrue(json.loads((target / "cmake/core-features.json").read_text()))
        self.assertEqual((target / "scripts/core_dependency.py").read_bytes(),
                         (root / "scripts/core_dependency.py").read_bytes())
        for name, entry in evolution["changed"].items():
            self.assertEqual(hashlib.sha256((target / name).read_bytes()).hexdigest(),
                             entry["baseline_sha256"])
        for name in evolution["added"]:
            self.assertFalse((target / name).exists())
        self.assertEqual((target / "cmake/core-source.json").read_bytes(),
                         (root / BASELINE_LOCK).read_bytes())

    def test_migration_lock_must_name_the_immutable_baseline(self):
        root = Path(__file__).resolve().parents[1]
        inventory = json.loads((root / "migration/source-inventory.json").read_text())
        self.assertEqual(baseline_lock(root, inventory), root / BASELINE_LOCK)
        lock = json.loads((root / BASELINE_LOCK).read_text())
        for key in ("commit", "tree"):
            with self.subTest(key=key):
                (self.root / "ci").mkdir(exist_ok=True)
                (self.root / BASELINE_LOCK).write_text(json.dumps(dict(lock, **{key: "0" * 40})))
                with self.assertRaisesRegex(ValueError, "immutable baseline"):
                    baseline_lock(self.root, inventory)

    def test_exact_inputs_pass(self):
        verify_historical_inputs(self.root, self.inventory)

    def test_modified_build_input_fails(self):
        self.path.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "Modified historical"):
            verify_historical_inputs(self.root, self.inventory)

    def test_missing_or_untracked_input_fails(self):
        self.path.unlink()
        with self.assertRaisesRegex(ValueError, "input set"):
            verify_historical_inputs(self.root, self.inventory)
        self.path.write_bytes(b"baseline")
        (self.path.parent / "injected.cmake").touch()
        with self.assertRaisesRegex(ValueError, "input set"):
            verify_historical_inputs(self.root, self.inventory)

    def test_symlinked_parent_fails(self):
        target = self.root / "target"
        (self.root / "bindings").rename(target)
        try:
            (self.root / "bindings").symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks unavailable")
        with self.assertRaisesRegex(ValueError, "Symlinked historical"):
            verify_historical_inputs(self.root, self.inventory)


if __name__ == "__main__":
    unittest.main()
