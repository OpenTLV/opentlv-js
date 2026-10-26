# SPDX-License-Identifier: MIT
# Copyright (c) 2026 OpenTLV
"""Rebuild the immutable Core WASM baseline and compare standalone Release outputs."""

import json
from pathlib import Path
import re
import shutil

import core_dependency as core
import verify_migration


def compare_contracts(baseline, standalone, declarations):
    """Compare actual binary exports/imports and JS namespace names/types."""
    if baseline != standalone:
        raise ValueError("Built WASM/JS contract differs from the Core baseline")
    expected = {re.search(r"(opentlv_wasm_\w+)\(", item).group(1)
                for item in declarations}
    # Release minifies binary export names; Emscripten's initialized module
    # provides the public bridge names mapped to those actual WASM functions.
    exported = {name[1:] for name, kind in standalone["runtime"].items()
                if kind == "function" and name.startswith("_opentlv_wasm_")}
    if exported != expected:
        raise ValueError("Built WASM exports differ from the recorded bridge declarations")


def verify_historical_inputs(source, inventory):
    expected = {entry["path"]: entry["sha256"] for entry in inventory["files"]
                if entry["path"].startswith(("bindings/wasm/", "bindings/common/"))}
    paths = [source / "bindings"]
    for name in ("bindings/wasm", "bindings/common"):
        directory = source / name
        paths.extend([directory, *directory.rglob("*")])
    if any(path.is_symlink() for path in paths):
        raise ValueError("Symlinked historical WASM input")
    actual = {path.relative_to(source).as_posix() for path in paths if path.is_file()}
    if not expected or actual != set(expected):
        raise ValueError("Historical WASM input set differs from the baseline")
    for name, checksum in expected.items():
        if core.digest((source / name).read_bytes()) != checksum:
            raise ValueError(f"Modified historical WASM input: {name}")


def check(runner, output, build):
    # Import lazily: ci owns the runner and invokes this optional migration gate.
    import ci
    selection = ci.read_selection(build)
    if selection["commit"] != verify_migration.BASELINE:
        raise ValueError("Migration comparison requires the immutable Core baseline pin")
    source = Path(selection["source"])
    verify_migration.verify(source)
    inventory = json.loads((ci.ROOT / "migration/source-inventory.json").read_text(encoding="utf-8"))
    # The native lock excludes the old bridge. Verify every baseline-owned input
    # before evaluating its CMake or executing its JS files.
    verify_historical_inputs(source, inventory)
    baseline = output / "migration-baseline"
    if baseline.exists():
        raise ValueError("Migration comparison requires a fresh baseline build")
    runner.run("migration-configure", "emcmake", "cmake", "-S", source, "-B", baseline,
               *inventory["cmake_flags"], "-DOPENTLV_BUILD_WASM_TESTS=ON",
               f"-DOPENTLV_NODE_EXECUTABLE={shutil.which('node')}")
    runner.run("migration-build", "cmake", "--build", baseline,
               "--target", "opentlv-wasm", "--parallel", "4")
    runner.run("migration-ctest", "ctest", "--test-dir", baseline, "-L", "wasm",
               "--output-on-failure", "--no-tests=error")
    historical = baseline / "bindings/wasm/dist"
    contracts = {}
    for name, dist in (("baseline", historical), ("standalone", build / "dist")):
        observed = runner.run(f"migration-{name}-contract", "node",
                              ci.ROOT / "scripts/inspect_wasm.mjs", dist)
        contracts[name] = json.loads(observed)
        (runner.evidence / f"migration-{name}-contract.json").write_text(
            observed + "\n", encoding="utf-8")
    compare_contracts(contracts["baseline"], contracts["standalone"], inventory["bridge_declarations"])
    hashes = ci.compare_outputs(historical, build / "dist")
    verify_historical_inputs(source, inventory)
    if ci.read_selection(build) != selection:
        raise ValueError("Core selection changed during migration comparison")
    return dict(baseline_commit=verify_migration.BASELINE, outputs=hashes,
                contract=contracts["standalone"], status="passed")
