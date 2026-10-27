// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel
// Inspect the emitted binary, module namespaces and initialized Emscripten API.
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const dist = resolve(process.argv[2]);
const wasmBinary = await readFile(resolve(dist, 'opentlv-core.wasm'));
const binary = await WebAssembly.compile(wasmBinary);
const modules = {};
let runtime;
for (const name of ['opentlv-core.js', 'opentlv.mjs', 'query.mjs']) {
  const namespace = await import(pathToFileURL(resolve(dist, name)).href);
  modules[name] = Object.fromEntries(Object.keys(namespace).sort().map(
    key => [key, typeof namespace[key]]));
  if (name === 'opentlv-core.js') runtime = await namespace.default({ wasmBinary });
}
const order = entries => entries.sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
console.log(JSON.stringify({
  modules,
  runtime: Object.fromEntries(Object.keys(runtime).sort().map(key => [key, typeof runtime[key]])),
  exports: order(WebAssembly.Module.exports(binary)),
  imports: order(WebAssembly.Module.imports(binary)),
}, null, 2));
