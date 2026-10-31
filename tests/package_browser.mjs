// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel
// Loads the installed package in a real headless browser, as a module page with
// the documented import map and as a module worker. Run by scripts/package.py.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { extname, join, resolve, sep } from "node:path";

const [packageDirectory, browser] = process.argv.slice(2).map((value, index) => (index ? value : resolve(value)));
assert.ok(packageDirectory && browser, "usage: package_browser.mjs <installed package> <browser>");
const metadata = JSON.parse(await readFile(join(packageDirectory, "package.json")));
const TIMEOUT_MS = 60000;
const TYPES = { ".mjs": "text/javascript", ".js": "text/javascript", ".wasm": "application/wasm" };

// Workers do not inherit import maps, so the shared check uses package-relative URLs.
const CHECK = `
export async function check(loadOpenTLV, hexToBytes, packageVersion) {
  const located = [];
  const api = await loadOpenTLV({ locateFile(name) { located.push(name); return "/assets/" + name; } });
  const adjacent = await loadOpenTLV();
  const parsed = adjacent.parse(hexToBytes("6F 03 84 01 41"), { format: "ber" });
  const document = api.Document.create();
  document.insert(hexToBytes("5A"), hexToBytes("01"));
  return { packageVersion, coreVersion: adjacent.version, located, parsedValue: parsed.elements[0].children[0].value,
           parseError: parsed.error ?? null, encoded: [...document.encode()] };
}`;
const WORKER = `
import { loadOpenTLV, hexToBytes, packageVersion } from "/package/index.mjs";
import { check } from "/check.mjs";
check(loadOpenTLV, hexToBytes, packageVersion).then(result => postMessage({ result }),
                                                    error => postMessage({ error: String(error?.stack ?? error) }));`;
const PAGE = `<!doctype html><meta charset="utf-8"><title>OpenTLV package check</title>
<script type="importmap">{"imports": {"@opentlv/opentlv": "/package/index.mjs"}}</script>
<script type="module">
const report = body => fetch("/result", { method: "POST", body: JSON.stringify(body) });
window.addEventListener("error", event => report({ error: String(event.message) }));
window.addEventListener("unhandledrejection", event => report({ error: String(event.reason?.stack ?? event.reason) }));
const { loadOpenTLV, hexToBytes, packageVersion } = await import("@opentlv/opentlv");
const { check } = await import("/check.mjs");
const page = await check(loadOpenTLV, hexToBytes, packageVersion);
const worker = await new Promise((done, failed) => {
  const instance = new Worker("/worker.mjs", { type: "module" });
  instance.onmessage = event => event.data.error ? failed(new Error(event.data.error)) : done(event.data.result);
  instance.onerror = event => failed(new Error(event.message || "worker failed to load"));
});
await report({ userAgent: navigator.userAgent, page, worker });
</script>`;

let finish;
let fail;
const reported = new Promise((done, failed) => { finish = done; fail = failed; });
const served = new Set();

function send(response, type, body) {
  response.writeHead(200, { "content-type": type, "cache-control": "no-store" });
  response.end(body);
}

const server = createServer(async (request, response) => {
  const { pathname } = new URL(request.url, "http://localhost");
  try {
    if (request.method === "POST" && pathname === "/result") {
      const chunks = [];
      for await (const chunk of request) chunks.push(chunk);
      send(response, "text/plain", "ok");
      finish(JSON.parse(Buffer.concat(chunks).toString()));
    } else if (pathname === "/") {
      send(response, "text/html", PAGE);
    } else if (pathname === "/check.mjs") {
      send(response, TYPES[".mjs"], CHECK);
    } else if (pathname === "/worker.mjs") {
      send(response, TYPES[".mjs"], WORKER);
    } else if (pathname === "/assets/opentlv-core.wasm" || pathname.startsWith("/package/")) {
      // A separately served copy proves that the documented locateFile option is used.
      const relative = pathname.startsWith("/assets/") ? "dist/opentlv-core.wasm" : decodeURIComponent(pathname.slice(9));
      const path = resolve(packageDirectory, relative);
      if (!path.startsWith(packageDirectory + sep) || !TYPES[extname(path)]) throw new Error(`Refused: ${pathname}`);
      const body = await readFile(path);
      served.add(pathname);
      send(response, TYPES[extname(path)], body);
    } else {
      response.writeHead(404).end();
    }
  } catch (error) {
    response.writeHead(404).end();
    fail(new Error(`${pathname}: ${error.message}`));
  }
});
await new Promise(done => server.listen(0, "127.0.0.1", done));

const profile = await mkdtemp(join(tmpdir(), "opentlv-browser-"));
// The sandbox needs host privileges CI containers may lack; only this local page is loaded.
const child = spawn(browser, ["--headless=new", "--no-sandbox", "--disable-gpu", "--no-first-run",
                              "--disable-background-networking", `--user-data-dir=${profile}`,
                              `http://127.0.0.1:${server.address().port}/`], { stdio: ["ignore", "ignore", "pipe"] });
let output = "";
child.stderr.on("data", chunk => { output = (output + chunk).slice(-4000); });
child.on("error", fail);
child.on("exit", code => fail(new Error(`Browser exited early (${code}):\n${output}`)));
const timer = setTimeout(() => fail(new Error(`No browser result in ${TIMEOUT_MS} ms:\n${output}`)), TIMEOUT_MS);

try {
  const result = await reported;
  assert.equal(result.error, undefined, result.error);
  const expected = { packageVersion: metadata.version, parsedValue: "41", parseError: null,
                     located: ["opentlv-core.wasm"], encoded: [0x5a, 0x01, 0x01] };
  for (const [scope, values] of [["page", result.page], ["worker", result.worker]]) {
    assert.match(values.coreVersion, /^\d+\.\d+\.\d+/, scope);
    const { coreVersion, ...observed } = values;
    assert.deepEqual(observed, expected, scope);
  }
  assert.ok(served.has("/assets/opentlv-core.wasm"), "locateFile did not serve the WASM binary");
  assert.ok(served.has("/package/dist/opentlv-core.wasm"), "The adjacent default did not serve the WASM binary");
  console.log(JSON.stringify({ userAgent: result.userAgent, coreVersion: result.page.coreVersion,
                               served: [...served].sort() }));
} finally {
  clearTimeout(timer);
  child.removeAllListeners("exit");
  child.kill();
  child.stderr.destroy();
  server.closeAllConnections();
  server.close();
  await new Promise(done => setTimeout(done, 500));
  await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }).catch(() => {});
}
