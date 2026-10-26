# SPDX-License-Identifier: MIT
# Copyright (c) 2026 OpenTLV
"""Reject actual binary/namespace drift even when bridge headers still match."""

import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from migration_compatibility import compare_contracts, verify_historical_inputs


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
