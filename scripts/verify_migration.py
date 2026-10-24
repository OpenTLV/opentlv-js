# SPDX-License-Identifier: MIT
# Copyright (c) 2026 OpenTLV
"""Verify baseline source parity and the recorded standalone build adaptations."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "a9a6f9470c2b285744738b40196bef9d0341fead"
TRANSFERRED = {
    "bindings/wasm/CMakeLists.txt",
    "bindings/wasm/examples/parse.mjs",
    "bindings/wasm/js/opentlv.mjs",
    "bindings/wasm/js/query.mjs",
    "bindings/wasm/src/opentlv_wasm.c",
    "bindings/wasm/src/opentlv_wasm.h",
    "bindings/wasm/test/smoke.mjs",
    "tests/query/wasm_facade.mjs",
}


def verify(core_source=None):
    inventory = json.loads((ROOT / "migration/source-inventory.json").read_text(encoding="utf-8"))
    if (inventory["schema"] != 1 or inventory["commit"] != BASELINE
            or inventory["repository"] != "https://github.com/OpenTLV/opentlv"):
        raise ValueError("Unexpected migration baseline")
    entries = [entry for entry in inventory["files"]
               if entry["path"].startswith("bindings/wasm/")
               or entry["path"] == "tests/query/wasm_facade.mjs"]
    if len(entries) != len(TRANSFERRED) or {entry["path"] for entry in entries} != TRANSFERRED:
        raise ValueError("Source inventory does not contain the exact eight-file transfer")
    adaptations = json.loads((ROOT / "migration/build-adaptations.json").read_text(encoding="utf-8"))
    if set(adaptations) != {"bindings/wasm/CMakeLists.txt"}:
        raise ValueError("Unexpected standalone build adaptations")
    actual = {path.relative_to(ROOT).as_posix()
              for directory in (ROOT / "bindings/wasm", ROOT / "tests/query")
              for path in directory.rglob("*") if path.is_file()}
    if actual != TRANSFERRED:
        raise ValueError(f"Transfer file set differs: missing={sorted(TRANSFERRED - actual)}, "
                         f"unexpected={sorted(actual - TRANSFERRED)}")

    def git(*args):
        return subprocess.check_output(["git", "-C", str(core_source), *args])

    if core_source is not None:
        tree = git("rev-parse", f"{BASELINE}^{{tree}}").decode().strip()
        if tree != inventory["tree"]:
            raise ValueError("Core baseline tree differs from the inventory")
    for entry in entries:
        name = entry["path"]
        if (entry["owner"] != "opentlv-js" or entry["migration_destination"] != name
                or entry["mode"] != "100644"):
            raise ValueError(f"Unexpected transfer ownership, destination or mode: {name}")
        data = (ROOT / name).read_bytes()
        if name == "bindings/wasm/src/opentlv_wasm.c":
            # Only dependency include paths change; verify all other C bytes.
            for helper in ("query_schema.h", "path_query.h"):
                adapted = f'#include "{helper}"'.encode()
                original = f'#include "../../common/{helper}"'.encode()
                if data.count(adapted) != 1:
                    raise ValueError(f"Unexpected shared helper include: {helper}")
                data = data.replace(adapted, original)
        if name in adaptations:
            adaptation = adaptations[name]
            if (adaptation["baseline_sha256"] != entry["sha256"]
                    or hashlib.sha256(data).hexdigest() != adaptation["adapted_sha256"]):
                raise ValueError(f"Unrecorded build adaptation: {name}")
            if core_source is not None:
                baseline = git("show", f"{BASELINE}:{name}")
                if hashlib.sha256(baseline).hexdigest() != entry["sha256"]:
                    raise ValueError(f"Core baseline differs from the inventory: {name}")
            continue
        blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        if (len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]
                or blob != entry["blob"]):
            raise ValueError(f"Transferred bytes differ from the baseline: {name}")
        if core_source is not None and data != git("show", f"{BASELINE}:{name}"):
            raise ValueError(f"Transferred bytes differ from the Core Git object: {name}")
    header = (ROOT / "bindings/wasm/src/opentlv_wasm.h").read_text(encoding="utf-8")
    declarations = [" ".join(match.split()) for match in re.findall(
        r"^OPENTLV_WASM_API\s+([^;]+);", header, re.M)]
    if declarations != inventory["bridge_declarations"]:
        raise ValueError("Bridge declarations differ from the baseline")
    print(f"Verified {len(entries)} transferred files (including recorded build adaptations) "
          f"and {len(declarations)} bridge declarations "
          f"at Core {BASELINE}")
    if core_source is not None:
        print("Verified against Core baseline Git objects (independent of checkout HEAD)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-source", type=Path,
                        help="optional Core Git checkout containing the recorded baseline")
    args = parser.parse_args()
    try:
        verify(args.core_source)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"Migration verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
