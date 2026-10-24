// Parses a nested BER-TLV document and prints every element in document
// order. See the C, C++ and Rust "parse" examples for the same bytes and
// the same fields. The JS/WASM binding currently only exposes parsing, so
// there is no "write", "query" or "validate" example here yet.
//
// Run with: node examples/parse.mjs <directory with opentlv.mjs>
// (build one first, see bindings/wasm/CMakeLists.txt).
import { pathToFileURL } from "node:url";
import { join, resolve } from "node:path";

const dist = resolve(process.argv[2] ?? ".");
const { loadOpenTLV, hexToBytes } = await import(pathToFileURL(join(dist, "opentlv.mjs")).href);
const opentlv = await loadOpenTLV();

// An FCI Template (6F) holding a DF Name (84) and an FCI Proprietary
// Template (A5) holding an Application Label (50).
const document = hexToBytes("6F 0A 84 03 41 42 43 A5 03 50 01 01");

function printElements(elements, depth = 0) {
  for (const element of elements) {
    const value = element.children ? "" : ` value=${element.value}`;
    console.log(`${"  ".repeat(depth)}tag=${element.tag} length=${element.length}${value}`);
    if (element.children) printElements(element.children, depth + 1);
  }
}

function countElements(elements) {
  return elements.reduce((sum, e) => sum + 1 + (e.children ? countElements(e.children) : 0), 0);
}

const result = opentlv.parse(document, { format: "ber" });
if (result.error) throw new Error(`parse error: ${result.error.message}`);
printElements(result.elements);

// 6F, its two children (84, A5) and A5's child (50).
if (countElements(result.elements) !== 4) process.exit(1);
