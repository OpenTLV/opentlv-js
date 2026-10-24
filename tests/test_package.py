# SPDX-License-Identifier: MIT
# Copyright (c) 2026 OpenTLV
"""Private package boundaries and malformed/stale artifact regressions."""

import io
import json
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import package


class PackageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        for name in ("package.json", "packaging/index.mjs", "packaging/README.md", "LICENSE", "CHANGELOG.md",
                     "src/opentlv.mjs", "src/query.mjs"):
            target = self.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(package.ROOT / name, target)
        self.dist = self.root / "dist"
        self.dist.mkdir()
        (self.dist / "opentlv-core.js").write_text("export default function createOpenTLV() {}\n")
        (self.dist / "opentlv-core.wasm").write_bytes(b"\0asm\x01\0\0\0")
        for name in ("opentlv.mjs", "query.mjs"):
            shutil.copyfile(self.source / "src" / name, self.dist / name)
        self.selection = dict(mode="pinned-source", release_verified=False, repository="fixture",
                              commit="a" * 40, tree="b" * 40, source_sha256="c" * 64,
                              version_inputs={"tag": "9.8.7"})

    def stage(self, name="stage"):
        return package.stage(self.dist, self.selection, self.root / name, self.source)

    def edit_metadata(self, **changes):
        path = self.source / "package.json"
        data = json.loads(path.read_text())
        data.update(changes)
        path.write_text(json.dumps(data))

    def test_version_is_independent_and_archive_inputs_are_exact(self):
        self.edit_metadata(version="2.3.4-rc.1+build.5")
        hashes = self.stage()
        self.assertEqual(set(hashes), package.FILES)
        staged = self.root / "stage"
        self.assertIn('"2.3.4-rc.1+build.5"', (staged / "version.mjs").read_text())
        info = json.loads((staged / "package-info.json").read_text())
        self.assertEqual(info["core"]["version_inputs"]["tag"], "9.8.7")
        self.assertEqual(info["version"], "2.3.4-rc.1+build.5")
        self.assertFalse(info["release_verified"])
        for name in package.OUTPUTS:
            self.assertEqual((staged / "dist" / name).read_bytes(), (self.dist / name).read_bytes())

    def test_invalid_versions_fail(self):
        for version in ("v1.2.3", "1.2", "01.2.3", "1.2.3-01", "1.2.3\n", "1.2.3-", 123):
            with self.subTest(version=version):
                self.edit_metadata(version=version)
                with self.assertRaisesRegex(ValueError, "SemVer"):
                    package.metadata(self.source)

    def test_publishable_or_inaccurate_metadata_fails(self):
        for change in ({"private": False}, {"name": "@opentlv/js"}, {"exports": {}},
                       {"scripts": {"prepack": "exit 0"}}, {"dependencies": {}},
                       {"types": "missing.d.ts"}, {"files": ["**/*"]}, {"type": "commonjs"},
                       {"engines": {"node": ">=18"}}, {"publishConfig": {}}):
            with self.subTest(change=change):
                shutil.copyfile(package.ROOT / "package.json", self.source / "package.json")
                self.edit_metadata(**change)
                with self.assertRaises(ValueError):
                    package.metadata(self.source)

    def test_local_development_or_release_claim_fails(self):
        self.selection["mode"] = "local-development"
        with self.assertRaisesRegex(ValueError, "pinned-source"):
            self.stage()
        self.selection.update(mode="pinned-source", release_verified=True)
        with self.assertRaisesRegex(ValueError, "non-release"):
            self.stage()

    def test_missing_empty_and_stale_outputs_fail(self):
        for name in package.OUTPUTS:
            path = self.dist / name
            original = path.read_bytes()
            path.unlink()
            with self.assertRaisesRegex(ValueError, "Missing"):
                self.stage()
            path.touch()
            with self.assertRaisesRegex(ValueError, "empty"):
                self.stage()
            path.write_bytes(original)
        (self.dist / "query.mjs").write_bytes(b"// changed")
        with self.assertRaisesRegex(ValueError, "Stale"):
            self.stage()

    def test_wrong_wasm_and_reused_destination_fail(self):
        self.stage()
        with self.assertRaisesRegex(ValueError, "fresh"):
            self.stage()
        (self.dist / "opentlv-core.wasm").write_bytes(b"not WASM")
        with self.assertRaisesRegex(ValueError, "WebAssembly"):
            self.stage("second")

    def test_symlinked_input_fails(self):
        path = self.dist / "opentlv-core.js"
        original = self.root / "original.js"
        path.rename(original)
        try:
            path.symlink_to(original)
        except OSError:
            self.skipTest("Symlinks unavailable")
        with self.assertRaisesRegex(ValueError, "symlinked"):
            self.stage()

    def archive(self, names, changed=False, symlink=False):
        archive = self.root / "test.tgz"
        with tarfile.open(archive, "w:gz") as bundle:
            for name in names:
                data = b"changed" if changed else b"fixture"
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                if symlink:
                    entry.type = tarfile.SYMTYPE
                    entry.linkname = "outside"
                    entry.size = 0
                bundle.addfile(entry, io.BytesIO(data))
        return archive

    def test_archive_bytes_paths_duplicates_and_links_are_checked(self):
        expected = {"index.mjs": package.digest(b"fixture")}
        package.verify_archive(self.archive(["package/index.mjs"]), expected)
        for names in ([], ["package/index.mjs", "package/secret"], ["package/../index.mjs"],
                      ["package/index.mjs", "package/index.mjs"]):
            with self.subTest(names=names), self.assertRaisesRegex(ValueError, "file set"):
                package.verify_archive(self.archive(names), expected)
        with self.assertRaisesRegex(ValueError, "content differs"):
            package.verify_archive(self.archive(["package/index.mjs"], changed=True), expected)
        with self.assertRaisesRegex(ValueError, "non-regular"):
            package.verify_archive(self.archive(["package/index.mjs"], symlink=True), expected)

    def test_dry_run_and_real_pack_inventory_must_be_exact(self):
        expected = {"index.mjs": "hash"}
        package.verify_inventory([{"files": [{"path": "index.mjs"}]}], expected)
        for report in ([], [{"files": []}], [{"files": [{"path": "index.mjs"}] * 2}],
                       [{"files": [{"path": "index.mjs"}, {"path": ".npmrc"}]}]):
            with self.assertRaises(ValueError):
                package.verify_inventory(report, expected)


if __name__ == "__main__":
    unittest.main()
