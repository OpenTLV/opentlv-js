// SPDX-License-Identifier: MIT
// Copyright (c) 2026 OpenTLV
// Copied outside the source tree and run against the installed local archive.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import * as entry from "opentlv-js";
import * as facade from "opentlv-js/opentlv.mjs";
import { queryFacade } from "opentlv-js/query.mjs";
import createOpenTLV from "opentlv-js/opentlv-core.js";
import { packageVersion } from "opentlv-js/version";

const metadata = JSON.parse(await readFile(new URL(import.meta.resolve("opentlv-js/package.json"))));
assert.equal(metadata.private, true);
assert.equal(packageVersion, metadata.version);
assert.equal(entry.packageVersion, metadata.version);
assert.deepEqual(Object.keys(entry).sort(), [...Object.keys(facade), "packageVersion"].sort());
for (const name of Object.keys(facade)) assert.equal(entry[name], facade[name]);
assert.equal(typeof queryFacade, "function");
assert.equal(typeof createOpenTLV, "function");
const wasmURL = new URL(import.meta.resolve("opentlv-js/opentlv-core.wasm"));
assert.equal(WebAssembly.validate(await readFile(wasmURL)), true);

const api = await entry.loadOpenTLV();
const wasm = await createOpenTLV();
assert.equal(api.version, wasm.UTF8ToString(wasm._opentlv_wasm_version()));
assert.match(api.version, /^\d+\.\d+\.\d+/);
const parsed = api.parse(entry.hexToBytes("6F 03 84 01 41"), { format: "ber" });
assert.equal(parsed.error, undefined);
assert.equal(parsed.elements[0].children[0].value, "41");
// Exercise a caller-supplied asset location as well as the adjacent default.
let located = false;
await entry.loadOpenTLV({ locateFile(name) {
  assert.equal(name, "opentlv-core.wasm");
  located = true;
  return wasmURL.href;
} });
assert.equal(located, true);
assert.throws(() => import.meta.resolve("opentlv-js/dist/query.mjs"),
              { code: "ERR_PACKAGE_PATH_NOT_EXPORTED" });
console.log(JSON.stringify({ packageVersion, coreVersion: api.version, exports: Object.keys(metadata.exports) }));
