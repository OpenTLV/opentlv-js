// Smoke test for the WebAssembly build: node smoke.mjs <directory with opentlv.mjs>
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { join, resolve } from "node:path";

const dist = resolve(process.argv[2] ?? ".");
const { loadOpenTLV, hexToBytes, MODULES } = await import(pathToFileURL(join(dist, "opentlv.mjs")).href);
const opentlv = await loadOpenTLV();

assert.deepEqual(MODULES, ["none", "emv"]);
assert.ok(opentlv.modules.includes("none"));
assert.equal(opentlv.modules.includes("emv"), opentlv.formats.includes("emv"));

assert.match(opentlv.version, /^\d+\.\d+\.\d+/);

if (opentlv.formats.includes("emv")) {
  const emv = opentlv.parse(hexToBytes("70 03 9F 02 00"), { format: "emv", module: "emv" });
  assert.equal(emv.error, undefined);
  assert.equal(emv.elements[0].constructed, true);
  assert.equal(emv.elements[0].children[0].tag, "9F02");
  assert.ok(opentlv.parse(hexToBytes("70 80 00 00"), { format: "emv" }).error);
}

if (opentlv.formats.includes("nfc-type2")) {
  const nfc = opentlv.parse(hexToBytes("00 03 03 D1 01 00 FE 00"), { format: "nfc-type2" });
  assert.equal(nfc.error, undefined);
  assert.deepEqual(nfc.elements.map(({ tag, length, value }) => [tag, length, value]),
    [["00", 0, ""], ["03", 3, "D10100"], ["FE", 0, ""], ["00", 0, ""]]);
  assert.deepEqual(nfc.elements[1].source.tag, { offset: 1, length: 1 });
  assert.ok(opentlv.parse(hexToBytes("03 FF FF FF"), { format: "nfc-type2" }).error);
}

if (opentlv.formats.includes("lldp")) {
  const lldp = opentlv.parse(hexToBytes("06 02 00 78 00 00"), { format: "lldp" });
  assert.equal(lldp.error, undefined);
  assert.deepEqual(lldp.elements.map(({ tag, length, value }) => [tag, length, value]),
    [["03", 2, "0078"], ["00", 0, ""]]);
  assert.deepEqual(lldp.elements[0].source.tag, { offset: 0, length: 1 });
}

// A one-byte fixed format has no constructed tags: one flat element holds the whole value.
const sample = hexToBytes("6F 0A 84 03 41 42 43 A5 03 50 01 01");
let result = opentlv.parse(sample, { format: "fixed" });
assert.equal(result.error, undefined);
assert.deepEqual(
  result.elements.map(({ tag, length, value }) => [tag, length, value]),
  [["6F", 10, "8403414243A503500101"]],
);

// The same bytes as BER: 6F is constructed and nests 84 and A5 (which nests 50).
result = opentlv.parse(sample, { format: "ber" });
assert.equal(result.error, undefined);
const [fci] = result.elements;
assert.equal(fci.tag, "6F");
assert.equal(fci.constructed, true);
assert.equal(opentlv.parse(sample).elements[0].constructed, true);
assert.ok(opentlv.parse(sample, { format: "compact" }).error);
assert.ok(opentlv.parse(sample, { format: "default" }).error);
assert.deepEqual(
  fci.children.map((child) => [child.tag, child.offset, child.depth]),
  [["84", 2, 1], ["A5", 7, 1]],
);
assert.equal(fci.children[0].value, "414243");
assert.equal(fci.children[1].children[0].tag, "50");
assert.equal(fci.children[1].children[0].value, "01");

// Source ranges distinguish logical values from complete encoded elements.
assert.deepEqual(
  [fci.headerSize, fci.children[0].headerSize, fci.children[1].children[0].headerSize],
  [2, 2, 2],
);
result = opentlv.parse(hexToBytes("5F 2D 02 65 6E"), { format: "ber" });
assert.equal(result.elements[0].headerSize, 3);
assert.equal(result.module, undefined);
assert.equal(result.elements[0].name, undefined);

// The EMV module names known tags and flags lengths the dictionary does not permit.
result = opentlv.parse(sample, { format: "ber", module: "emv" });
assert.equal(result.error, undefined);
assert.equal(result.module, "emv");
assert.equal(result.elements[0].symbol, "fci_template");
assert.match(result.elements[0].name, /FCI/);
assert.equal(result.elements[0].children[0].symbol, "df_name");
assert.equal(result.elements[0].children[0].lengthValid, false); // DF Name is 5..16 bytes long
result = opentlv.parse(hexToBytes("9F 02 06 00 00 00 00 01 00 DF 99 01 00"), { format: "ber", module: "emv" });
assert.equal(result.elements[0].symbol, "amount_authorised");
assert.equal(result.elements[0].lengthValid, true);
assert.equal(result.elements[1].symbol, undefined);
assert.ok(opentlv.parse(sample, { format: "fixed", module: "emv" }).error);
assert.ok(opentlv.parse(sample, { format: "ber", module: "nope" }).error);

// Errors are reported to the caller together with the elements read before them.
result = opentlv.parse(hexToBytes("84 03 41 42 43 84 05 41"), { format: "ber" });
assert.equal(result.elements.length, 1);
assert.equal(result.elements[0].tag, "84");
assert.ok(result.error, "truncated input must report an error");
assert.equal(result.error.offset, 7);
assert.deepEqual(result.error.location, {domain: "input", kind: "point", begin: 7, end: 7});
assert.equal(typeof result.error.message, "string");
assert.notEqual(result.error.code, 0);

