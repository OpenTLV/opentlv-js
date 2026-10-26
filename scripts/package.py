# SPDX-License-Identifier: MIT
# Copyright (c) 2026 OpenTLV
"""Stage and check a private local npm archive; never publish or create a release."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ("opentlv-core.js", "opentlv-core.wasm", "opentlv.mjs", "query.mjs")
EXPORTS = {
    ".": {"types": "./index.d.mts", "import": "./index.mjs"},
    "./opentlv.mjs": {"types": "./dist/opentlv.d.mts", "import": "./dist/opentlv.mjs"},
    "./query.mjs": {"types": "./dist/query.d.mts", "import": "./dist/query.mjs"},
    "./opentlv-core.js": {"import": "./dist/opentlv-core.js"},
    "./opentlv-core.wasm": "./dist/opentlv-core.wasm",
    "./version": {"types": "./version.d.mts", "import": "./version.mjs"},
    "./package.json": "./package.json",
}
DECLARATIONS = ("index.d.mts", "version.d.mts", "dist/opentlv.d.mts", "dist/query.d.mts")
FILES = {*DECLARATIONS, "package.json", "index.mjs", "version.mjs", "package-info.json",
         "README.md", "CHANGELOG.md", "LICENSE", *(f"dist/{name}" for name in OUTPUTS)}
# SemVer numeric prerelease identifiers must not have leading zeroes.
NUMBER = r"(?:0|[1-9][0-9]*)"
IDENTIFIER = rf"(?:{NUMBER}|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
SEMVER = re.compile(rf"{NUMBER}\.{NUMBER}\.{NUMBER}(?:-{IDENTIFIER}(?:\.{IDENTIFIER})*)?"
                    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_file(path):
    if path.is_symlink() or not path.is_file() or not path.stat().st_size:
        raise ValueError(f"Missing, empty or symlinked package input: {path}")
    return path.read_bytes()


def metadata(root=ROOT):
    data = json.loads(read_file(root / "package.json"))
    if not isinstance(data.get("version"), str) or not SEMVER.fullmatch(data["version"]):
        raise ValueError("Package version must be independent SemVer")
    if data.get("name") != "opentlv-js" or data.get("private") is not True:
        raise ValueError("The local package must remain private and named opentlv-js")
    if data.get("type") != "module" or data.get("main") != "./index.mjs" or data.get("exports") != EXPORTS:
        raise ValueError("Package ESM exports do not match the existing artifacts")
    if (set(data.get("files", [])) != FILES - {"package.json"}
            or len(data["files"]) != len(FILES) - 1):
        raise ValueError("Package file allowlist differs from the distribution contract")
    if data.get("license") != "MIT" or data.get("engines") != {"node": "22.x"}:
        raise ValueError("Package license or tested Node version differs")
    if data.get("types") != "./index.d.mts":
        raise ValueError("Package type entry differs")
    forbidden = {"scripts", "dependencies", "devDependencies", "optionalDependencies",
                 "peerDependencies", "bundledDependencies", "bundleDependencies",
                 "publishConfig", "workspaces", "typings", "bin"}
    if forbidden.intersection(data):
        raise ValueError("Package must not introduce hooks, dependencies, publication or unsupported APIs")
    return data


def stage(dist, selection, destination, root=ROOT):
    data = metadata(root)
    if destination.exists():
        raise ValueError(f"Use a fresh package directory: {destination}")
    if selection.get("mode") != "pinned-source" or selection.get("release_verified") is not False:
        raise ValueError("Packaging requires pinned-source, non-release Core evidence")
    outputs = {name: read_file(dist / name) for name in OUTPUTS}
    if not outputs["opentlv-core.wasm"].startswith(b"\0asm\x01\0\0\0"):
        raise ValueError("Expected a WebAssembly v1 binary")
    for name in ("opentlv.mjs", "query.mjs"):
        if outputs[name] != read_file(root / "src" / name):
            raise ValueError(f"Stale or modified JS wrapper: {name}")
    payload = {f"dist/{name}": content for name, content in outputs.items()}
    payload["package.json"] = (json.dumps(data, indent=2) + "\n").encode()
    payload["index.mjs"] = read_file(root / "packaging/index.mjs")
    payload["version.mjs"] = (
        "// Generated from package.json; this is the JS binding version, not Core.\n"
        f"export const packageVersion = {json.dumps(data['version'])};\n").encode()
    for name in ("README.md", "CHANGELOG.md", "LICENSE"):
        source = root / "packaging/README.md" if name == "README.md" else root / name
        payload[name] = read_file(source)
    for name in DECLARATIONS:
        source = root / "src" / Path(name).name if name.startswith("dist/") else root / "packaging" / name
        payload[name] = read_file(source)
        if name.startswith("dist/") and read_file(dist / Path(name).name) != payload[name]:
            raise ValueError(f"Stale or modified type declaration: {name}")
    info = dict(schema=1, name=data["name"], version=data["version"], release_verified=False,
                core={key: selection[key] for key in
                      ("repository", "commit", "tree", "source_sha256", "version_inputs")},
                outputs={name: digest(content) for name, content in outputs.items()})
    payload["package-info.json"] = (json.dumps(info, indent=2, sort_keys=True) + "\n").encode()
    destination.mkdir(parents=True)
    for name, content in payload.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return {name: digest(content) for name, content in payload.items()}


def verify_inventory(report, expected):
    if len(report) != 1:
        raise ValueError("npm pack must report exactly one package")
    names = [entry["path"] for entry in report[0]["files"]]
    if len(names) != len(expected) or set(names) != set(expected):
        raise ValueError("npm pack inventory differs from the exact package file set")


def verify_archive(archive, expected):
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        names = [member.name for member in members]
        if len(names) != len(expected) or set(names) != {f"package/{name}" for name in expected}:
            raise ValueError("Archive file set differs (missing, extra, duplicate or unsafe path)")
        for member in members:
            if not member.isfile():
                raise ValueError(f"Archive contains a non-regular file: {member.name}")
            if digest(bundle.extractfile(member).read()) != expected[member.name[len("package/"):]]:
                raise ValueError(f"Archive content differs: {member.name}")


def check(build, output):
    # Reuse the same live pinned-source verification as the CI build runner.
    import ci

    if output.exists():
        raise ValueError(f"Use a fresh package check directory: {output}")
    selection = ci.read_selection(build)
    output.mkdir(parents=True)
    runner = ci.Runner(output)
    runner.env["npm_config_update_notifier"] = "false"
    report = dict(schema=1, status="failed", release_verified=False, published=False)
    try:
        node = runner.run("node-version", "node", "--version")
        if not node.startswith("v22."):
            raise ValueError("Package checks require Node 22")
        npm = shutil.which("npm")
        if npm is None:
            raise ValueError("npm is required for local pack/install checks")
        report["npm_version"] = runner.run("npm-version", npm, "--version")
        staged = output / "stage"
        hashes = stage(build / "dist", selection, staged)
        common = ("--json", "--ignore-scripts", "--offline", "--workspaces=false",
                  "--cache", output / "npm-cache")
        dry = json.loads(runner.run("pack-dry-run", npm, "pack", staged, "--dry-run", *common,
                                    separate_stderr=True))
        verify_inventory(dry, hashes)
        packed = json.loads(runner.run("pack", npm, "pack", staged, "--pack-destination", output, *common,
                                       separate_stderr=True))
        verify_inventory(packed, hashes)
        filename = packed[0]["filename"]
        if Path(filename).name != filename or not filename.endswith(".tgz"):
            raise ValueError("Unexpected npm archive filename")
        archive = output / filename
        verify_archive(archive, hashes)
        consumer = output / "consumer"
        consumer.mkdir()
        (consumer / "package.json").write_text('{"private":true,"type":"module"}\n', encoding="utf-8")
        runner.run("install", npm, "install", "--prefix", consumer, archive, *common,
                   "--no-audit", "--no-fund", "--package-lock=false")
        installed = consumer / "node_modules/opentlv-js"
        for name, expected in hashes.items():
            if digest(read_file(installed / name)) != expected:
                raise ValueError(f"Installed package differs: {name}")
        shutil.copyfile(ROOT / "tests/package_consumer.mjs", consumer / "check.mjs")
        runner.run("consumer", "node", consumer / "check.mjs")
        runner.run("installed-smoke", "node", ROOT / "tests/smoke.mjs", installed / "dist")
        runner.run("installed-example", "node", ROOT / "examples/parse.mjs", installed / "dist")
        runner.run("installed-fields", "node", ROOT / "tests/format_fields.mjs", installed / "dist")
        runner.run("installed-fields-example", "node", ROOT / "examples/fields.mjs", installed / "dist")
        runner.run("installed-streaming", "node", ROOT / "tests/streaming.mjs", installed / "dist")
        runner.run("installed-streaming-example", "node", ROOT / "examples/streaming.mjs", installed / "dist")
        runner.run("installed-document-schema", "node", ROOT / "tests/document_schema.mjs", installed / "dist")
        runner.run("installed-document-schema-example", "node", ROOT / "examples/document_schema.mjs", installed / "dist")
        runner.run("installed-codecs-generator", "node", ROOT / "tests/codecs_generator.mjs", installed / "dist")
        runner.run("installed-generic", "node", ROOT / "tests/generic.mjs", installed / "dist")
        runner.run("installed-codecs-generator-example", "node", ROOT / "examples/codecs_generator.mjs", installed / "dist")
        tsc = shutil.which("tsc")
        if tsc is None:
            raise ValueError("TypeScript 5.9.3 tsc is required for installed-package checks")
        if runner.run("typescript-version", tsc, "--version").strip() != "Version 5.9.3":
            raise ValueError("Installed-package type checks require TypeScript 5.9.3")
        shutil.copyfile(ROOT / "tests/types.mts", consumer / "types.mts")
        for mode, resolution in (("NodeNext", "NodeNext"), ("ESNext", "Bundler")):
            runner.run(f"types-{resolution}", tsc, "--strict", "--noEmit", "--target", "ES2022",
                       "--module", mode, "--moduleResolution", resolution, consumer / "types.mts")
        if ci.read_selection(build) != selection:
            raise ValueError("Core selection changed during package checks")
        report.update(status="passed", version=metadata()["version"], files=hashes,
                      archive=filename, archive_sha256=digest(archive.read_bytes()))
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        report["commands"] = runner.commands
        (output / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True, help="Existing pinned CMake build")
    parser.add_argument("--output", type=Path, required=True, help="Fresh package check directory")
    args = parser.parse_args()
    try:
        result = check(args.build.resolve(), args.output.resolve())
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError, tarfile.TarError) as error:
        print(f"Package checks failed: {error}", file=sys.stderr)
        return 1
    print(f"Private local package {result['version']} passed; no publication performed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
