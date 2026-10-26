// SPDX-License-Identifier: MIT
// Copyright (c) 2026 OpenTLV
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const { loadOpenTLV, hexToBytes: hex } = await import(pathToFileURL(resolve(process.argv[2], 'opentlv.mjs')));
const api = await loadOpenTLV();
const { Codec, CodecError, StructureCodec, Generator, Format, Writer, TreeReader } = api;
const resources = [];
const own = resource => { resources.push(resource); return resource; };
const fails = (run, reason) => assert.throws(run, error => error instanceof CodecError && (!reason || error.codec?.reason_name === reason));
try {
  for (const [name, value, encoded] of [
    ['uint8', 255, 'FF'], ['uint16-be', 65535, 'FFFF'], ['uint16-le', 258, '0201'],
    ['uint32-be', 0xffffffff, 'FFFFFFFF'], ['uint32-le', 0x01020304, '04030201'],
    ['int64-minimal-be', -(1n << 63n), '8000000000000000'],
  ]) {
    const codec = own(Codec.builtin(name));
    assert.deepEqual(codec.encode(value), hex(encoded));
    assert.equal(codec.measure(value), encoded.length / 2);
    assert.equal(codec.decode(hex(encoded)), value);
    fails(() => codec.encode(value, { capacity: 0 }));
    fails(() => codec.decode(new Uint8Array()));
  }
  const signed = own(Codec.builtin('int64-minimal-be'));
  for (const value of [-129n, -128n, -1n, 0n, 127n, 128n, (1n << 63n) - 1n])
    assert.equal(signed.decode(signed.encode(value)), value);
  fails(() => signed.decode(hex('0001')), 'canonical');
  assert.throws(() => signed.encode(1n << 63n), RangeError);
  const config = { encoding: 'little', width: 8 };
  assert.throws(() => Codec.number({ encoding: 'toString' }), TypeError);
  assert.throws(() => Codec.text({ alphabet: 'constructor' }), TypeError);
  const number = own(Codec.number(config)); config.width = 1;
  const maximum = (1n << 64n) - 1n;
  assert.equal(number.decode(number.encode(maximum)), maximum);
  assert.deepEqual(number.encode(0x0102n), hex('0201000000000000'));
  assert.throws(() => number.encode(maximum + 1n), RangeError);
  assert.throws(() => number.encode(Number.MAX_SAFE_INTEGER + 1), TypeError);
  assert.throws(() => number.encode(-1n), RangeError);
  const bcd = own(Codec.number({ encoding: 'bcd', digits: 18 }));
  assert.equal(bcd.decode(bcd.encode(999999999999999999n)), 999999999999999999n);
  fails(() => bcd.decode(hex('1A')), 'digit');
  fails(() => bcd.encode(1000000000000000000n), 'range');
  fails(() => own(Codec.number({ width: 9 })).measure(1n));
  const schemaNumber = own(Codec.schemaNumber({ min_length: 2, max_length: 4, length_multiple: 2 }));
  assert.deepEqual(schemaNumber.encode(1n), hex('0001'));
  assert.deepEqual(schemaNumber.encode(65536n), hex('00010000'));
  fails(() => schemaNumber.decode(hex('01')));
  const endpoints = own(Codec.schemaNumber({ min_length: 2, max_length: 4, endpoints: true }));
  assert.equal(endpoints.measure(65536n), 4);
  fails(() => endpoints.decode(hex('010000')));
  const digits = own(Codec.digits({ width: 4 }));
  assert.deepEqual(digits.encode('00123'), hex('00123FFF'));
  assert.equal(digits.decode(hex('00123FFF')), '00123');
  assert.equal(digits.decode(digits.encode('')), '');
  fails(() => digits.encode('12A'), 'digit');
  fails(() => digits.encode('1\0'), 'digit');
  fails(() => digits.decode(hex('1F2FFFFF')), 'digit');
  const text = own(Codec.text({ width: 6, zero_padding: true }));
  assert.deepEqual(text.encode('A 1'), hex('412031000000'));
  assert.equal(text.decode(text.encode('A 1')), 'A 1');
  fails(() => text.encode('A\0B'), 'text');
  fails(() => text.encode('é'), 'text');
  fails(() => own(Codec.text({ alphabet: 'alnum' })).encode(' '), 'text');
  const raw = own(Codec.builtin('bytes')), input = hex('010203');
  const copy = raw.decode(input); input.fill(0);
  assert.deepEqual(copy, hex('010203'));
  assert.deepEqual(raw.encode(new Uint8Array()), new Uint8Array());
  const ip = own(Codec.builtin('ipv4')), list = own(Codec.builtin('ipv4-list'));
  assert.deepEqual(ip.decode(ip.encode(hex('C0000201'))), hex('C0000201'));
  const addresses = hex('C0000201C6336402');
  assert.deepEqual(list.decode(list.encode(addresses)), addresses);
  assert.deepEqual(list.at(addresses, 1), hex('C6336402'));
  assert.deepEqual(list.encode(new Uint8Array()), new Uint8Array());
  fails(() => ip.decode(hex('010203')), 'length');
  fails(() => list.decode(hex('010203')), 'length');
  fails(() => list.at(addresses, 2));
  assert.throws(() => list.at(addresses, -1), RangeError);
  assert.throws(() => raw.at(addresses, 0), TypeError);

  let called = 0;
  const definition = { rules: [{ tag: hex('04'), min_occurs: 1, max_occurs: 1, min_length: 1, max_length: 1 }] };
  const structure = own(new StructureCodec({ schema: definition,
    decode(data) { ++called; return data[2]; },
    encode(value) { return Writer.encode({ tag: hex('04'), value: Uint8Array.of(value) }); },
  }));
  definition.rules[0].tag[0] = 5;
  assert.deepEqual(structure.encode(7), hex('040107'));
  assert.equal(structure.measure(7), 3);
  assert.equal(structure.decode(hex('040107')), 7);
  fails(() => structure.decode(hex('0402FF')));
  assert.equal(called, 1, 'invalid structures must not invoke the object decoder');
  fails(() => structure.decode(hex('050107')));
  const invalid = own(new StructureCodec({ encode: () => hex('0402FF') }));
  fails(() => invalid.encode(null)); fails(() => invalid.measure(null));
  fails(() => invalid.decode(hex('0400')));
  let guard;
  guard = own(new StructureCodec({ decode(data) {
    assert.throws(() => guard.close()); assert.throws(() => guard.decode(data)); return data;
  } }));
  assert.deepEqual(guard.decode(hex('0400')), hex('0400'));
  const marker = new Error('callback');
  const throwing = own(new StructureCodec({ decode() { throw marker; } }));
  assert.throws(() => throwing.decode(hex('0400')), error => error === marker);
  throwing.close(); throwing.close(); assert.throws(() => throwing.decode(hex('0400')));
  const asyncCodec = own(new StructureCodec({ decode: async data => data }));
  assert.throws(() => asyncCodec.decode(hex('0400')), TypeError);
  const depth = own(new StructureCodec({ max_depth: 0, decode: data => data }));
  fails(() => depth.decode(hex('30020400')));
  const badSchemaOutput = own(new StructureCodec({ schema: { rules: [{ tag: hex('04'), min_occurs: 1 }] }, encode: () => hex('0500') }));
  assert.throws(() => badSchemaOutput.encode(null), error => error instanceof CodecError && error.codec.cause_name === 'schema');

  const candidates = [{ tag: hex('04'), min_value_size: 1, max_value_size: 8 }, { tag: hex('30'), max_value_size: 24 }];
  // Core a9a6f947 tests/unit/generator_test.cpp: CxxFacadeAndZeroDepth.
  // This vector checks binding option transfer against Core's version-2 result.
  const fixed = own(Format.fixed());
  const golden = own(new Generator({ format: fixed, seed: 0n,
    candidates: [{ tag: hex('01'), min_value_size: 0, max_value_size: 10 }],
    max_elements: 1, max_depth: 0, max_value_size: 10, max_case_size: 64 }));
  assert.deepEqual(golden.generate(7n), hex('010A59AE27CB27A684AD9962'));
  for (const tag of [null, new Uint8Array()]) {
    const tagless = own(Format.custom({
      decode(data) { return { tag, header: { offset: 0, size: 1 }, value: { offset: 1, size: data[0] } }; },
      measure(element) { assert.deepEqual(element.tag, tag); return { header: 1, value: element.valueSize }; },
      encode(element) { assert.deepEqual(element.tag, tag); return Uint8Array.of(element.value.length, ...element.value); },
    }));
    const cases = own(new Generator({ format: tagless, candidates: [{ tag, max_value_size: 4 }], max_case_size: 32 }));
    assert.ok(cases.generate().length);
  }
  const generator = own(new Generator({ candidates, seed: maximum, max_depth: 3, max_elements: 16, max_value_size: 24, max_case_size: 128 }));
  assert.equal(generator.version, 2); assert.equal(generator.workspaceSize, 512);
  const first = generator.generate(123n); generator.generate(124n);
  assert.deepEqual(generator.generate(123), first);
  candidates[0].tag.fill(0); candidates.length = 0;
  assert.deepEqual(generator.generate(123n), first);
  const same = own(new Generator({ candidates: [{ tag: hex('04'), min_value_size: 1, max_value_size: 8 }, { tag: hex('30'), max_value_size: 24 }],
    seed: maximum, max_depth: 3, max_elements: 16, max_value_size: 24, max_case_size: 128 }));
  assert.deepEqual(same.generate(123n), first);
  for (const index of [0n, 1n, 127n, maximum]) {
    const wire = generator.generate(index);
    const reader = own(new TreeReader(wire));
    const events = [];
    while (true) { const result = reader.nextEvent(); if (result.status === 'end') break; events.push(result.item); }
    assert.deepEqual(api.TreeWriter.measureEvents(events).bytes, wire);
    reader.close();
  }
  assert.throws(() => generator.generate(-1n), RangeError);
  assert.throws(() => generator.generate(maximum + 1n), RangeError);
  assert.throws(() => new Generator({ candidates: [] }));
  assert.throws(() => new Generator({ candidates: [{ tag: hex('04') }], max_depth: 65 }));
  assert.throws(() => new Generator({ candidates: [{ tag: hex('04') }], max_case_size: 0 }));
  const impossible = own(new Generator({ candidates: [{ tag: hex('04') }], max_case_size: 1, max_value_size: 0 }));
  assert.throws(() => impossible.generate());
  const format = new Format('ber');
  const retained = own(new Generator({ format, candidates: [{ tag: hex('04') }] }));
  format.close(); assert.ok(retained.generate().length);
  let callbackGenerator = null, callbackStructure = null, reject = false;
  const callbackError = new Error('format callback');
  const custom = own(Format.fixed({ isConstructed() {
    if (callbackGenerator) {
      assert.throws(() => callbackGenerator.close());
      assert.throws(() => callbackGenerator.generate());
    }
    if (callbackStructure) assert.throws(() => callbackStructure.close());
    if (reject) throw callbackError;
    return false;
  } }));
  callbackGenerator = own(new Generator({ format: custom, candidates: [{ tag: hex('01') }], max_case_size: 32 }));
  callbackStructure = own(new StructureCodec({ format: custom, decode: data => data, encode: data => data }));
  assert.ok(callbackGenerator.generate().length);
  assert.deepEqual(callbackStructure.decode(hex('0101FF')), hex('0101FF'));
  reject = true;
  assert.throws(() => callbackGenerator.generate(), error => error === callbackError);
  assert.throws(() => callbackStructure.encode(hex('0101FF')), error => error === callbackError);
  reject = false; assert.ok(callbackGenerator.generate().length);
  callbackGenerator = null; callbackStructure = null;
  const closed = own(Codec.text()); closed.close(); closed.close(); assert.throws(() => closed.decode(hex('41')));
  generator.close(); generator.close(); assert.throws(() => generator.generate()); assert.throws(() => generator.workspaceSize);
  // Force memory growth; earlier decoded byte arrays and diagnostics stay detached from WASM.
  const huge = new Uint8Array(20 * 1024 * 1024); huge[huge.length - 1] = 42;
  assert.deepEqual(raw.decode(huge), huge); assert.deepEqual(copy, hex('010203'));
  assert.equal(number.decode(number.encode(maximum)), maximum);
  let diagnostic;
  try { bcd.decode(hex('1A')); } catch (error) { diagnostic = error; }
  bcd.decode(hex('12'));
  assert.equal(diagnostic.codec.reason_name, 'digit');
  assert.equal(diagnostic.codec.reported, diagnostic.code);
  console.log('Generic codecs, structure adapters, Generator and ownership checks passed');
} finally { for (const resource of resources.reverse()) resource.close(); }