// Bluetooth LTV: the length precedes the type, and the reported length is the value length.
result = opentlv.parse(hexToBytes("02 01 06 03 09 48 69"), { format: "bluetooth-ltv" });
assert.equal(result.error, undefined);
assert.equal(result.elements.length, 2);
assert.equal(result.elements[1].tag, "09");
assert.equal(result.elements[1].length, 2);
assert.equal(result.elements[1].headerSize, 2);
assert.equal(result.elements[1].value, "4869");
assert.equal(result.elements[0].name, "Flags");

// Container padding is separate from strict LTV framing and never trims values.
result = opentlv.parse(hexToBytes("02 01 06 00 00 00"), { format: "bluetooth-ad" });
assert.equal(result.error, undefined);
assert.equal(result.elements.length, 1);
assert.deepEqual(result.padding, { offset: 3, length: 3 });
result = opentlv.parse(hexToBytes("02 01 06 00 00 00"), { format: "bluetooth-ltv" });
assert.equal(result.error.code, 6); // TLV_ERR_INVALID_LENGTH
assert.equal(result.elements.length, 1);
assert.equal(result.padding, undefined);
result = opentlv.parse(hexToBytes("02 01 06 00 00 01"), { format: "bluetooth-ad" });
assert.equal(result.error.offset, 5);
assert.equal(result.elements.length, 1);
assert.equal(result.padding, undefined);
result = opentlv.parse(hexToBytes("02 FE 00"), { format: "bluetooth-ad" });
assert.equal(result.error, undefined);
assert.equal(result.elements[0].value, "00");
assert.equal(result.elements[0].name, undefined);
assert.equal(result.padding, undefined);
result = opentlv.parse(hexToBytes("00 00"), { format: "bluetooth-ad" });
assert.deepEqual(result.elements, []);
assert.deepEqual(result.padding, { offset: 0, length: 2 });
assert.deepEqual(opentlv.parse(new Uint8Array(0), { format: "bluetooth-ad" }).elements, []);
result = opentlv.parse(hexToBytes("02 01 06 04 09 00 00"), { format: "bluetooth-ad" });
assert.equal(result.error.code, 3); // TLV_ERR_TRUNCATED
assert.equal(result.error.offset, 5);
assert.equal(result.elements.length, 1);
assert.ok(opentlv.parse(sample, { format: "bluetooth-ad", module: "emv" }).error);

// Configurable fixed-width format: a two-byte tag, then a one-byte big-endian length.
result = opentlv.parse(hexToBytes("12 34 03 AA BB CC"), {
  format: "fixed", fixedTagSize: 2, fixedLengthSize: 1, fixedByteOrder: "big",
});
assert.equal(result.error, undefined);
assert.equal(result.elements.length, 1);
assert.equal(result.elements[0].tag, "1234");
assert.equal(result.elements[0].length, 3);
assert.equal(result.elements[0].headerSize, 3);
assert.equal(result.elements[0].value, "AABBCC");

result = opentlv.parse(hexToBytes("04 01 AA BB CC 02 04 2A"), {
  format: "fixed", fixedElementOrder: "ltv", fixedLengthScope: "tag-and-value",
});
assert.equal(result.error, undefined);
assert.equal(result.elements[0].length, 3);
assert.equal(result.elements[0].encodedSize, 5);
assert.deepEqual(result.elements[0].source.tag, { offset: 1, length: 1 });
assert.deepEqual(result.elements[0].source.length, { offset: 0, length: 1 });
assert.deepEqual(result.elements[1].source.value, { offset: 7, length: 1 });
result = opentlv.parse(hexToBytes("30 80 02 01 05 00 00"), { format: "ber" });
assert.equal(result.error, undefined);
assert.equal(result.elements[0].length, 3);
assert.equal(result.elements[0].encodedSize, 7);
assert.deepEqual(result.elements[0].source.value, { offset: 2, length: 3 });
assert.deepEqual(result.elements[0].source.trailer, { offset: 5, length: 2 });
assert.equal(result.elements[0].children[0].offset, 2);
assert.ok(opentlv.formats.includes("fixed"));
assert.ok(opentlv.formats.includes("cer"));
result = opentlv.parse(hexToBytes("30 80 02 01 05 0C 05 48 65 6C 6C 6F 00 00"), { format: "cer" });
assert.equal(result.error, undefined);
assert.equal(result.elements[0].constructed, true);
assert.equal(result.elements[0].encodedSize, 14);
assert.equal(result.elements[0].length, 10);
assert.deepEqual(result.elements[0].source.trailer, { offset: 12, length: 2 });
assert.deepEqual(result.elements[0].children.map(e => e.tag), ["02", "0C"]);
assert.ok(opentlv.parse(hexToBytes("30 03 02 01 05"), { format: "cer" }).error);
assert.ok(opentlv.parse(hexToBytes("30 80 02 01 05"), { format: "cer" }).error);
assert.ok(opentlv.parse(sample, { format: "cer", module: "emv" }).error);
assert.ok(opentlv.formats.includes("bluetooth-ad"));
for (const invalid of [{ fixedTagSize: 0 }, { fixedLengthSize: 9 },
  { fixedByteOrder: "invalid" }, { fixedElementOrder: "invalid" },
  { fixedLengthScope: "invalid" }]) {
  assert.throws(() => opentlv.parse(sample, { format: "fixed", ...invalid }), TypeError);
}

// Unknown formats and bad arguments.
assert.ok(opentlv.parse(sample, { format: "nope" }).error);
assert.deepEqual(opentlv.parse(new Uint8Array(0)).elements, []);
assert.throws(() => opentlv.parse("6F"), TypeError);
assert.throws(() => hexToBytes("6F 0"), TypeError);

// Larger input grows module memory; results must still be correct.
const big = new Uint8Array(20 * 1024 * 1024);
big.set([0x84, 0xff]);
assert.ok(opentlv.parse(big, { format: "ber" }).error);

console.log("opentlv wasm smoke test passed");
