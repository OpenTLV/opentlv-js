// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const { loadOpenTLV, hexToBytes: hex } = await import(pathToFileURL(resolve(process.argv[2], 'opentlv.mjs')));
const api = await loadOpenTLV();
const { Document, Schema, SchemaError, DocumentBuilder, StreamResult: R } = api;
const code = value => error => error.code === value;

const doc = Document.create({ max_elements: 6, retain_source_locations: true });
const root = doc.insert(hex('70'));
const one = doc.insert(hex('5A'), hex('01'), { parent: root });
const two = doc.insert(hex('5A'), hex('02'), { parent: root });
assert.equal(doc.count, 3);
assert.equal(doc.revision, 3n);
assert.equal(doc.retireEpoch, 0n);
assert.equal(doc.find(hex('5A'), root).identity, one.identity);
assert.equal(one.nextSameTag.identity, two.identity);
assert.equal(two.nextSameTag, null);
assert.equal(doc.findPath('70/5A').identity, one.identity);
assert.equal(doc.findPath('71'), null);
assert.deepEqual(one.sourceLocation, { offset: null, headerSize: null });
assert.deepEqual(root.encode(), hex('70065A01015A0102'));
assert.equal(root.encodedSize(), root.encode().length);
assert.equal(doc.encodedSize(), doc.encode().length);
const fixed = api.Format.fixed();
assert.deepEqual(one.encode(fixed), hex('5A0101'));
assert.deepEqual(doc.encodeAs('ber'), doc.encode());
fixed.close();
const foreign = Document.create(); const foreignNode = foreign.insert(hex('5B'));
assert.throws(() => doc.insert(hex('5B'), hex('00'), { parent: foreignNode }), TypeError);
assert.throws(() => doc.insert(hex('5B'), hex('00'), { parent: root, before: root }), code(R.INVALID_ARG));
one.erase(); assert.equal(doc.retireEpoch, 1n);
assert.throws(() => one.encode(), code(R.INVALID_ARG)); assert.throws(() => one.sourceLocation, code(R.INVALID_ARG));
root.setValue(hex('5A0103')); assert.throws(() => two.value);
assert.equal(doc.count, 2);
foreign.close();

const located = new Document(hex('70065A01015B0102'), { retain_source_locations: true });
const child = located.first.firstChild, sibling = child.next;
assert.deepEqual(child.sourceLocation, { offset: 2, headerSize: 2 });
child.setValue(hex('00010203'));
assert.deepEqual(located.first.sourceLocation, { offset: null, headerSize: null });
assert.deepEqual(sibling.sourceLocation, { offset: 5, headerSize: 2 });
assert.throws(() => new Document(hex('70035A0101'), { max_elements: 1 }), code(R.LIMIT));
assert.throws(() => new Document(hex('70035A0101'), { max_depth: 0 }), code(R.LIMIT));

const query = api.compileQuery('//5A');
assert.equal(query.evaluateDocument(located).length, 1);
const contextual = api.compileQuery('./5A');
assert.equal(contextual.evaluateDocument(located, { context: located.first }).length, 1);
assert.throws(() => contextual.evaluateDocument(located, { context: root }), TypeError);
contextual.close();
assert.throws(() => new api.QueryExecution(contextual), code(R.INVALID_STATE));
const execution = query.execution().evaluateDocument(located);
execution.visit(node => {
  assert.throws(() => node.erase(), code(R.INVALID_STATE));
  assert.throws(() => located.close(), code(R.INVALID_STATE));
  assert.throws(() => located.insert(hex('5B')), code(R.INVALID_STATE));
});
execution.reset().evaluateDocument(located);
assert.throws(() => execution.editDocument('replace', { value: hex('09'), target_capacity: 0 }), code(R.BUFFER_TOO_SHORT));
assert.equal(execution.editDocument('replace', { value: hex('09') }), 1);
assert.throws(() => execution.next(), code(R.INVALID_STATE));
assert.equal(query.editDocument(located, 'insert_after', { tag: hex('5C'), value: hex('04') }), 1);
execution.close(); query.close();
const scalar = api.compileQuery('value(//70)');
assert.deepEqual(scalar.evaluateDocument(located), located.first.encode().slice(2));
assert.equal(located.queryValueSize(), 11);
scalar.close();
const manyValues = api.compileQuery('//*');
const valueAssertion = api.compileQuery('value(.) = value(.)');
const deepSchema = api.querySchema([{ context: manyValues, assertion: valueAssertion }]);
const nested = new Document(hex('7008300630045A020102'));
assert.equal(nested.queryValueSize(), nested.encodedSize());
deepSchema.validateDocument(nested);
deepSchema.close(); manyValues.close(); valueAssertion.close(); nested.close();
const invalidated = api.compileQuery('//*'); const stale = invalidated.execution().evaluateDocument(located);
located.close(); assert.throws(() => stale.next(), code(R.INVALID_STATE)); stale.reset(); stale.close(); invalidated.close();

const builder = new DocumentBuilder(hex('5A0101'), { incremental: true, retain_source_locations: true });
assert.equal(builder.consume().status, 'need-more-data');
assert.equal(builder.state.consumed, 3);
builder.setInput(hex('5B0102'), { discard: 3, final: true });
const built = builder.consume(); assert.equal(built.status, 'ok');
assert.equal(built.document.count, 2);
assert.deepEqual(built.document.first.next.sourceLocation, { offset: 3, headerSize: 2 });
assert.throws(() => builder.consume(), code(R.INVALID_STATE)); builder.close(); builder.close();
assert.deepEqual(built.document.encode(), hex('5A01015B0102')); built.document.close();
const failed = new DocumentBuilder(hex('5A02FF'));
assert.throws(() => failed.consume()); assert.throws(() => failed.consume(), code(R.INVALID_STATE)); failed.close();

