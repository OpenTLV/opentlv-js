// SPDX-License-Identifier: MIT
// Copyright (c) 2026 OpenTLV
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const { loadOpenTLV, hexToBytes: hex } = await import(pathToFileURL(resolve(process.argv[2], 'opentlv.mjs')));
const { ValueConstraint, ConstraintError, Tag, QueryError, StreamResult, Codec, CodecError,
  compileQuery, definitionResolver } = await loadOpenTLV();
const resources = [];
const own = value => { resources.push(value); return value; };
const minimum = -(1n << 63n), maximum = (1n << 63n) - 1n;
const rejected = run => assert.throws(run, error => error instanceof ConstraintError && error.code === StreamResult.SCHEMA);
try {
  const none = own(ValueConstraint.none());
  for (const value of [minimum, -1, 0, 1, maximum]) {
    assert.equal(none.validate(value), undefined); assert.equal(none.name(value), null);
  }
  const full = own(ValueConstraint.range(minimum, maximum));
  full.validate(minimum); full.validate(maximum);
  const range = own(ValueConstraint.range(-2, 3n));
  for (const value of [-2, -1n, 0, 3]) range.validate(value);
  rejected(() => range.validate(-3)); rejected(() => range.validate(4));
  assert.throws(() => ValueConstraint.range(3, 2), error =>
    error instanceof ConstraintError && error.code === StreamResult.INVALID_SCHEMA);
  const singleton = own(ValueConstraint.range(maximum, maximum));
  singleton.validate(maximum); rejected(() => singleton.validate(maximum - 1n));
  const entries = [{ value: minimum, name: 'minimum' }, { value: 7n, name: 'žltá "7"' },
    { value: maximum }, { value: 0, name: '' }, { value: 7, name: 'duplicate' }];
  const allowed = own(ValueConstraint.allowed(entries));
  entries[0].value = 1; entries[0].name = 'changed'; entries.length = 0;
  for (const value of [minimum, 7, maximum, 0]) allowed.validate(value);
  assert.equal(allowed.name(minimum), 'minimum');
  assert.equal(allowed.name(7), 'žltá "7"');
  assert.equal(allowed.name(maximum), null); assert.equal(allowed.name(0), '');
  assert.equal(allowed.name(1), null); rejected(() => allowed.validate(1));
  const empty = own(ValueConstraint.allowed([]));
  rejected(() => empty.validate(0)); assert.equal(empty.name(0), null);
  assert.throws(() => ValueConstraint.allowed([{ value: 1, name: 'a\0b' }]), TypeError);
  assert.throws(() => ValueConstraint.allowed([{ value: '1' }]), TypeError);
  assert.throws(() => ValueConstraint.allowed({}), TypeError);
  for (const value of [minimum - 1n, maximum + 1n]) {
    assert.throws(() => none.validate(value), RangeError);
    assert.throws(() => ValueConstraint.allowed([{ value }]), RangeError);
  }
  for (const value of [Number.MAX_SAFE_INTEGER + 1, 1.5, NaN, '1', true])
    assert.throws(() => none.validate(value), TypeError);
  allowed.close(); allowed.close();
  for (const run of [() => allowed.validate(7), () => allowed.name(7)])
    assert.throws(run, error => error instanceof QueryError && error.code === StreamResult.INVALID_STATE);

  for (const [left, right, order] of [['', '', 0], ['', '00', -1], ['00', '', 1],
    ['01', '0100', -1], ['80', '7F', 1], ['0100', '02', -1], ['9F02', '9F02', 0]]) {
    const a = hex(left), b = hex(right);
    assert.equal(Tag.compare(a, b), order); assert.equal(Tag.equal(a, b), order === 0);
    assert.equal(Tag.hash(a), Tag.hash(a.slice()));
    assert.ok(Number.isInteger(Tag.hash(a)) && Tag.hash(a) >= 0 && Tag.hash(a) <= 0xffffffff);
    assert.deepEqual(a, hex(left)); assert.deepEqual(b, hex(right));
  }
  assert.throws(() => Tag.hash('5A'), TypeError);
  assert.throws(() => Tag.compare(hex('5A'), null), TypeError);
  assert.throws(() => Tag.compare(hex('5A')), TypeError);
  const storage = hex('FF9F02FF');
  assert.equal(Tag.compare(storage.subarray(1, 3), hex('9F02')), 0);
  // Force WASM memory growth, then repeat a retained constraint and byte operation.
  const large = new Uint8Array(20 * 1024 * 1024);
  assert.equal(Tag.compare(large, large), 0); range.validate(3);

  // Checked Codec operations cover the excluded unchecked endian helpers.
  for (const encoding of ['big', 'little']) for (let width = 1; width <= 8; ++width) {
    const codec = own(Codec.number({ encoding, width }));
    const value = (1n << BigInt(width * 8)) - 1n;
    assert.deepEqual(codec.encode(value), new Uint8Array(width).fill(255));
    assert.equal(codec.decode(codec.encode(value)), value);
    const padded = new Uint8Array(width); padded[encoding === 'big' ? width - 1 : 0] = 1;
    assert.deepEqual(codec.encode(1), padded); assert.equal(codec.decode(padded), 1n);
    assert.equal(codec.measure(1), width);
    assert.throws(() => codec.decode(new Uint8Array(width - 1)), CodecError);
    assert.throws(() => codec.encode(value + 1n), width === 8 ? RangeError : CodecError);
  }

  // Binding-owned evidence for the JS representations of native Query adapters.
  const signed = own(Codec.builtin('int64-minimal-be'));
  const constraint = own(ValueConstraint.range(0, 10));
  const tag = hex('5A');
  const resolve = definitionResolver({ app: [{ name: 'count', tag }] }); tag.fill(0);
  const query = own(compileQuery("num(//name('app','count'))", { resolve,
    providers: { num: { id: 7001, decode: data => {
      const value = signed.decode(data); constraint.validate(value); return value;
    } } } }));
  assert.equal(query.evaluate(hex('5A0107')), 7);
  rejected(() => query.evaluate(hex('5A010B')));
  assert.throws(() => query.evaluate(hex('5A020007')), CodecError);
  assert.equal(query.evaluate(hex('5A0108')), 8);
  const unsigned = own(Codec.number({ encoding: 'little', width: 8 }));
  const wide = own(compileQuery('num(//5A)', { providers: { num: {
    id: 7002, decode: data => unsigned.decode(data),
  } } }));
  assert.equal(wide.evaluate(hex('5A080100000000000000')), 1);
  assert.throws(() => wide.evaluate(hex('5A08FFFFFFFFFFFFFFFF')), RangeError);
  signed.close();
  assert.throws(() => query.evaluate(hex('5A0101')), QueryError);
  const text = own(Codec.text());
  const textQuery = own(compileQuery('text(//5A)', { providers: { text: {
    id: 7003, max_result_bytes: 8, decode: data => text.decode(data),
  } } }));
  assert.equal(textQuery.evaluate(hex('5A024142')), 'AB');
  assert.throws(() => textQuery.evaluate(hex('5A01FF')), CodecError);
} finally { for (const resource of resources.reverse()) resource.close(); }
console.log('JS/WASM generic completion: constraints, tags and Query composition passed');
