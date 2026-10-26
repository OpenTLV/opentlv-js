// SPDX-License-Identifier: MIT
// Copyright (c) 2026 OpenTLV
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";
const { loadOpenTLV, hexToBytes } = await import(pathToFileURL(resolve(process.argv[2], "opentlv.mjs")).href);
const { Field, Format } = await loadOpenTLV();
const identifier = Field.fixedIdentifier(1);
const length = Field.variableLength({ policy: { require_minimal: true } });
let format;
try {
  format = Format.compose(identifier, length);
  identifier.close(); length.close(); // the Format retains its own native references
  const wire = format.encode({ tag: hexToBytes("42"), value: hexToBytes("AABB") });
  assert.deepEqual(wire, hexToBytes("4202AABB"));
  assert.deepEqual(format.decode(wire).value, hexToBytes("AABB"));
  console.log(Buffer.from(wire).toString("hex"));
} finally { format?.close(); length.close(); identifier.close(); }
