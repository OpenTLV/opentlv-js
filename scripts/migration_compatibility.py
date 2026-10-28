# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Check historical byte equality separately from reviewed current API additions."""

import json
from pathlib import Path
import re
import shutil

import core_dependency as core
import verify_migration
import source_evolution

BASELINE_LOCK = "ci/migration-core-source.json"


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


def compare_additions(baseline, current, additions):
    """Keep the old public surface and allow only explicitly reviewed additions.

    Raw binary export/import names and output bytes may change after features
    are added; they remain recorded, and historical equality is checked on the
    reconstructed migration sources separately.
    """
    expected = dict(baseline["runtime"])
    for name in additions:
        if name in expected or not re.fullmatch(r"_opentlv_wasm_\w+", name):
            raise ValueError("Invalid reviewed bridge addition")
        expected[name] = "function"
    if current["runtime"] != expected or current["modules"] != baseline["modules"]:
        raise ValueError("Unreviewed post-migration public contract change")


def baseline_lock(root, inventory):
    """Return the recorded migration Core lock after checking it names the baseline."""
    path = root / BASELINE_LOCK
    lock = core.load_lock(path)
    if lock["commit"] != verify_migration.BASELINE or lock["tree"] != inventory["tree"]:
        raise ValueError("Migration Core lock differs from the immutable baseline")
    return path


def stage_migration_sources(root, destination, evolution):
    """Reconstruct only the verified migration project, never current features."""
    destination.mkdir()
    names = set(verify_migration.TRANSFERRED.values()) | {
        "CMakeLists.txt", "cmake/Core.cmake", "cmake/core-features.json",
        "scripts/core_dependency.py"}
    for name in sorted(names):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source_evolution.restore(root, name, evolution))
    # The current lock may pin a newer Core; the migration keeps its own.
    (destination / "cmake/core-source.json").write_bytes((root / BASELINE_LOCK).read_bytes())


def check(runner, output, build):
    # Import lazily: ci owns the runner and invokes this optional migration gate.
    import ci
    selection = ci.read_selection(build)
    inventory = json.loads((ci.ROOT / "migration/source-inventory.json").read_text(encoding="utf-8"))
    lock = baseline_lock(ci.ROOT, inventory)
    evolution = source_evolution.load(ci.ROOT)
    # Rebuild the completed migration sources against the baseline Core lock;
    # its verified checkout also provides the historical Core WASM target.
    reconstructed = output / "migration-standalone-source"
    stage_migration_sources(ci.ROOT, reconstructed, evolution)
    reconstructed_build = output / "migration-standalone-build"
    runner.run("migration-standalone-configure", "emcmake", "cmake", "-S", reconstructed,
               "-B", reconstructed_build, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
               "-DOPENTLV_WARNINGS_AS_ERRORS=ON", f"-DOPENTLV_NODE_EXECUTABLE={shutil.which('node')}")
    baseline_selection = ci.read_selection(reconstructed_build, lock)
    runner.run("migration-standalone-build", "cmake", "--build", reconstructed_build,
               "--target", "opentlv-wasm", "--parallel", "4")
    runner.run("migration-standalone-ctest", "ctest", "--test-dir", reconstructed_build,
               "-L", "wasm", "--output-on-failure", "--no-tests=error")
    comparison_dist = reconstructed_build / "dist"
    source = Path(baseline_selection["source"])
    verify_migration.verify(source)
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
    for name, dist in (("baseline", historical), ("standalone", comparison_dist), ("current", build / "dist")):
        observed = runner.run(f"migration-{name}-contract", "node",
                              ci.ROOT / "scripts/inspect_wasm.mjs", dist)
        contracts[name] = json.loads(observed)
        (runner.evidence / f"migration-{name}-contract.json").write_text(
            observed + "\n", encoding="utf-8")
    compare_contracts(contracts["baseline"], contracts["standalone"], inventory["bridge_declarations"])
    hashes = ci.compare_outputs(historical, comparison_dist)
    compare_additions(contracts["baseline"], contracts["current"], evolution["bridge_additions"])
    verify_historical_inputs(source, inventory)
    if (ci.read_selection(build) != selection
            or ci.read_selection(reconstructed_build, lock) != baseline_selection):
        raise ValueError("Core selection changed during migration comparison")
    current_is_baseline = not evolution["changed"] and selection["commit"] == verify_migration.BASELINE
    return dict(baseline_commit=verify_migration.BASELINE, current_core_commit=selection["commit"],
                outputs=hashes, contract=contracts["standalone"], current_contract=contracts["current"],
                current_is_migration_baseline=current_is_baseline, status="passed")
