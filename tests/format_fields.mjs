// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel
// Binding contracts: marshalling, owned configuration, errors and lifetimes.
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";
const { loadOpenTLV, hexToBytes: hex } = await import(pathToFileURL(resolve(process.argv[2], "opentlv.mjs")).href);
const api = await loadOpenTLV();
const { Field, Format, FormatError, Document, QueryProgram } = api;
const keep = [];
const own = value => { keep.push(value); return value; };
const error = run => assert.throws(run, FormatError);
try {
  const tag = own(Field.fixedIdentifier(2));
  assert.deepEqual(tag.read(hex("1234FF")), { tag: hex("1234"), consumed: 2 });
  assert.deepEqual(tag.encode(hex("1234")), hex("1234"));
  assert.throws(() => tag.read(hex("12")), e => e instanceof FormatError && e.consumed === 1);
  error(() => tag.encode(hex("12")));
  error(() => Field.fixedIdentifier(0));
  for (const order of ["big", "little"]) {
    const length = own(Field.fixedLength(8, order));
    assert.deepEqual(length.encode(0x0102), hex(order === "big" ? "0000000000000102" : "0201000000000000"));
    for (const value of [0, 255, 9007199254740993n, 0xffffffffffffffffn]) {
      assert.equal(length.read(length.encode(value)).value, value);
    }
    assert.throws(() => length.encode(-1), RangeError);
    assert.throws(() => length.encode(2 ** 54), TypeError);
    assert.throws(() => length.encode(1n << 64n), RangeError);
  }
  const variable = own(Field.variableIdentifier());
  assert.deepEqual(variable.encode(hex("9F8101")), hex("9F8101"));
  assert.deepEqual(variable.read(hex("9F8101FF")).tag, hex("9F8101"));
  error(() => variable.encode(hex("9F81")));
  const forbidden = hex("00FF");
  const policy = { forbidden_leading: forbidden, require_minimal: true, reject_zero_first_payload: true };
  const constrained = own(Field.variableIdentifier({ policy }));
  forbidden.fill(0x42); policy.require_minimal = false;
  error(() => constrained.read(hex("00")));
  error(() => constrained.read(hex("1F8001")));
  const long = own(Field.variableLength());
  assert.deepEqual(long.encode(128), hex("8180"));
  assert.equal(long.read(hex("820080")).value, 128);
  const strict = own(Field.variableLength({ policy: { require_minimal: true } }));
  error(() => strict.read(hex("820080")));
  assert.equal(long.read(long.encode(0xffffffffffffffffn)).value, 0xffffffffffffffffn);
  const bounded = own(Field.variableLength({ policy: { allow_short: false, max_long_octets: 1, max_value: 9 } }));
  assert.deepEqual(bounded.encode(9), hex("8109"));
  error(() => bounded.encode(10));
  error(() => bounded.read(hex("09")));
  const escaped = own(Field.escapedLength({ min_extended: 0 }));
  assert.equal(escaped.read(hex("FF0001")).value, 1);
  assert.deepEqual(escaped.encode(1), hex("01"));
  error(() => Field.variableIdentifier({ inline_mask: 0 }));
  error(() => Field.variableLength({ long_form_bit: 3 }));
  error(() => Field.escapedLength({ extended_size: 0 }));
  assert.throws(() => Field.variableIdentifier({ inline_mask: 256 }), RangeError);
  assert.throws(() => Field.fixedLength(2, "native"), TypeError);
  const bits = own(Field.packed({ storage_size: 2, bit_offset: 4, bit_width: 8 }));
  const original = hex("F00F");
  assert.deepEqual(bits.encode(0x5a, original), hex("F5AF"));
  assert.deepEqual(original, hex("F00F"));
  assert.equal(bits.read(hex("F5AF")).value, 0x5a);
  error(() => bits.encode(256, original));
  assert.throws(() => bits.read(hex("00")), e => e instanceof FormatError && e.consumed === 0);
  const wide = own(Field.packed({ storage_size: 8, bit_width: 64 }));
  assert.equal(wide.read(wide.encode(0xffffffffffffffffn, new Uint8Array(8))).value, 0xffffffffffffffffn);

  // Composition snapshots fields and tag-only tables and supports LTV/count scope.
  const id = Field.fixedIdentifier(1), len = Field.fixedLength(1);
  const tagOnly = hex("00");
  const composed = own(Format.compose(id, len, { element_order: "ltv", length_scope: "tag-and-value" }));
  const tagged = own(Format.compose(id, len, { tag_only: [tagOnly] }));
  id.close(); len.close(); tagOnly[0] = 9;
  error(() => id.read(hex("01")));
  assert.equal(composed.canRead, true); assert.equal(composed.canWrite, true);
  const element = { tag: hex("12"), value: hex("ABCD") };
  assert.deepEqual(composed.encode(element), hex("0312ABCD"));
  assert.deepEqual(composed.measure(element), { header: 2, value: 2, trailer: 0, total: 4 });
  const decoded = composed.decode(hex("0312ABCDFFFF"));
  assert.deepEqual(decoded.tag, element.tag); assert.deepEqual(decoded.value, element.value);
  assert.equal(decoded.encodedSize, 4);
  assert.deepEqual(decoded.source.tag, { offset: 1, size: 1 });
  assert.deepEqual(composed.preserve(hex("0312ABCDFF"), element), hex("0312ABCD"));
  error(() => composed.preserve(hex("0312ABCD"), { ...element, value: hex("ABCE") }));
  assert.deepEqual(tagged.encode({ tag: hex("00"), value: new Uint8Array() }), hex("00"));
  assert.equal(tagged.decode(hex("00")).encodedSize, 1);
  error(() => tagged.encode({ tag: hex("00"), value: hex("01") }));

  const vf = own(Format.variable({ constructed: { byte_index: 0, mask: 0x20, value: 0x20 } }));
  assert.equal(vf.decode(hex("2100")).constructed, true);
  const padded = hex("018101AA");
  const value = vf.decode(padded);
  assert.deepEqual(vf.encode(value), hex("0101AA"));
  assert.deepEqual(vf.preserve(padded, value), padded);
  const ef = own(Format.escaped({ length: { min_extended: 0 }, tag_only: [hex("00")] }));
  assert.deepEqual(ef.preserve(hex("01FF0001AA"), elementFrom(hex("01"), hex("AA"))), hex("01FF0001AA"));
  assert.deepEqual(ef.encode(elementFrom(hex("01"), hex("AA"))), hex("0101AA"));
  assert.equal(ef.decode(hex("00")).encodedSize, 1);
  const table = hex("00010203");
  const pf = own(Format.packed({ header_size: 1, tag_size: 1, tag_storage: table,
    tag: { bit_offset: 6, bit_width: 2 }, length: { bit_offset: 0, bit_width: 6 } }));
  table.fill(0xff);
  assert.deepEqual(pf.encode(elementFrom(hex("02"), hex("AABB"))), hex("82AABB"));
  assert.deepEqual(pf.decode(hex("82AABB")).tag, hex("02"));
  const invalidTable = own(Format.packed({ header_size: 1, tag_size: 1, tag_storage: hex("00112233"),
    tag: { bit_offset: 6, bit_width: 2 }, length: { bit_offset: 0, bit_width: 6 } }));
  error(() => invalidTable.decode(hex("820000")));
  error(() => Format.packed({ header_size: 1, tag_size: 1, tag_storage: hex("0011"),
    tag: { bit_width: 1 }, length: { bit_width: 7 } }));
  error(() => Format.variable({ constructed: { mask: 0, value: 0 } }));

  // Owning copies survive subsequent calls, heap growth, and caller mutation.
  const source = hex("0101AA");
  const copied = vf.decode(source); source.fill(0);
  const big = own(Format.fixed({ tag_size: 1, length_size: 4 }));
  big.encode({ tag: hex("01"), value: new Uint8Array(20 * 1024 * 1024) });
  assert.deepEqual(copied.value, hex("AA"));
  assert.deepEqual(vf.decode(hex("0101BB")).value, hex("BB"));
  assert.deepEqual(copied.value, hex("AA"));
  const largeFormat = own(Format.fixed({ length_size: 8 }));
  assert.equal(largeFormat.measure({ tag: hex("01"), valueSize: 9007199254740993n }).total, 9007199254741002n);

  // A Query/Document keeps native configuration alive after public close().
  const lifetime = Format.variable();
  const document = own(new Document(hex("0101AA"), { format: lifetime }));
  const query = own(new QueryProgram("//*", { format: lifetime }));
  lifetime.close(); lifetime.close();
  error(() => lifetime.decode(hex("0100")));
  assert.deepEqual(document.encode(), hex("0101AA"));
  assert.equal(query.evaluate(hex("0101AA")).length, 1);
  assert.deepEqual(document.first.value, hex("AA"));

  // Existing custom formats gain direct operations and preserve callback errors.
  const sentinel = new Error("callback failure");
  let custom;
  custom = own(Format.custom({ decode() { assert.throws(() => custom.close()); throw sentinel; } }));
  assert.equal(custom.canWrite, false);
  assert.throws(() => custom.decode(hex("00")), e => e === sentinel);
  assert.throws(() => custom.measure({ tag: hex("01"), valueSize: 1n << 32n }), RangeError);
  const customRoundtrip = own(Format.custom({
    decode(data) { return { tag: data.slice(0, 1), header: { offset: 0, size: 1 }, value: { offset: 1, size: data.length - 1 } }; },
    measure(e) { return { header: 1, value: e.valueSize }; },
    encode(e) { return Uint8Array.of(...e.tag, ...e.value); }
  }));
  assert.deepEqual(customRoundtrip.encode(elementFrom(hex("01"), hex("AABB"))), hex("01AABB"));
  assert.deepEqual(customRoundtrip.decode(hex("01AABB")).value, hex("AABB"));
  error(() => vf.decode(hex("0182")));
  assert.throws(() => vf.decode(hex("0182")), e => e instanceof FormatError && Boolean(e.format?.length));
  assert.throws(() => vf.encode({ tag: hex("01"), value: hex("00"), valueSize: 2 }), RangeError);
  const closing = Format.fixed();
  assert.throws(() => closing.encode({ get tag() { closing.close(); return hex("01"); }, value: hex("AA") }), FormatError);
  const closingField = Field.fixedLength();
  const closingInput = hex("01");
  Object.defineProperty(closingInput, "length", { get() { closingField.close(); return 1; } });
  assert.throws(() => closingField.read(closingInput), FormatError);
  const alien = await loadOpenTLV();
  const alienField = alien.Field.fixedLength();
  try { assert.throws(() => Format.compose(tag, alienField), TypeError); }
  finally { alienField.close(); }
  console.log("Generic Format/field binding contracts passed");
} finally { for (const object of keep.reverse()) object.close(); }
function elementFrom(tag, value) { return { tag, value }; }