const rules = [{ tag: hex('5A'), name: 'value', min_length: 1, max_length: 1,
  min_occurs: 1, max_occurs: 1, kind: 'primitive' }];
const schema = new Schema({ rules: [{ tag: hex('70'), kind: 'constructed', min_occurs: 1,
  children: { rules, order: 'sequence' } }] });
rules[0].tag[0] = 0; rules[0].name = 'mutated';
schema.validate(hex('70035A0101'));
assert.deepEqual(schema.validateAll(hex('70035A0101')), []);
assert.equal(schema.find(hex('5A'), 1).name, 'value');
const found = schema.find(hex('5A'), 1); found.tag.fill(0);
assert.deepEqual(schema.find(hex('5A'), 1).tag, hex('5A'));
assert.equal(schema.find(hex('5B'), 1), null);
schema.validateLength(hex('5A'), 1, 1);
assert.throws(() => schema.validateLength(hex('5A'), 2, 1), code(R.SCHEMA));
let failure;
assert.throws(() => schema.validate(hex('7000')), error => {
  failure = error; return error instanceof SchemaError && error.schema.kind_name === 'missing';
});
const snapshot = JSON.stringify(failure);
assert.throws(() => schema.validateAll(hex('70065B01005C0100')), error => {
  assert.ok(error.diagnostics.length >= 2); return error.code === R.SCHEMA;
});
assert.throws(() => schema.validateAll(hex('70065B01005C0100'), { capacity: 0 }));
assert.throws(() => schema.validate(hex('70035A02FF')), error => error.cause === 'reader');
assert.equal(JSON.stringify(failure), snapshot);
assert.throws(() => new Schema({ rules: [{ tag: hex('5A'), min_length: 2, max_length: 1 }] }), SchemaError);
const cycle = { rules: [] }; cycle.rules.push({ tag: hex('70'), kind: 'constructed', children: cycle });
const recursive = new Schema(cycle); recursive.validate(hex('70027000'));
assert.throws(() => recursive.validate(hex('70027000'), { max_depth: 0 })); recursive.close();
const choice = new Schema({ rules: [{ tag: hex('5A'), group: 1 }, { tag: hex('5B'), group: 1 }],
  groups: [{ id: 1, min_occurs: 1, max_occurs: 1, name: 'choice' }] });
choice.validate(hex('5B00')); assert.throws(() => choice.validate(hex('5A005B00')), SchemaError); choice.close();
const sequence = new Schema({ order: 'sequence', rules: [{ tag: hex('5A') }, { tag: hex('5B') }] });
assert.throws(() => sequence.validate(hex('5B005A00')), SchemaError);
sequence.validateAll(hex('5A005C00'), { unknown: 'allow' }); sequence.close();
schema.close(); schema.close(); assert.throws(() => schema.validate(hex('7000')), code(R.INVALID_STATE));

const context = api.compileQuery('//5A'), assertion = api.compileQuery('num(.) = 3');
const qs = api.querySchema([{ context, assertion, name: 'three' }]);
context.close(); assertion.close(); qs.validateDocument(doc);
doc.first.firstChild.setValue(hex('04')); assert.throws(() => qs.validateDocument(doc)); qs.close();
const detached = doc.first; const copy = detached.encode();
// Force memory growth with an owned document; public byte snapshots must survive.
const large = Document.create(); large.insert(hex('5A'), new Uint8Array(32 * 1024 * 1024)); large.close();
assert.deepEqual(copy, hex('70035A0104'));
doc.close(); doc.close(); assert.throws(() => detached.tag, code(R.INVALID_STATE));
// Format callbacks retain their JS closures after the public Format is closed.
let callbackDocument = null, rejectClassification = false;
const sentinel = new Error('classification failed');
const callbackFormat = api.Format.fixed({ isConstructed() {
  if (callbackDocument) assert.throws(() => callbackDocument.close(), code(R.INVALID_STATE));
  if (rejectClassification) throw sentinel;
  return false;
} });
callbackDocument = Document.create({ format: callbackFormat }); callbackFormat.close();
callbackDocument.insert(hex('01'), hex('02'));
rejectClassification = true;
assert.throws(() => callbackDocument.insert(hex('02')), error => error === sentinel);
rejectClassification = false;
callbackDocument.close();
// The Document's writer can use a different Format from the compiled program.
// Its snapshot callbacks must not close the execution before evaluation starts.
let snapshotExecution = null, snapshotCalls = 0;
const snapshotFormat = api.Format.custom({
  decode(input) { return { tag: input.slice(0, 1), header: { offset: 0, size: 2 },
    value: { offset: 2, size: input[1] } }; },
  measure(element) {
    if (snapshotExecution) {
      ++snapshotCalls;
      assert.throws(() => snapshotExecution.close(), code(R.INVALID_STATE));
    }
    return { header: 2, value: element.valueSize };
  },
  encode(element) { return new Uint8Array([element.tag[0], element.valueSize, ...element.value]); },
  isConstructed: tag => tag[0] === 0x70,
});
const snapshotDoc = Document.create({ format: snapshotFormat });
const snapshotRoot = snapshotDoc.insert(hex('70'));
snapshotDoc.insert(hex('5A'), hex('01'), { parent: snapshotRoot });
const snapshotProgram = api.compileQuery('value(//70)');
snapshotExecution = snapshotProgram.execution();
assert.throws(() => snapshotExecution.evaluateDocument(snapshotDoc), code(R.INVALID_ARG));
assert.ok(snapshotCalls > 0);
snapshotExecution.reset();
snapshotExecution.close(); snapshotProgram.close(); snapshotDoc.close(); snapshotFormat.close();
console.log('Document, Query and Schema binding regressions passed');
