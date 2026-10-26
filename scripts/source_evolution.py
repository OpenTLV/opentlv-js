# SPDX-License-Identifier: MIT
# Copyright (c) 2026 OpenTLV
"""Account for reviewed post-migration additions without rewriting the baseline."""

import hashlib
import json
from pathlib import Path
import re


def load(root):
    path = root / "ci/source-evolution.json"
    if not path.exists():
        return {"changed": {}, "added": {}, "bridge_additions": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or not data.get("reason"):
        raise ValueError("Invalid source evolution record")
    for category in ("changed", "added"):
        for name, entry in data[category].items():
            if Path(name).is_absolute() or ".." in Path(name).parts or "\\" in name:
                raise ValueError("Invalid source evolution path")
            if not entry.get("reason") or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
                raise ValueError("Invalid source evolution entry")
    return data


def checked(root, name, entry):
    path = root / name
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        raise ValueError(f"Unrecorded post-migration source differs: {name}")
    return path.read_bytes()


def restore(root, name, evolution):
    entry = evolution["changed"].get(name)
    if entry is None:
        return (root / name).read_bytes()
    data = checked(root, name, entry).decode("utf-8")
    for section in entry.get("sections", []):
        start, end = section["start"], section["end"]
        if data.count(start) != 1 or data.count(end) != 1:
            raise ValueError(f"Unrecognized evolution section: {name}")
        begin = data.index(start)
        finish = data.index(end, begin) + len(end)
        data = data[:begin] + data[finish:]
    for change in entry.get("restore", []):
        if not change["current"] or data.count(change["current"]) != 1:
            raise ValueError(f"Unrecognized evolution replacement: {name}")
        data = data.replace(change["current"], change["baseline"])
    restored = data.encode("utf-8")
    if hashlib.sha256(restored).hexdigest() != entry["baseline_sha256"]:
        raise ValueError(f"Restored migration source differs: {name}")
    return restored
