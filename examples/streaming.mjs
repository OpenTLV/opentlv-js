// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";
const { loadOpenTLV, hexToBytes } = await import(pathToFileURL(resolve(process.argv[2], "opentlv.mjs")).href);
const { TreeReader, TreeWriter } = await loadOpenTLV();
const input = hexToBytes("30060401AA0401BB");
const reader = new TreeReader(input.slice(0, 4), { incremental: true });
const writer = new TreeWriter({ capacity: 64 });
try {
  assert.equal(reader.nextEvent().status, "need-more-data");
  reader.setInput(input, { final: true });
  for (;;) {
    const result = reader.nextEvent();
    if (result.status === "end") break;
    writer.writeEvent(result.item);
  }
  assert.deepEqual(writer.finish(), input);
  console.log("Tree event round trip:", Buffer.from(writer.bytes).toString("hex").toUpperCase());
} finally { writer.close(); reader.close(); }
