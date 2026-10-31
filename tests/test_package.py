# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Private package boundaries and malformed/stale artifact regressions."""

import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import package


class PackageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        for name in ("package.json", "packaging/index.mjs", "packaging/README.md", *package.NOTICES, "CHANGELOG.md",
                     "src/opentlv.mjs", "src/query.mjs", "src/opentlv.d.mts", "src/query.d.mts",
                     "packaging/index.d.mts", "packaging/version.d.mts", "packaging/opentlv-core.d.mts"):
            target = self.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(package.ROOT / name, target)
        self.dist = self.root / "dist"
        self.dist.mkdir()
        (self.dist / "opentlv-core.js").write_text("export default function createOpenTLV() {}\n")
        (self.dist / "opentlv-core.wasm").write_bytes(b"\0asm\x01\0\0\0")
        for name in ("opentlv.mjs", "query.mjs", "opentlv.d.mts", "query.d.mts"):
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

    def test_license_notices_survive_staging_and_archive_checks(self):
        hashes = self.stage()
        staged = self.root / "stage"
        self.assertEqual(json.loads((staged / "package.json").read_text())["license"], "MIT")
        for name in package.NOTICES:
            self.assertEqual((staged / name).read_bytes(), (self.source / name).read_bytes())
        # REUSE-IgnoreStart
        self.assertIn("SPDX-License-Identifier: MIT", (staged / "version.mjs").read_text())
        # REUSE-IgnoreEnd
        archive = self.root / "notices.tgz"
        with tarfile.open(archive, "w:gz") as bundle:
            for name in hashes:
                bundle.add(staged / name, arcname=f"package/{name}")
        package.verify_archive(archive, hashes)
        for name in package.NOTICES:
            with self.subTest(name=name):
                with tarfile.open(archive, "w:gz") as bundle:
                    for other in hashes:
                        if other != name:
                            bundle.add(staged / other, arcname=f"package/{other}")
                with self.assertRaisesRegex(ValueError, "file set"):
                    package.verify_archive(archive, hashes)

    def test_missing_empty_or_symlinked_notices_fail_before_staging(self):
        for name in package.NOTICES:
            path = self.source / name
            original = path.read_bytes()
            with self.subTest(name=name):
                path.unlink()
                with self.assertRaisesRegex(ValueError, "Missing"):
                    self.stage()
                path.touch()
                with self.assertRaisesRegex(ValueError, "empty"):
                    self.stage()
                path.unlink()
                try:
                    path.symlink_to(self.source / "CHANGELOG.md")
                except OSError:
                    pass  # Windows can prohibit symlinks; missing/empty still run.
                else:
                    with self.assertRaisesRegex(ValueError, "symlinked"):
                        self.stage()
                    path.unlink()
                path.write_bytes(original)

    def test_stale_declarations_fail(self):
        (self.dist / "query.d.mts").write_text("export {};\n")
        with self.assertRaisesRegex(ValueError, "Stale or modified type declaration"):
            self.stage()

    def test_package_identity_is_the_selected_private_scoped_name(self):
        data = package.metadata(self.source)
        self.assertEqual(data["name"], "@opentlv/opentlv")
        self.assertIs(data["private"], True)
        self.assertEqual(package.ARCHIVE_PREFIX, "opentlv-opentlv")
        self.stage()
        info = json.loads((self.root / "stage/package-info.json").read_text())
        self.assertEqual(info["name"], "@opentlv/opentlv")

    def test_every_javascript_export_declares_types_and_every_declaration_is_exported(self):
        data = package.metadata(self.source)
        declared = set()
        for name, target in data["exports"].items():
            if isinstance(target, dict):
                with self.subTest(name=name):
                    self.assertEqual(next(iter(target)), "types")
                    declared.add(target["types"])
        self.assertEqual(declared, {f"./{name}" for name in package.DECLARATIONS})
        self.stage()
        self.assertIn("createOpenTLV", (self.root / "stage/opentlv-core.d.mts").read_text())

    def test_repository_url_needs_no_npm_correction(self):
        self.assertEqual(package.metadata(self.source)["repository"]["url"],
                         "git+https://github.com/OpenTLV/opentlv-js.git")
        self.edit_metadata(repository={"type": "git", "url": "https://github.com/OpenTLV/opentlv-js.git"})
        with self.assertRaisesRegex(ValueError, "repository"):
            package.metadata(self.source)

    def test_clean_consumer_environment_drops_inherited_node_and_npm_settings(self):
        clean = package.clean_environment({"PATH": "/bin", "NODE_PATH": "/leak", "NODE_OPTIONS": "--require=/leak",
                                           "npm_config_registry": "http://leak", "NPM_TOKEN": "leak",
                                           "HOME": "/leak"}, "/clean")
        self.assertEqual(clean, {"PATH": "/bin", "HOME": "/clean", "npm_config_update_notifier": "false"})

    def test_browser_is_explicit_or_found_on_path(self):
        with patch.dict(os.environ, {"OPENTLV_BROWSER": "/custom/chrome"}):
            self.assertEqual(package.find_browser(), "/custom/chrome")
        with patch.dict(os.environ):
            os.environ.pop("OPENTLV_BROWSER", None)
            with patch.object(package.shutil, "which", side_effect=lambda name: f"/bin/{name}" if name == "chromium" else None):
                self.assertEqual(package.find_browser(), "/bin/chromium")
            with patch.object(package.shutil, "which", return_value=None):
                self.assertIsNone(package.find_browser())

    def test_no_workflow_or_script_can_publish_to_npm(self):
        # Registry publication needs the separately approved change in #39.
        forbidden = re.compile(r"npm\W+publish|NODE_AUTH_TOKEN|NPM_TOKEN|registry\.npmjs\.org", re.IGNORECASE)
        paths = [*(package.ROOT / ".github/workflows").glob("*.yml"), *(package.ROOT / "scripts").glob("*.py")]
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(path=path.name):
                self.assertIsNone(forbidden.search(path.read_text(encoding="utf-8")))

    def test_ci_provides_the_browser_for_package_checks(self):
        workflow = (package.ROOT / ".github/workflows/js-checks.yml").read_text(encoding="utf-8")
        self.assertIn("run: google-chrome --version", workflow)
        self.assertIn("google-chrome", package.BROWSERS)

    def test_publishable_or_inaccurate_metadata_fails(self):
        for change in ({"private": False}, {"name": "opentlv-js"}, {"name": "@opentlv/js"}, {"exports": {}},
                       {"scripts": {"prepack": "exit 0"}}, {"dependencies": {}},
                       {"types": "missing.d.ts"}, {"files": ["**/*"]}, {"type": "commonjs"},
                       {"engines": {"node": ">=18"}}, {"publishConfig": {}}, {"license": "UNLICENSED"}):
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
