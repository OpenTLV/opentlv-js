# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel
"""Exercise declaration parsing, native references, exclusions and exact-pin diffs."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("api_coverage", ROOT / "scripts/api_coverage.py")
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)

HEADER = '''\
#define TLV_DECLARE(name) TLV_API int name(void);
/* TLV_API int tlv_commented(void); */
extern "C" {
// TLV_API int tlv_line_commented(void);
TLV_API tlv_result_t tlv_multi_line(const uint8_t* data,
                                  size_t size, void (*visit)(void* context, int item));
TLV_NODISCARD TLV_API const char* TLV_PRINTF(1, 2) tlv_attributed(const char* format, ...);
extern TLV_API const tlv_codec_t tlv_codec_sample;
TLV_API extern const tlv_format_t tlv_format_sample;
extern TLV_API const uint8_t tlv_table[TLV_TABLE_SIZE][2];
typedef struct { int (*callback)(void); } tlv_plain_t;
}
'''


def git(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root), "-c", "user.name=Coverage fixture",
         "-c", "user.email=coverage@example.invalid", "-c", "commit.gpgsign=false", *args],
        stderr=subprocess.STDOUT, text=True).strip()


def commit(root, files):
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "Fixture")
    return git(root, "rev-parse", "HEAD")


class CoverageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_declaration_shapes_and_unknown_shape(self):
        self.assertEqual(dict(api.declarations("sample.h", HEADER)), {
            "tlv_multi_line": "function", "tlv_attributed": "function",
            "tlv_codec_sample": "data", "tlv_format_sample": "data", "tlv_table": "data"})
        with self.assertRaisesRegex(ValueError, "Unrecognized TLV_API"):
            list(api.declarations("x.h", "TLV_API void (*tlv_handler(void))(int);"))

    def test_source_selection_excludes_tests_and_docs(self):
        bridge = self.root / "native"
        bridge.mkdir()
        (bridge / "bridge.h").write_text('static void f(void) { tlv_used(); }')
        (bridge / "bridge_test.c").write_text('tlv_test_only()')
        (bridge / "notes.md").write_text('tlv_documented_only')
        (bridge / "bridge.c").write_text('tlv_c(); /* tlv_comment */ "tlv_string";')
        found = api.references(self.root, ["native/*.h", "native/*.c"], ["**/*_test.c"])
        self.assertEqual({x for x in found if x.startswith("tlv_")}, {"tlv_used", "tlv_c"})
        with self.assertRaisesRegex(ValueError, "matches no files"):
            api.references(self.root, ["absent/*.c"])

    def test_ignores_require_reasons_and_stale_patterns_are_field_specific(self):
        config = {"schema": 1, "lock": "lock.json", "references": ["native"],
                  "ignore": [{"symbols": ["tlv_x"], "reason": " "}]}
        path = self.root / "config.json"
        path.write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError, "reason"):
            api.load_config(path)
        config["ignore"] = [{"reason": "native value", "symbols": ["tlv_x"], "headers": ["tlv_x"]}]
        ignored, stale = api.ignored(config, {"tlv_x": {"header": "tlv/value.h"}})
        self.assertEqual(ignored, {"tlv_x": "native value"})
        self.assertEqual(stale, ["tlv_x"])

    def test_ignored_symbols_take_precedence_and_builtin_headers_are_separate(self):
        symbols = {"tlv_hidden": {"header": "tlv/reader/reader.h"},
                   "tlv_kept": {"header": "tlv/reader/reader.h"},
                   "tlv_builtin": {"header": "tlv/builtins/example.h"}}
        ignored, stale = api.ignored({"ignore": [
            {"headers": ["tlv/reader/*"], "reason": "header exclusion"},
            {"symbols": ["tlv_hidden"], "reason": "overlapping exclusion"}]}, symbols)
        self.assertEqual(ignored["tlv_hidden"], "header exclusion")
        self.assertEqual(stale, [])
        scopes = api.coverage(symbols, {"tlv_hidden", "tlv_builtin"}, ignored)
        self.assertEqual(scopes["core"]["ignored"], 2)
        self.assertEqual(scopes["core"]["referenced"], 0)
        self.assertEqual(scopes["builtins"]["referenced"], 1)
        self.assertEqual(api.ratio(scopes["core"]), "-")

    def test_c_literals_do_not_turn_comment_markers_into_references(self):
        source = r'''tlv_before(); "// tlv_string"; '\''; /* tlv_comment */
                     "escaped \" /* tlv_literal */"; // tlv_line
                     tlv_after();'''
        found = set(api.IDENTIFIER.findall(api.strip_comments(Path("bridge.c"), source, literals=False)))
        self.assertEqual({name for name in found if name.startswith("tlv_")},
                         {"tlv_before", "tlv_after"})

    def test_repository_urls_and_fetch_use_exact_lock(self):
        for repository in ("OpenTLV/opentlv", "https://github.com/OpenTLV/opentlv.git"):
            self.assertEqual(api.repository_url(repository), "https://github.com/OpenTLV/opentlv.git")
        with self.assertRaises(ValueError):
            api.repository_url("--upload-pack=command")
        pin = {"repository": "https://github.com/OpenTLV/opentlv.git", "commit": "a" * 40}
        cache = self.root / "build/api-coverage/core.git"
        cache.mkdir(parents=True)
        with patch.object(api.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)), \
                patch.object(api, "git", return_value=b"a" * 40 + b"\n") as mocked:
            api.core_repository(self.root, None, [pin])
        self.assertEqual(mocked.call_args_list[0].args,
                         (cache, "fetch", "-q", "--depth=1", "--no-tags", pin["repository"], "a" * 40))

    def test_cli_exact_git_objects_pin_diff_scopes_and_summary(self):
        core, binding = self.root / "core", self.root / "binding"
        for repo in (core, binding):
            repo.mkdir()
            git(repo, "init", "-q")
        header = "tlv/include/tlv/sample.h"
        old = commit(core, {header: "TLV_API int tlv_used(void);\nTLV_API int tlv_removed(void);",
                           "tlv/include/tlv/builtins/example.h": "extern TLV_API int tlv_builtin;"})
        new = commit(core, {header: "TLV_API int tlv_used(void);\nTLV_API int tlv_added(void);\n"
                                   "TLV_API int tlv_ignored(void);"})
        # A dirty header must not affect an inventory of committed blobs.
        (core / header).write_text("TLV_API int tlv_dirty(void);")
        config = {"schema": 1, "lock": "lock.json", "references": ["native/*.c"],
                  "ignore": [{"reason": "native equivalent", "symbols": ["tlv_ignored", "tlv_stale"]}]}
        lock = {"repository": "https://github.com/OpenTLV/opentlv.git", "commit": old}
        base = commit(binding, {"lock.json": json.dumps(lock), "coverage.json": json.dumps(config),
                                "native/bridge.c": 'void f(void) { tlv_used(); tlv_builtin(); }\n'
                                                    '// tlv_added\n'})
        commit(binding, {"lock.json": json.dumps(dict(lock, commit=new))})
        output, summary = self.root / "report.json", self.root / "summary.md"
        summary.write_text("previous\n")
        command = [sys.executable, "-B", str(ROOT / "scripts/api_coverage.py"),
                   "--config", "coverage.json", "--core", str(core), "--base", base,
                   "--output", str(output), "--summary", str(summary)]
        result = subprocess.run(command, cwd=binding, capture_output=True, text=True, check=True)
        report = json.loads(output.read_text())
        self.assertEqual(report["core"]["commit"], new)
        self.assertEqual(report["scopes"]["core"]["headers"]["tlv/sample.h"], {
            "referenced": ["tlv_used"], "missing": ["tlv_added"], "ignored": ["tlv_ignored"]})
        self.assertEqual(report["scopes"]["builtins"]["referenced"], 1)
        self.assertEqual(report["ignored"], {"tlv_ignored": "native equivalent"})
        self.assertEqual(report["stale_ignores"], ["tlv_stale"])
        self.assertEqual(report["diff"]["base"]["commit"], old)
        self.assertEqual([x["name"] for x in report["diff"]["added"]], ["tlv_added", "tlv_ignored"])
        self.assertEqual([x["name"] for x in report["diff"]["removed"]], ["tlv_removed"])
        self.assertEqual(summary.read_text(), "previous\n" + result.stdout)
        self.assertIn("native equivalent", result.stdout)
        self.assertIn("not proof", result.stdout)
        unchanged = api.report(binding, config, core, base_commit=new)
        self.assertIn("Core pin unchanged", api.markdown(unchanged))
        self.assertEqual(unchanged["diff"]["added"], [])
        with self.assertRaisesRegex(ValueError, "fetch it first"):
            api.report(binding, config, core, base_commit="f" * 40)
        (binding / "lock.json").write_text(json.dumps(dict(lock, commit="main")))
        with self.assertRaisesRegex(ValueError, "immutable"):
            api.pin(binding, "lock.json")


if __name__ == "__main__":
    unittest.main()
