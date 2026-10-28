# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Run the JS-owned WASM checks against an independent, pinned Core checkout."""

import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import core_dependency as core
import migration_compatibility

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ("opentlv-core.js", "opentlv-core.wasm", "opentlv.mjs", "query.mjs")
TIERS = ("pr", "main", "full", "release")


def configurations(tier):
    if tier not in TIERS:
        raise ValueError(f"Unknown CI tier: {tier}")
    return ("Release", "Debug") if tier == "full" else ("Release",)


def output_hashes(dist):
    result = {}
    for name in OUTPUTS:
        path = dist / name
        if path.is_symlink() or not path.is_file() or not path.stat().st_size:
            raise ValueError(f"Missing, empty or symlinked WASM output: {path}")
        result[name] = core.digest(path.read_bytes())
    return result


def compare_outputs(first, second):
    if first.resolve() == second.resolve():
        raise ValueError("Reproducibility requires independent build directories")
    left, right = output_hashes(first), output_hashes(second)
    if left != right:
        changed = [name for name in OUTPUTS if left[name] != right[name]]
        raise ValueError(f"WASM outputs are not reproducible: {', '.join(changed)}")
    return left


def verify_query_inputs(source, commit):
    """Check Core-owned integration scripts/corpus against immutable Git blobs.

    These files are outside the native build checksum. Verify the entire Query
    directory before executing its Python helpers; never copy it into JS.
    """
    directory = source / "tests/query"
    entries = subprocess.check_output(
        ["git", "-C", str(source), "ls-tree", "-r", "-z", commit, "--", "tests/query"]
    ).decode().split("\0")
    expected = {}
    for entry in filter(None, entries):
        metadata, name = entry.split("\t", 1)
        mode, kind, blob = metadata.split()
        if kind != "blob" or mode not in ("100644", "100755"):
            raise ValueError(f"Unsupported Core Query input: {name}")
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing or symlinked Core Query input: {name}")
        original = subprocess.check_output(["git", "-C", str(source), "cat-file", "blob", blob])
        expected[name] = core.digest(original)
        if core.digest(path.read_bytes()) != expected[name]:
            raise ValueError(f"Modified Core Query input: {name}")
    if not expected or directory.is_symlink():
        raise ValueError("Missing or symlinked Core Query directory")
    actual = set()
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Symlinked Core Query input: {path}")
        if path.is_file():
            actual.add(path.relative_to(source).as_posix())
    if actual != set(expected):
        raise ValueError("Unexpected Core Query files (including ignored/untracked inputs)")
    return dict(commit=commit, input_count=len(expected), source_sha256=core.source_digest(expected))


def read_selection(build, lock=core.LOCK):
    receipt = json.loads((build / "core-selection.json").read_text(encoding="utf-8"))
    if receipt["mode"] != "pinned-source":
        raise ValueError("CI requires pinned-source Core, not a local development override")
    current = core.inspect(Path(receipt["source"]), "pinned-source", core.load_lock(lock))
    if current != receipt:
        raise ValueError("Core selection changed after configuration")
    return receipt


class Runner:
    def __init__(self, evidence):
        self.evidence = evidence
        self.commands = []
        self.env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        # The upstream ABI checker uses assertions; optimization must not disable it.
        self.env.pop("PYTHONOPTIMIZE", None)

    def run(self, name, *command, separate_stderr=False):
        command = [str(value) for value in command]
        print(f"[{name}] {' '.join(command)}", flush=True)
        log = self.evidence / f"{name}.log"
        error_log = self.evidence / f"{name}.stderr.log"
        with ExitStack() as stack:
            stream = stack.enter_context(log.open("wb"))
            errors = stack.enter_context(error_log.open("wb")) if separate_stderr else subprocess.STDOUT
            result = subprocess.run(command, cwd=ROOT, env=self.env,
                                    stdout=stream, stderr=errors, check=False)
        self.commands.append(dict(name=name, command=command, exit_code=result.returncode))
        if result.returncode:
            print(log.read_text(encoding="utf-8", errors="replace"), flush=True)
            if separate_stderr:
                print(error_log.read_text(encoding="utf-8", errors="replace"), flush=True)
            raise RuntimeError(f"{name} failed ({result.returncode}); see {log}")
        return log.read_text(encoding="utf-8").strip()


