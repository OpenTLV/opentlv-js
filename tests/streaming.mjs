// SPDX-License-Identifier: MIT
// Copyright (c) 2026 OpenTLV
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";
const { loadOpenTLV, hexToBytes: hex } = await import(pathToFileURL(resolve(process.argv[2], "opentlv.mjs")).href);
const { Reader, TreeReader, Writer, TreeWriter, Format, Field, StreamError, StreamResult, Visit } = await loadOpenTLV();
const constants = { result: StreamResult };
const keep = [];
const own = value => { keep.push(value); return value; };
const fails = (run, name) => assert.throws(run, e => e instanceof StreamError && e.code === constants.result[name]);
const primitive = { tag: hex("04"), value: hex("CAFE") };
const wire = hex("30060401AA0401BB0401CC");
try {
  assert.deepEqual(Reader.read(Writer.encode(primitive)).item.value, primitive.value);
  const input = hex("0402CAFE0400");
  const reader = own(new Reader(input)); input.fill(0);
  const first = reader.next();
  assert.equal(first.status, "ok");
  assert.deepEqual(first.item.value, primitive.value);
  assert.deepEqual(first.item.source.value, { offset: 2, size: 2 });
  assert.deepEqual(first.item.encoded, hex("0402CAFE"));
  assert.deepEqual(reader.state, { consumed: 4, offset: 4, atEnd: false });
  assert.equal(reader.next().item.value.length, 0);
  assert.equal(reader.next().status, "end");
  assert.equal(reader.next().status, "end");
  reader.reset(hex("0401AA"));
  assert.deepEqual(first.item.value, primitive.value);
  reader.close(); reader.close(); fails(() => reader.next(), "INVALID_STATE");

  const incremental = own(new Reader(hex("0401AA04"), { incremental: true }));
  assert.equal(incremental.next().status, "ok");
  const need = incremental.next();
  assert.equal(need.status, "need-more-data"); assert.equal(need.item, null);
  assert.equal(incremental.state.offset, 3);
  assert.deepEqual(incremental.next(), need);
  fails(() => incremental.setInput(hex("0501BB"), { discard: 3 }), "INVALID_ARG");
  incremental.setInput(hex("0401BB"), { discard: 3 });
  assert.equal(incremental.next().item.offset, 3);
  incremental.setInput(new Uint8Array(), { discard: 3, final: true });
  assert.deepEqual(incremental.state, { consumed: 0, offset: 6, atEnd: true });
  assert.equal(incremental.next().status, "end");
  fails(() => incremental.setInput(hex("0400"), { final: true }), "INVALID_STATE");
  incremental.reset(hex("0401AA0402FF"), { incremental: true });
  incremental.next(); incremental.setInput(hex("0402FF"), { discard: 3, final: true });
  assert.throws(() => incremental.next(), e => e instanceof StreamError &&
    e.code === constants.result.TRUNCATED && e.reader.required === 2 &&
    e.diagnostic.location.domain === "input");
  assert.equal(incremental.state.offset, 3);
  incremental.reset(); assert.equal(incremental.next().status, "end");
  incremental.reset(undefined, { incremental: true });
  assert.equal(incremental.next().status, "need-more-data");

  const huge = own(new Reader(hex("0488FFFFFFFFFFFFFFFF")));
  assert.throws(() => huge.next(), e => e instanceof StreamError &&
    e.reader.declared_length === 0xffffffffffffffffn);
  const malformed = own(new Reader(hex("0480")));
  fails(() => malformed.next(), "INVALID_LENGTH");

  const tree = own(new TreeReader(wire));
  const events = [];
  for (;;) {
    const result = tree.nextEvent(); if (result.status === "end") break;
    assert.equal(result.status, "ok"); events.push(result.item);
  }
  assert.deepEqual(events.map(e => [e.kind, e.depth]), [
    ["begin", 0], ["element", 1], ["element", 1], ["end", 0], ["element", 0],
  ]);
  assert.equal(events[3].tag, undefined);
  assert.equal(tree.state.atEnd, true);
  fails(() => tree.next(), "INVALID_STATE");
  tree.reset(wire); assert.equal(tree.next().item.constructed, true);
  tree.skipSubtree(); assert.deepEqual(tree.next().item.value, hex("CC"));
  fails(() => tree.skipSubtree(), "INVALID_STATE");
  tree.reset(wire); tree.nextEvent(); tree.skipSubtree();
  const skipped = tree.nextEvent().item;
  assert.equal(skipped.kind, "end"); assert.equal(skipped.skipped, true);
  const empty = own(new TreeReader(hex("3000")));
  assert.equal(empty.nextEvent().item.kind, "begin");
  assert.equal(empty.nextEvent().item.kind, "end");
  assert.equal(empty.nextEvent().status, "end");
  const bounded = own(new TreeReader(wire, { frame_capacity: 0 }));
  bounded.next(); fails(() => bounded.next(), "BUFFER_TOO_SHORT");
  bounded.skipSubtree(); assert.deepEqual(bounded.next().item.value, hex("CC"));
  const depthBound = own(new TreeReader(wire, { max_depth: 0 }));
  depthBound.next(); fails(() => depthBound.next(), "LIMIT");
  const countBound = own(new TreeReader(wire, { max_elements: 1 }));
  countBound.next(); fails(() => countBound.next(), "LIMIT");
  const partialTree = own(new TreeReader(wire.slice(0, 5), { incremental: true }));
  assert.equal(partialTree.nextEvent().status, "need-more-data");
  partialTree.setInput(wire.slice(0, 8));
  const parent = partialTree.nextEvent().item;
  assert.equal(parent.kind, "begin"); assert.equal(partialTree.state.consumed, 2);
  partialTree.setInput(wire.slice(2, 8), { discard: 2 });
  assert.equal(partialTree.nextEvent().item.offset, 2);
  partialTree.nextEvent(); assert.equal(partialTree.nextEvent().item.kind, "end");
  assert.equal(partialTree.nextEvent().status, "need-more-data");
  partialTree.setInput(wire.slice(8), { discard: 6, final: true });
  assert.equal(partialTree.nextEvent().item.offset, 8);
  partialTree.close(); assert.deepEqual(parent.value, wire.slice(2, 8));

  const visitor = own(new Reader(hex("0401AA0401BB"), { incremental: true }));
  const visited = [];
  assert.equal(visitor.visit(item => { visited.push(item.value); return Visit.STOP; }).status, "ok");
  assert.equal(visitor.state.offset, 3);
  assert.equal(visitor.visit(item => { visited.push(item.value); return Visit.CONTINUE; }).status, "need-more-data");
  assert.deepEqual(visited, [hex("AA"), hex("BB")]);
  visitor.reset(hex("0401AA0401BB"));
  const marker = new Error("visitor failed");
  assert.throws(() => visitor.visit(() => { throw marker; }), e => e === marker);
  assert.equal(visitor.state.offset, 3); assert.deepEqual(visitor.next().item.value, hex("BB"));
  visitor.reset(hex("0401AA"));
  assert.throws(() => visitor.visit(() => Promise.resolve(Visit.CONTINUE)), TypeError);
  visitor.reset(hex("0401AA"));
  fails(() => visitor.visit(() => { visitor.close(); return Visit.CONTINUE; }), "INVALID_STATE");
  visitor.reset(hex("0401AA"));
  fails(() => visitor.visit(() => Visit.ERROR), "VISITOR");
  tree.reset(wire);
  const preorder = [];
  tree.visit(item => { preorder.push([item.depth, item.offset]); return Visit.CONTINUE; });
  assert.deepEqual(preorder, [[0, 0], [1, 2], [1, 5], [0, 8]]);
  tree.reset(wire); tree.visit(() => Visit.STOP); tree.skipSubtree();
  assert.equal(tree.next().item.offset, 8);

  const writer = own(new Writer({ capacity: 8 }));
  assert.equal(writer.measure(primitive), 4); assert.equal(writer.size, 0);
  writer.write(primitive); assert.equal(writer.size, 4); assert.equal(writer.remaining, 4);
  const snapshot = writer.bytes; snapshot.fill(0);
  assert.deepEqual(writer.bytes, hex("0402CAFE"));
  writer.copyEncoded(hex("0400"));
  fails(() => writer.write(primitive), "BUFFER_TOO_SHORT");
  assert.deepEqual(writer.bytes, hex("0402CAFE0400"));
  assert.throws(() => writer.write({ tag: hex("04") }), TypeError);
  const preserved = own(new Writer());
  const source = own(new Reader(hex("048101AA"))).next().item;
  preserved.preserve(source); assert.deepEqual(preserved.bytes, hex("048101AA"));
  const canonical = own(new Writer()); canonical.write(source);
  assert.deepEqual(canonical.bytes, hex("0401AA"));
  fails(() => preserved.preserve(source, { tag: hex("04"), value: hex("BB") }), "INVALID_ARG");
  assert.deepEqual(preserved.bytes, hex("048101AA"));

  const tw = own(new TreeWriter({ capacity: 32 }));
  const parentTag = hex("30"); tw.begin(parentTag); parentTag.fill(0);
  tw.write({ tag: hex("04"), value: hex("AA") });
  assert.equal(tw.size, 0); assert.deepEqual(tw.bytes, new Uint8Array());
  fails(() => tw.finish(), "INVALID_STATE");
  tw.end(); assert.deepEqual(tw.finish(), hex("30030401AA"));
  fails(() => tw.end(), "INVALID_STATE");
  const transcode = own(new TreeWriter());
  for (const event of events) transcode.writeEvent(event);
  assert.deepEqual(transcode.finish(), wire);
  const malformedEvent = own(new TreeWriter());
  fails(() => malformedEvent.writeEvent({ kind: "end", depth: 0 }), "INVALID_VALUE");
  fails(() => malformedEvent.writeEvent({ ...events[1], depth: 1 }), "INVALID_VALUE");
  malformedEvent.writeEvent(events[0]);
  fails(() => malformedEvent.writeEvent(skipped), "INVALID_VALUE");
  fails(() => own(new TreeWriter({ frame_capacity: 0 })).begin(hex("30")), "BUFFER_TOO_SHORT");
  fails(() => own(new TreeWriter({ tag_capacity: 0 })).begin(hex("30")), "BUFFER_TOO_SHORT");
  const noScratch = own(new TreeWriter({ scratch_capacity: 0 }));
  noScratch.begin(hex("30")); noScratch.write(primitive);
  assert.throws(() => noScratch.end(), e => e instanceof StreamError && e.writer.operation === "end" && e.writer.required === 4);
  fails(() => noScratch.finish(), "INVALID_STATE");
  const exact = TreeWriter.measureEvents(events);
  assert.equal(exact.size, wire.length); assert.deepEqual(exact.bytes, wire);
  const nodes = events.filter(e => e.kind !== "end");
  assert.deepEqual(TreeWriter.measure(nodes).bytes, wire);
  assert.throws(() => TreeWriter.measureEvents(events, { capacity: 1 }), e =>
    e instanceof StreamError && e.requiredData > 1);
  assert.throws(() => TreeWriter.measure(nodes, { scratch_capacity: 0 }), e =>
    e instanceof StreamError && e.requiredScratch > 0);
  fails(() => TreeWriter.measureEvents(events.slice(0, 2)), "INVALID_VALUE");
  assert.deepEqual(TreeWriter.measureEvents([]), { size: 0, bytes: new Uint8Array() });
  // Every split preserves a balanced stream, including splits inside a parent.
  for (let split = 0; split <= wire.length; ++split) {
    const chunks = new TreeReader(wire.slice(0, split), { incremental: true });
    const destination = new TreeWriter();
    try {
      for (;;) {
        const result = chunks.nextEvent();
        if (result.status === "need-more-data") break;
        destination.writeEvent(result.item);
      }
      const discard = chunks.state.consumed;
      chunks.setInput(wire.slice(discard), { discard, final: true });
      for (;;) {
        const result = chunks.nextEvent();
        if (result.status === "end") break;
        destination.writeEvent(result.item);
      }
      assert.deepEqual(destination.finish(), wire);
    } finally { chunks.close(); destination.close(); }
  }

  // Indefinite framing, trailers, and source snapshots survive cursor destruction.
  const indefinite = own(new TreeWriter({ format: "ber-indefinite" }));
  indefinite.begin(hex("30")); indefinite.begin(hex("30")); indefinite.end(); indefinite.end();
  assert.deepEqual(indefinite.finish(), hex("3080308000000000"));
  const ir = own(new TreeReader(indefinite.bytes));
  const ip = ir.nextEvent().item;
  assert.deepEqual(ip.source.trailer, { offset: 6, size: 2 });
  ir.close(); assert.deepEqual(ip.encoded, indefinite.bytes);

  // Retain composed native configuration and JS callbacks after Format.close().
  const id = own(Field.fixedIdentifier()), len = own(Field.fixedLength());
  const composed = own(Format.compose(id, len));
  const cr = own(new Reader(hex("0101AA"), { format: composed }));
  const cw = own(new Writer({ format: composed }));
  id.close(); len.close(); composed.close();
  cw.write(cr.next().item); assert.deepEqual(cw.bytes, hex("0101AA"));
  let active, throwDecode = false, throwEncode = false, grow = false;
  const custom = own(Format.custom({
    decode(data) {
      if (throwDecode) throw marker;
      if (active) fails(() => active.next(), "INVALID_STATE");
      if (grow) { const large = new Writer({ capacity: 24 * 1024 * 1024 }); large.close(); grow = false; }
      if (data.length < 2 || data.length < 2 + data[1]) return { code: constants.result.TRUNCATED };
      return { tag: data.slice(0, 1), header: { offset: 0, size: 2 }, value: { offset: 2, size: data[1] } };
    },
    measure(e) { return { header: 2, value: e.valueSize }; },
    encode(e) { if (throwEncode) throw marker; return Uint8Array.of(...e.tag, e.value.length, ...e.value); },
    isConstructed(tag) { return tag[0] === 0x30; },
  }));
  active = own(new Reader(hex("0402CAFE"), { format: custom }));
  const callbackWriter = own(new TreeWriter({ format: custom })); custom.close();
  throwDecode = true; assert.throws(() => active.next(), e => e === marker);
  assert.equal(active.state.offset, 0); throwDecode = false; grow = true;
  assert.deepEqual(active.next().item.value, primitive.value);
  callbackWriter.begin(hex("30")); callbackWriter.write(primitive); callbackWriter.end();
  assert.deepEqual(callbackWriter.finish(), hex("30040402CAFE"));
  callbackWriter.begin(hex("30")); callbackWriter.write(primitive); throwEncode = true;
  assert.throws(() => callbackWriter.end(), e => e === marker);
  assert.deepEqual(callbackWriter.bytes, hex("30040402CAFE"));
  throwEncode = false; callbackWriter.end();
  assert.deepEqual(callbackWriter.finish(), hex("30040402CAFE30040402CAFE"));
  active.close(); callbackWriter.close();
  const closedWriter = own(new Writer()); closedWriter.close();
  fails(() => closedWriter.write(primitive), "INVALID_STATE");
  assert.throws(() => new Reader("bad"), TypeError);
  assert.throws(() => new Writer({ capacity: -1 }), RangeError);
  assert.throws(() => new TreeReader(wire, { incremental: 1 }), TypeError);
  console.log("Reader/Writer streaming, events, visitors, ownership and diagnostics passed");
} finally { for (const item of keep.reverse()) item.close(); }
