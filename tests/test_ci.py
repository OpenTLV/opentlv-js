# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Regression tests for provenance and fail-closed CI checks, not Core behavior."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ci


class ReproducibilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.first, self.second = self.root / "first", self.root / "second"
        for dist in (self.first, self.second):
            dist.mkdir()
            for name in ci.OUTPUTS:
                (dist / name).write_bytes(name.encode())

    def test_all_four_outputs_match(self):
        self.assertEqual(set(ci.compare_outputs(self.first, self.second)), set(ci.OUTPUTS))

    def test_each_output_mismatch_fails(self):
        for name in ci.OUTPUTS:
            with self.subTest(name=name):
                path = self.second / name
                path.write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "not reproducible"):
                    ci.compare_outputs(self.first, self.second)
                path.write_bytes(name.encode())

    def test_missing_and_empty_outputs_fail(self):
        for name in ci.OUTPUTS:
            with self.subTest(name=name):
                path = self.second / name
                path.unlink()
                with self.assertRaisesRegex(ValueError, "Missing"):
                    ci.compare_outputs(self.first, self.second)
                path.touch()
                with self.assertRaisesRegex(ValueError, "empty"):
                    ci.compare_outputs(self.first, self.second)
                path.write_bytes(name.encode())

    def test_same_directory_is_not_independent(self):
        with self.assertRaisesRegex(ValueError, "independent"):
            ci.compare_outputs(self.first, self.first)


class QueryInputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.query = self.root / "tests/query"
        self.query.mkdir(parents=True)
        self.fixture = self.query / "corpus.json"
        self.fixture.write_bytes(b'{"cases": []}\n')
        self.git("init", "-q")
        self.git("config", "core.autocrlf", "false")
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
        self.commit = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args],
                                       stderr=subprocess.PIPE).decode()

    def verify(self):
        return ci.verify_query_inputs(self.root, self.commit)

    def test_records_immutable_query_inputs(self):
        report = self.verify()
        self.assertEqual(report["commit"], self.commit)
        self.assertEqual(report["input_count"], 1)
        self.assertEqual(len(report["source_sha256"]), 64)

    def test_modified_fixture_fails_even_if_staged(self):
        self.fixture.write_bytes(b'{"cases": [1]}\n')
        self.git("add", ".")
        with self.assertRaisesRegex(ValueError, "Modified Core Query"):
            self.verify()

    def test_missing_fixture_fails(self):
        self.fixture.unlink()
        with self.assertRaisesRegex(ValueError, "Missing"):
            self.verify()

    def test_ignored_injected_python_fails(self):
        (self.root / ".git/info/exclude").write_text("injected.py\n", encoding="utf-8")
        (self.query / "injected.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            self.verify()


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_tiers_and_invalid_configuration(self):
        self.assertEqual(ci.configurations("full"), ("Release", "Debug"))
        for tier in ("pr", "main", "release"):
            self.assertEqual(ci.configurations(tier), ("Release",))
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                ci.execute(tier, "Debug", self.root / tier)
        with self.assertRaisesRegex(ValueError, "Unknown"):
            ci.configurations("typo")

    def test_stale_evidence_rejected(self):
        with self.assertRaisesRegex(ValueError, "fresh"):
            ci.execute("pr", "Release", self.root)

    def test_command_failure_is_logged_and_propagated(self):
        runner = ci.Runner(self.root)
        with self.assertRaisesRegex(RuntimeError, "failed"):
            runner.run("bad", sys.executable, "-c", "print('failure evidence'); raise SystemExit(7)")
        self.assertEqual(runner.commands[0]["exit_code"], 7)
        self.assertIn("failure evidence", (self.root / "bad.log").read_text())

    def test_python_assertions_cannot_be_disabled_by_environment(self):
        with patch.dict(ci.os.environ, {"PYTHONOPTIMIZE": "2"}):
            runner = ci.Runner(self.root)
            self.assertEqual(runner.run("assertions", sys.executable, "-c", "print(__debug__)"), "True")

    def test_stderr_notices_do_not_corrupt_json_stdout(self):
        runner = ci.Runner(self.root)
        output = runner.run("json", sys.executable, "-c",
                            "import sys; print('[1]'); print('npm notice', file=sys.stderr)",
                            separate_stderr=True)
        self.assertEqual(json.loads(output), [1])
        self.assertIn("npm notice", (self.root / "json.stderr.log").read_text())

    def test_local_core_receipt_rejected(self):
        (self.root / "core-selection.json").write_text(json.dumps({"mode": "local-development"}))
        with self.assertRaisesRegex(ValueError, "pinned-source"):
            ci.read_selection(self.root)

    def test_failed_run_writes_failed_evidence(self):
        output = self.root / "run"
        with patch.object(ci.Runner, "run", side_effect=RuntimeError("missing compiler")):
            with self.assertRaisesRegex(RuntimeError, "missing compiler"):
                ci.execute("release", "Release", output)
        result = json.loads((output / "evidence/result.json").read_text())
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["reproducibility_verified"])
        self.assertFalse(result["release_verified"])

    def fake_command(self, name, *command):
        return "v22.16.0" if name == "version-node" else "fixture"

    def fake_build(self, runner, output, configuration, name):
        dist = output / name / "dist"
        dist.mkdir(parents=True)
        for filename in ci.OUTPUTS:
            (dist / filename).write_bytes(filename.encode())
        return {"outputs": ci.output_hashes(dist), "package": {"archive_sha256": "fixture"}}

    def test_only_release_requires_two_builds(self):
        for tier in ci.TIERS:
            with self.subTest(tier=tier), patch.object(ci.Runner, "run", self.fake_command), \
                    patch.object(ci, "build_and_check", side_effect=self.fake_build) as build, \
                    patch.object(ci.migration_compatibility, "check", return_value={"status": "passed"}) as migration:
                result = ci.execute(tier, "Release", self.root / tier)
                self.assertEqual(build.call_count, 2 if tier == "release" else 1)
                self.assertEqual(result["status"], "passed")
                self.assertEqual(result["reproducibility_verified"], tier == "release")
                self.assertFalse(result["release_verified"])
                self.assertEqual(migration.call_count, int(tier in ("full", "release")))

    def test_migration_mismatch_cannot_pass_full(self):
        output = self.root / "migration-mismatch"
        with patch.object(ci.Runner, "run", self.fake_command), \
                patch.object(ci, "build_and_check", side_effect=self.fake_build), \
                patch.object(ci.migration_compatibility, "check", side_effect=ValueError("contract mismatch")):
            with self.assertRaisesRegex(ValueError, "contract mismatch"):
                ci.execute("full", "Release", output)
        result = json.loads((output / "evidence/result.json").read_text())
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("migration_compatibility", result)

    def test_debug_does_not_compare_release_baseline(self):
        with patch.object(ci.Runner, "run", self.fake_command), \
                patch.object(ci, "build_and_check", side_effect=self.fake_build), \
                patch.object(ci.migration_compatibility, "check") as migration:
            result = ci.execute("full", "Debug", self.root / "debug")
        self.assertEqual(result["status"], "passed")
        migration.assert_not_called()

    def test_second_build_failure_cannot_pass_release(self):
        output = self.root / "release"
        with patch.object(ci.Runner, "run", self.fake_command), \
                patch.object(ci, "build_and_check", side_effect=[{}, RuntimeError("second build failed")]):
            with self.assertRaisesRegex(RuntimeError, "second build failed"):
                ci.execute("release", "Release", output)
        result = json.loads((output / "evidence/result.json").read_text())
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["reproducibility_verified"])

    def test_comparison_failure_cannot_pass_release(self):
        output = self.root / "release"
        with patch.object(ci.Runner, "run", self.fake_command), \
                patch.object(ci, "build_and_check", side_effect=self.fake_build), \
                patch.object(ci, "compare_outputs", side_effect=ValueError("hash mismatch")):
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                ci.execute("release", "Release", output)
        result = json.loads((output / "evidence/result.json").read_text())
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["reproducibility_verified"])

    def test_package_mismatch_cannot_pass_release(self):
        def changed_package(runner, output, configuration, name):
            result = self.fake_build(runner, output, configuration, name)
            result["package"]["archive_sha256"] = name
            return result

        output = self.root / "different-packages"
        with patch.object(ci.Runner, "run", self.fake_command), \
                patch.object(ci, "build_and_check", side_effect=changed_package):
            with self.assertRaisesRegex(ValueError, "package archives are not reproducible"):
                ci.execute("release", "Release", output)
        result = json.loads((output / "evidence/result.json").read_text())
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["reproducibility_verified"])


if __name__ == "__main__":
    unittest.main()