def build_and_check(runner, output, configuration, name):
    build = output / name
    if build.exists():
        raise ValueError(f"CI requires a fresh build directory: {build}")
    runner.run(f"{name}-configure", "emcmake", "cmake", "-S", ROOT, "-B", build,
               "-G", "Ninja", f"-DCMAKE_BUILD_TYPE={configuration}",
               f"-DOPENTLV_NODE_EXECUTABLE={shutil.which('node')}",
               "-DOPENTLV_BUILD_WASM_TESTS=ON", "-DOPENTLV_WARNINGS_AS_ERRORS=ON")
    selection = read_selection(build)
    runner.run(f"{name}-build", "cmake", "--build", build, "--target", "opentlv-wasm", "--parallel", "4")
    runner.run(f"{name}-ctest", "ctest", "--test-dir", build, "-L", "wasm",
               "--output-on-failure", "--no-tests=error")
    source = Path(selection["source"])
    query = verify_query_inputs(source, selection["commit"])
    fixture = runner.evidence / f"{name}-query-fixtures.json"
    runner.run(f"{name}-fixtures", sys.executable, "-B", source / "tests/query/facade_fixtures.py",
               "--output", fixture)
    dist = build / "dist"
    runner.run(f"{name}-facade", "node", ROOT / "tests/query/wasm_facade.mjs", dist, fixture)
    abi = build / "query-abi.js"
    runner.run(f"{name}-abi-build", "emcc", "-std=c99", "-DTLV_STATIC_DEFINE",
               "-I", source / "tlv/include", "-I", build / "core/generated/include",
               source / "tests/query/abi.c", "-o", abi)
    # This probe uses Emscripten's CommonJS default, while package.json marks
    # the source tree as ESM. Make the probe format explicit in either location.
    commonjs_abi = abi.with_suffix(".cjs")
    abi.rename(commonjs_abi)
    observed = runner.run(f"{name}-abi-observe", "node", commonjs_abi)
    abi_json = runner.evidence / f"{name}-query-abi.json"
    abi_json.write_text(observed + "\n", encoding="utf-8")
    runner.run(f"{name}-abi-check", sys.executable, "-B", source / "tests/query/check_abi.py",
               "--input", abi_json)
    # Catch changes during the checks as well as before them.
    if read_selection(build) != selection or verify_query_inputs(source, selection["commit"]) != query:
        raise ValueError("Core inputs changed during JS integration checks")
    package_output = output / f"{name}-package"
    try:
        runner.run(f"{name}-package", sys.executable, "-B", ROOT / "scripts/package.py",
                   "--build", build, "--output", package_output)
    finally:
        if (package_output / "result.json").is_file():
            shutil.copyfile(package_output / "result.json", runner.evidence / f"{name}-package.json")
    package_result = json.loads((package_output / "result.json").read_text(encoding="utf-8"))
    installed_dist = package_output / "consumer/node_modules/opentlv-js/dist"
    runner.run(f"{name}-package-facade", "node", ROOT / "tests/query/wasm_facade.mjs", installed_dist, fixture)
    return dict(core=selection, query_inputs=query, outputs=output_hashes(dist),
                package={key: package_result[key] for key in ("version", "archive_sha256", "files")})


def execute(tier, configuration, output):
    if configuration not in configurations(tier):
        raise ValueError(f"Unsupported {tier} configuration: {configuration}")
    if output.exists():
        raise ValueError(f"Use a fresh evidence/build directory: {output}")
    evidence = output / "evidence"
    evidence.mkdir(parents=True)
    runner = Runner(evidence)
    report = dict(schema=1, tier=tier, configuration=configuration, status="failed",
                  hosted=os.environ.get("GITHUB_ACTIONS") == "true",
                  repository=os.environ.get("GITHUB_REPOSITORY"),
                  sha=os.environ.get("GITHUB_SHA"), ref=os.environ.get("GITHUB_REF"),
                  run_id=os.environ.get("GITHUB_RUN_ID"), run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"),
                  reproducibility_verified=False, release_verified=False, builds={})
    try:
        report["checkout_commit"] = runner.run("checkout-commit", "git", "rev-parse", "HEAD")
        report["checkout_dirty"] = bool(runner.run("checkout-status", "git", "status", "--porcelain"))
        report["toolchain"] = {name: runner.run(f"version-{name}", name, "--version")
                               for name in ("emcc", "node", "cmake", "ninja")}
        if not report["toolchain"]["node"].startswith("v22."):
            raise ValueError("CI requires Node 22")
        report["builds"]["first"] = build_and_check(runner, output, configuration, "first")
        if tier == "release":
            report["builds"]["second"] = build_and_check(runner, output, configuration, "second")
            first, second = (output / name / "dist" for name in ("first", "second"))
            report["reproducible_outputs"] = compare_outputs(first, second)
            if report["builds"]["first"]["package"] != report["builds"]["second"]["package"]:
                raise ValueError("Private package archives are not reproducible")
            report["reproducibility_verified"] = True
        if tier in ("full", "release") and configuration == "Release":
            report["migration_compatibility"] = migration_compatibility.check(
                runner, output, output / "first")
        report["status"] = "passed"
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        report["commands"] = runner.commands
        (evidence / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=TIERS, required=True)
    parser.add_argument("--configuration", choices=("Release", "Debug"), default="Release")
    parser.add_argument("--output", type=Path, help="Fresh build/evidence root (default: build/ci/TIER/CONFIGURATION)")
    args = parser.parse_args()
    output = (args.output or ROOT / "build/ci" / args.tier / args.configuration).resolve()
    try:
        execute(args.tier, args.configuration, output)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"JS CI failed: {error}", file=sys.stderr)
        return 1
    print(f"JS {args.tier} / {args.configuration} passed; evidence: {output / 'evidence'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
