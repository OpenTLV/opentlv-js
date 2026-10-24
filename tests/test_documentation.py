# SPDX-License-Identifier: MIT
# Copyright (c) 2026 OpenTLV
"""Protect the transferred API manual and independent example version identity."""

import hashlib
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DocumentationTests(unittest.TestCase):
    def test_original_api_section_and_examples_are_preserved(self):
        record = json.loads((ROOT / "migration/documentation-source.json").read_text())
        manual = (ROOT / record["destination"]).read_text(encoding="utf-8")
        api = manual.split("## Use from JavaScript\n", 1)[1].split("## Documentation playground\n", 1)[0]
        api = api.replace("https://github.com/OpenTLV/opentlv/blob/main/docs/standards/emv/README.md",
                          "../standards/emv/README.md")
        self.assertEqual(hashlib.sha256(api.encode()).hexdigest(), record["api_section_sha256"])
        self.assertEqual(re.findall(r"^## (.+)$", manual, re.M)[:4],
                         ["Build", "Use from JavaScript", "Documentation playground", "Testing"])

    def test_catalog_uses_package_version_and_unchanged_parse_source(self):
        package = json.loads((ROOT / "package.json").read_text())
        catalog = json.loads((ROOT / "docs-examples.json").read_text())
        self.assertEqual(catalog["component_version"], package["version"])
        self.assertEqual(catalog["version"], 1)
        self.assertEqual(catalog["examples"], [{"feature": "ber.parse", "language": "js",
                         "status": "supported", "path": "examples/parse.mjs"}])
        # The existing migration verifier owns the immutable example byte check.
        self.assertTrue((ROOT / catalog["examples"][0]["path"]).is_file())


if __name__ == "__main__":
    unittest.main()
