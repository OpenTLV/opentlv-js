# SPDX-License-Identifier: MIT
# Copyright (c) 2026 OpenTLV
"""Verify pinned Core source or record an explicit development checkout."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ("CMakeLists.txt", "cmake", "tlv")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def input_hashes(source):
    files = {}
    for name in INPUTS:
        path = source / name
        if not path.exists():
            raise ValueError(f"Missing Core build input: {name}")
        if path.is_symlink():
            raise ValueError(f"Core build inputs must not be symlinks: {path}")
        for item in ([path] if path.is_file() else sorted(path.rglob("*"))):
            if item.is_symlink():
                raise ValueError(f"Core build inputs must not be symlinks: {item}")
            if item.is_file():
                files[item.relative_to(source).as_posix()] = digest(item.read_bytes())
    return files


def source_digest(files):
    return digest(json.dumps(sorted(files.items()), separators=(",", ":")).encode())


def load_lock():
    lock = json.loads((ROOT / "cmake/core-source.json").read_text(encoding="utf-8"))
    if (lock["schema"] != 1 or lock["repository"] != "https://github.com/OpenTLV/opentlv.git"
            or not re.fullmatch(r"[0-9a-f]{40}", lock["commit"])
            or not re.fullmatch(r"[0-9a-f]{40}", lock["tree"])
            or not re.fullmatch(r"[0-9a-f]{64}", lock["source_sha256"])):
        raise ValueError("Invalid pinned Core source lock")
    return lock


def inspect(source, mode, lock):
    source = source.resolve()

    def git(*args):
        return subprocess.check_output(["git", "-C", str(source), *args],
                                       stderr=subprocess.PIPE).decode().strip()

    if not (source / ".git").exists():
        raise ValueError("Core source must be a Git checkout (including worktrees)")
    commit = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    status = git("status", "--porcelain", "--untracked-files=all", "--", *INPUTS)
    files = input_hashes(source)
    checksum = source_digest(files)
    # Core derives its public version from Git, so record/check those inputs too.
    tag = git("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", "--match", "[0-9]*", "HEAD")
    version = dict(tag=tag, tag_commit=git("rev-list", "-n", "1", tag),
                   revision=int(git("rev-list", "--count", f"{tag}..HEAD")),
                   short_commit=git("rev-parse", "--short", "HEAD"),
                   branch=git("rev-parse", "--abbrev-ref", "HEAD"))
    version["tags_at_commit"] = git("tag", "--points-at", version["tag_commit"], "--list",
                                    "v[0-9]*", "[0-9]*", "--sort=-version:refname").splitlines()
    if mode == "pinned-source":
        if commit != lock["commit"] or tree != lock["tree"]:
            raise ValueError("Core commit/tree does not match the source lock")
        if checksum != lock["source_sha256"] or status:
            raise ValueError("Core source checksum/working tree does not match the source lock")
        if version != lock["version_inputs"]:
            raise ValueError("Core Git version inputs do not match the source lock")
    elif mode != "local-development":
        raise ValueError(f"Unknown Core selection mode: {mode}")
    return dict(schema=1, mode=mode, repository=lock["repository"],
                pinned_commit=lock["commit"], source=str(source), commit=commit, tree=tree,
                source_sha256=checksum, input_count=len(files), dirty=bool(status),
                version_inputs=version, release_verified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("pinned-source", "local-development"))
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path)
    action.add_argument("--check", type=Path)
    args = parser.parse_args()
    try:
        lock = load_lock()
        receipt = inspect(args.source, args.mode, lock)
        if args.check:
            if receipt != json.loads(args.check.read_text(encoding="utf-8")):
                raise ValueError("Core inputs changed after configuration; reconfigure before building")
        else:
            args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(f"Core {receipt['mode']}: {receipt['commit']}, "
              f"SHA-256 {receipt['source_sha256']}, dirty={receipt['dirty']}")
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f"Core verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
