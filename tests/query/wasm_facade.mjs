// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
const { loadOpenTLV, hexToBytes } = await import(pathToFileURL(resolve(process.argv[2], "opentlv.mjs")));
const api = await loadOpenTLV();
assert.throws(() => api.compileQuery("/"), error => {
  assert.equal(error.location.domain, "expression");
  assert.equal(error.location.kind, "span");
  assert.equal(error.location.begin, 1);
  assert.equal(error.location.end, 1);
  return true;
});
const cases = JSON.parse(await readFile(process.argv[3], "utf8"));
const hex = bytes => Buffer.from(bytes).toString("hex");
function scalar(value) {
  if (typeof value === "boolean") return `bool:${Number(value)}`;
  if (typeof value === "number" || typeof value === "bigint") return `int:${value}`;
  if (typeof value === "string") return `string:${hex(new TextEncoder().encode(value))}`;
  return `bytes:${hex(value)}`;
}
let checks = 0;
for (const fixture of cases) {
  const wire = hexToBytes(fixture.wire);
  for (const optimize of [false, true]) {
    const variables = Object.fromEntries(Object.entries(fixture.variables ?? {}).map(([name, value]) =>
      [name, value.type === "int" ? "integer" : value.type]));
    const options = { optimize, variables,
      names: { "fixture:leaf": hexToBytes("5a"), "fixture:container": hexToBytes("70") } };
    let program;
    try { program = api.compileQuery(fixture.query, options); }
    catch (error) {
      assert.ok(fixture.diagnostic, `${fixture.id}: ${error}`);
      assert.equal(error.code, fixture.diagnostic.code, fixture.id);
      assert.equal(error.query.kind, fixture.diagnostic.kind, fixture.id);
      if (fixture.diagnostic.begin !== undefined) {
        // The expression span is primary, or related evidence beside another location.
        const span = error.location.domain === "expression" ? error.location : error.query.expression;
        assert.equal(span.begin, fixture.diagnostic.begin, fixture.id);
        assert.equal(span.end, fixture.diagnostic.end, fixture.id);
      }
      checks += 1;
      continue;
    }
    assert.equal(fixture.diagnostic, undefined, fixture.id);
    const execution = retained => {
      const query = program.execution({ retained });
      for (const [name, value] of Object.entries(fixture.variables ?? {})) {
        query.bind(name, value.type === "bytes" ? hexToBytes(value.value) : value.value);
      }
      return query;
    };
    const verify = (query, matches) => {
      const actual = program.info.result_kind ? scalar(query.result()) : matches;
      assert.deepEqual(actual, fixture.matches, fixture.id);
      checks += 1;
    };
    try {
      if (program.info.level !== 3) {
        for (const retained of [true, false]) {
          if (!retained && program.info.level > 1) continue;
          for (let split = 0; split <= wire.length; split += 1) {
            const query = execution(retained);
            try {
              const matches = [];
              query.setInput(wire.subarray(0, split), { final: false });
              assert.throws(() => query.visit(match => { matches.push(match.offset); }), error => error.code === 2, fixture.id);
              query.setInput(wire);
              query.visit(match => { matches.push(match.offset); });
              verify(query, matches);
            } finally { query.close(); }
          }
        }
      }
      {
        const document = api.document(wire, { retain_source_locations: true });
        const query = execution(true);
        try {
          const offsets = new Map(), stack = [];
          let node = document.first;
          while (node !== null) {
            offsets.set(node.identity, fixture.offsets[offsets.size]);
            if (node.next !== null) stack.push(node.next);
            node = node.firstChild;
            if (node === null && stack.length) node = stack.pop();
          }
          query.evaluateDocument(document);
          verify(query, program.info.result_kind ? [] : [...query].map(node => offsets.get(node.identity)));
        } finally { query.close(); document.close(); }
      }
    } finally { program.close(); }
  }
}
// Image ownership, continuation, callback failure and stale Document results.
const program = api.compileQuery("//5A");
const loaded = api.loadQuery(program.image());
assert.deepEqual(loaded.evaluate(hexToBytes("5a0101")).map(match => match.offset), [0]);
assert.throws(() => api.loadQuery(program.image().subarray(1)));
const query = loaded.execution({ retained: false });
query.setInput(hexToBytes("5a0101"), { final: false });
const first = query.next();
assert.throws(() => query.next(), error => error.code === 2);
query.setInput(hexToBytes("5a01015a0102"));
query.visit(match => {
  assert.equal(match.offset, 3);
  assert.throws(() => query.close(), error => error.code === 12 && error.query.kind === 12);
  assert.throws(() => query.reset(), error => error.code === 12 && error.query.kind === 12);
  return false;
});
assert.equal(query.next(), null);
query.reset().setInput(hexToBytes("5a00"));
const failure = new Error("callback failure");
assert.throws(() => query.visit(() => { throw failure; }), error => error === failure);
assert.throws(() => query.next(), error => error.code === 12 && error.query.kind === 12);
query.reset().setInput(hexToBytes("5a005a"));
assert.equal(query.exists({ early_return: true }), true);
assert.equal(query.info.full_validation, 0);
assert.throws(() => query.exists(), error => error.code === 3);
assert.deepEqual(first.value, hexToBytes("01"));
program.close(); loaded.close(); query.close();
const selected = api.compileQuery("//5A/preceding-sibling::*");
const document = api.document(hexToBytes("70065a01015a0102"));
const selection = selected.execution().evaluateDocument(document);
const node = selection.next();
assert.deepEqual(node.value, hexToBytes("01"));
node.setValue(hexToBytes("07"));
assert.throws(() => selection.next(), error => error.code === 12 && error.query.kind === 12);
selection.reset().evaluateDocument(document);
assert.deepEqual(selection.next().value, hexToBytes("07"));
document.close();
assert.throws(() => selection.next(), error => error.code === 12 && error.query.kind === 12);
selection.reset(); selection.close(); selected.close();
console.log(`JS/WASM public Query facade: ${cases.length} fixtures, ${checks} backend/window checks passed`);

const metadataSeen = [];
const providers = { num: { id: 101, decode(value, metadata) {
  metadataSeen.push(metadata);
  return BigInt(value[0]) * -10n;
} } };
const custom = api.compileQuery("num(//5A)", { providers });
assert.equal(custom.evaluate(hexToBytes("5a0103")), -30);
assert.equal(metadataSeen.at(-1).offset, 0);
const customImage = custom.image();
assert.throws(() => api.QueryProgram.load(customImage), error => error.code === 7 && error.query.kind === 15);
const customLoaded = api.QueryProgram.load(customImage, { providers });
assert.equal(customLoaded.evaluate(hexToBytes("5a0104")), -40);
const ongoing = custom.execution().setInput(hexToBytes("5a0105"));
custom.close();
ongoing.finish();
assert.equal(ongoing.result(), -50);
ongoing.close(); customLoaded.close();
const textProvider = api.compileQuery("text(//5A)", { providers: {
  text: { id: 102, max_result_bytes: 3, decode: () => "a\0b" },
} });
assert.equal(textProvider.evaluate(hexToBytes("5a00")), "a\0b");
textProvider.close();
const shortProvider = api.compileQuery("text(//5A)", { providers: {
  text: { id: 102, max_result_bytes: 2, decode: () => "a\0b" },
} });
assert.throws(() => shortProvider.evaluate(hexToBytes("5a00")), error => error.code === 14 && error.query.codec_detail.reported === 14 && error.query.codec_detail.operation === 0);
shortProvider.close();
let active;
const reentrant = api.compileQuery("num(//5A)", { providers: {
  num: { id: 103, decode: () => { active.reset(); return 1; } },
} });
active = reentrant.execution().setInput(hexToBytes("5a00"));
assert.throws(() => active.finish(), error => error.code === 12 && error.query.kind === 12);
active.reset(); active.close(); reentrant.close();
const exceptional = api.compileQuery("num(//5A)", { providers: {
  num: { id: 104, decode: () => { throw null; } },
} });
assert.throws(() => exceptional.evaluate(hexToBytes("5a00")), error => error === null);
exceptional.close();
console.log("JS/WASM custom providers: lifetime, image compatibility, bounded results and callback failures passed");
const feedProgram = api.compileQuery("//5A");
const feedExecution = feedProgram.execution({ retained: false });
assert.equal(feedExecution.feed({ kind: "element", tag: hexToBytes("5a"), value: hexToBytes("01") }).offset, 0);
assert.throws(() => feedExecution.setInput(hexToBytes("5a00")), error => error.code === 12 && error.query.kind === 12);
feedExecution.finish();
assert.equal(feedExecution.info.full_validation, 1);
feedExecution.reset();
assert.throws(() => feedExecution.feed({ kind: "end" }), error => error.query.kind === 5);
assert.equal(feedExecution.info.invalid, 1);
feedExecution.reset(); feedExecution.close();
const retainedFeed = feedProgram.execution();
assert.equal(retainedFeed.feed({ kind: "element", tag: hexToBytes("5a"), offset: 7 }), null);
retainedFeed.finish();
assert.equal(retainedFeed.next().offset, 7);
assert.equal(retainedFeed.next(), null);
retainedFeed.close(); feedProgram.close();
console.log("JS/WASM event feeds: immediate/retained publication, malformed events and reset passed");
const editingDocument = api.document(hexToBytes("70065a01015a01025a0103"));
const editingProgram = api.compileQuery("//5A");
const editing = editingProgram.execution().evaluateDocument(editingDocument);
assert.throws(() => editing.editDocument("replace", { value: hexToBytes("09"), target_capacity: 2 }),
  error => error.code === 14 && error.applied === 0 && error.query.kind_name === "storage");
assert.deepEqual(editingDocument.first.firstChild.value, hexToBytes("01"));
assert.equal(editing.editDocument("replace", { value: hexToBytes("09"), target_capacity: 3 }), 3);
assert.throws(() => editing.next(), error => error.code === 12 && error.query.kind === 12);
editing.reset().evaluateDocument(editingDocument);
assert.equal(editing.editDocument("insert_after", { tag: hexToBytes("5b"), value: hexToBytes("04") }), 3);
const ancestorProgram = api.compileQuery("//70 | //5A");
const ancestors = ancestorProgram.execution().evaluateDocument(editingDocument);
assert.equal(ancestors.editDocument("remove"), 2);
assert.deepEqual(editingDocument.first.tag, hexToBytes("5b"));
assert.equal(editingDocument.first.next, null);
ancestors.close(); ancestorProgram.close(); editing.close(); editingProgram.close(); editingDocument.close();
// A rejected constructed replacement keeps the Reader cause of its children.
const readerDocument = api.document(hexToBytes("70035a0101"));
const readerProgram = api.compileQuery("//70");
const readerEdit = readerProgram.execution().evaluateDocument(readerDocument);
assert.throws(() => readerEdit.editDocument("replace", { value: hexToBytes("5a03") }),
  error => error.code === 3 && error.applied === 0 && error.query.kind_name === "reader");
readerEdit.close(); readerProgram.close(); readerDocument.close();
console.log("JS/WASM completed-selection edits: short-capacity retry, replacement, insertion and ancestor dominance passed");

const schemaContext = api.compileQuery("//5A");
const emptyRootProgram = api.compileQuery("value(//70)");
const emptyRootDocument = api.document(hexToBytes("7000"));
const emptyRootExecution = emptyRootProgram.execution({max_depth: 0}).evaluateDocument(emptyRootDocument);
assert.deepEqual(emptyRootExecution.result(), new Uint8Array());
emptyRootExecution.close(); emptyRootProgram.close(); emptyRootDocument.close();
const schemaAssertion = api.compileQuery("num(.) = 1");
const schema = api.querySchema([{ context: schemaContext, assertion: schemaAssertion, name: "one" }]);
schemaContext.close(); schemaAssertion.close();
const goodSchemaInput = hexToBytes("70035a0101");
const badSchemaInput = hexToBytes("70035a0102");
schema.validateBuffer(goodSchemaInput);
let schemaFailure;
assert.throws(() => schema.validateBuffer(badSchemaInput), error => {
  schemaFailure = error;
  return error.rule === 0 && error.schema.kind_name === "assertion";
});
assert.equal(schemaFailure.schema.tag, "5A");
// The Schema part adds only Schema detail; common evidence is the error's own.
assert.deepEqual(Object.keys(schemaFailure.schema).sort(), ["field", "kind", "kind_name", "tag"]);
assert.deepEqual(schemaFailure.query.diagnostic.path, ["70"]);
assert.deepEqual(schemaFailure.location, { domain: "input", kind: "point", begin: 2, end: 2 });
assert.equal(schemaFailure.schema.field, "one");
assert.equal(schemaFailure.query.diagnostic.expected, "contextual Query assertion true");
assert.equal(schemaFailure.query.diagnostic.path_omitted, 0);
let deepSchemaInput = new Uint8Array([0x5a, 1, 2]);
for (let level = 0; level < 35; ++level)
  deepSchemaInput = new Uint8Array([level === 34 ? 0x70 : 0x30, deepSchemaInput.length, ...deepSchemaInput]);
assert.throws(() => schema.validateBuffer(deepSchemaInput), error => {
  assert.deepEqual(error.query.diagnostic.path, ["70", ...Array(31).fill("30")]);
  assert.equal(error.query.diagnostic.path_omitted, 3);
  return error.schema.kind_name === "assertion";
});

assert.throws(() => schema.validateBuffer(goodSchemaInput, { max_contexts: 0 }),
  error => error.query.limit === "schema-contexts" && error.schema === null);
assert.throws(() => schema.validateBuffer(goodSchemaInput, { max_work: 1 }), error => error.query.limit === "work");
const schemaDocument = api.document(goodSchemaInput);
schema.validateDocument(schemaDocument);
const badSchemaDocument = api.document(badSchemaInput);
let documentSchemaFailure;
assert.throws(() => schema.validateDocument(badSchemaDocument), error => {
  documentSchemaFailure = error; return error.location.kind === "unknown";
});
badSchemaDocument.close(); schema.close(); badSchemaInput.fill(0);
assert.deepEqual(documentSchemaFailure.query.diagnostic.path, ["70"]);
assert.equal(schemaFailure.schema.tag, "5A");
const schemaMarker = { reason: "schema provider" };
let schemaProvider, throwSchemaProvider = false;
const schemaProviderContext = api.compileQuery("//5A");
const schemaProviderAssertion = api.compileQuery("num(.) = 1", { providers: { num: {
  id: 201, decode(value, metadata) {
    if (throwSchemaProvider) throw schemaMarker;
    assert.deepEqual(metadata.tag, hexToBytes("5a"));
    assert.throws(() => schemaDocument.close(), error => error.code === 12 && error.query.kind === 12);
    assert.throws(() => schemaDocument.first.erase(), error => error.code === 12 && error.query.kind === 12);
    assert.throws(() => schemaProvider.close(), error => error.code === 12 && error.query.kind === 12);
    assert.throws(() => schemaProvider.validateDocument(schemaDocument), error => error.code === 12 && error.query.kind === 12);
    return value[0];
  },
} } });
schemaProvider = api.querySchema([{ context: schemaProviderContext, assertion: schemaProviderAssertion }]);
schemaProviderContext.close(); schemaProviderAssertion.close();
schemaProvider.validateDocument(schemaDocument);
throwSchemaProvider = true;
assert.throws(() => schemaProvider.validateDocument(schemaDocument), error => error === schemaMarker);
schemaProvider.close(); schemaDocument.close();
const reverseContext = api.compileQuery("//5A[2]");
const reverseAssertion = api.compileQuery("exists(preceding::5A)");
const reverseSchema = api.querySchema([{ context: reverseContext, assertion: reverseAssertion }]);
const siblingInput = hexToBytes("70065a01015a0102");
assert.throws(() => reverseSchema.validateBuffer(siblingInput), error => error.code === 19);
const siblingDocument = api.document(siblingInput);
reverseSchema.validateDocument(siblingDocument);
reverseSchema.close(); reverseContext.close(); reverseAssertion.close(); siblingDocument.close();
console.log("JS/WASM Query Schema: contextual assertions, owned diagnostics, bounded storage and provider guards passed");

// Scoped resolvers snapshot names and the checked two-pass constructor rejects drift.
const namedBytes = hexToBytes("5a");
const definitions = api.definitionResolver({ fixture: [{ name: "leaf", tag: namedBytes }] });
namedBytes[0] = 0;
for (const resolveName of [definitions, api.nameResolver({ "fixture:leaf": hexToBytes("5a") })]) {
  const named = api.compileQuery("//name('fixture','leaf')", { resolve: resolveName });
  assert.equal(named.evaluate(hexToBytes("5a00")).length, 1);
  named.close();
}
assert.throws(() => api.definitionResolver({ a: [{ name: "x", tag: hexToBytes("01") }, { name: "x", tag: hexToBytes("02") }] }), TypeError);
assert.throws(() => api.compileQuery("//name('a','missing')", { resolve: definitions }));
let resolutions = 0;
assert.throws(() => api.compileQuery("//name('a','changing')", {
  resolve: () => Uint8Array.of(++resolutions === 1 ? 0x5a : 0x5b),
}), error => error.code === 7 && error.query.kind === 15);
assert.ok(resolutions >= 2);
const resolverMarker = { resolver: "failed" };
assert.throws(() => api.compileQuery("//name('a','x')", { resolve() { throw resolverMarker; } }), error => error === resolverMarker);
const emvNamed = api.compileQuery("//name('emv','PAN')", { resolve: "emv" });
assert.equal(emvNamed.evaluate(hexToBytes("5a00")).length, 1);
emvNamed.close();
const unqualified = api.compileQuery("//name('','leaf')", { resolve: definitions });
assert.equal(unqualified.evaluate(hexToBytes("5a00")).length, 1);
unqualified.close();
assert.throws(() => api.compileQuery("//name('','x')", { resolve: api.definitionResolver({
  a: [{ name: "x", tag: hexToBytes("01") }], b: [{ name: "x", tag: hexToBytes("02") }],
}) }), error => error.code === 11);

// Optional tag capabilities have stable image identities and owned callback lifetimes.
const fixedFormat = api.Format.fixed({ tag_size: 2, length_size: 2, byte_order: "little", element_order: "ltv", length_scope: "tag-and-value" });
const fixedInput = hexToBytes("0300123407");
const adapter = { id: 311, numberOf: tag => BigInt(tag[0] * 256 + tag[1]) };
const tagged = api.compileQuery("//*[number()=4660]", { format: fixedFormat, tags: adapter });
assert.equal(tagged.evaluate(fixedInput).length, 1);
assert.throws(() => api.compileQuery("//*[class()=1]", { format: fixedFormat, tags: adapter }), error => error.code === 19);
const taggedImage = tagged.image();
assert.throws(() => api.loadQuery(taggedImage, { format: fixedFormat, tags: { ...adapter, id: 312 } }), error => error.code === 7 && error.query.kind === 15);
const taggedLoaded = api.loadQuery(taggedImage, { format: fixedFormat, tags: adapter });
const taggedExecution = taggedLoaded.execution().setInput(fixedInput);
const fixedDocument = api.document(fixedInput, { format: fixedFormat });
assert.deepEqual(fixedDocument.encode(), fixedInput);
fixedFormat.close(); tagged.close(); taggedLoaded.close();
assert.deepEqual(taggedExecution.next().tag, hexToBytes("1234"));
taggedExecution.close(); fixedDocument.close();
let tagExecution;
const tagMarker = { tag: "failed" };
const tagErrors = api.compileQuery("//*[class()=1]", { tags: { id: 313, classOf() {
  assert.throws(() => tagExecution.reset(), error => error.code === 12 && error.query.kind === 12);
  throw tagMarker;
} } });
tagExecution = tagErrors.execution().setInput(hexToBytes("5a00"));
assert.throws(() => tagExecution.next(), error => error === tagMarker);
assert.throws(() => tagExecution.next(), error => error.code === 12 && error.query.kind === 12);
tagExecution.reset(); tagExecution.close(); tagErrors.close();
for (const marker of [null, undefined, new api.QueryError(5)]) {
  const p = api.compileQuery("//*[number()=1]", { tags: { id: 314, numberOf() { throw marker; } } });
  assert.throws(() => p.evaluate(hexToBytes("5a00")), error => error === marker);
  p.close();
}
const wideTagNumber = api.compileQuery("//*[number()=4294967297]", { tags: { id: 315, numberOf: () => 4294967297n } });
assert.equal(wideTagNumber.evaluate(hexToBytes("5a00")).length, 1);
wideTagNumber.close();

for (const [format, input, tag] of [
  ["ber", "5a0107", "5a"], ["der", "040107", "04"], ["cer", "040107", "04"],
  ["ber-indefinite", "70800000", "70"], ["emv", "5a0107", "5a"],
  ["nfc-type2", "030107", "03"], ["lldp", "060107", "03"],
  ["bluetooth-ltv", "025a07", "5a"], ["bluetooth-ad", "025a07", "5a"],
  ["dhcpv4", "5a0107", "5a"],
]) {
  const p = api.compileQuery(`//${tag}`, { format });
  const wire = hexToBytes(input), doc = api.document(wire, { format });
  assert.equal(p.evaluate(wire).length, 1, format);
  try { assert.deepEqual(doc.encode(), wire, format); }
  catch (error) { error.message = `${format}: ${error.message}`; throw error; }
  doc.close(); p.close();
}

// Transformed semantic Tags remain valid after callbacks return and owners close.
let customFormat, customDocument, formatFailure = false;
const formatMarker = { format: "failed" };
customFormat = api.Format.custom({
  decode(input) {
    if (formatFailure) throw formatMarker;
    assert.throws(() => customFormat.close(), error => error.code === 12 && error.query.kind === 12);
    if (input.length < 2 || input.length < input[1] + 2) return { code: 3 };
    return { tag: Uint8Array.of(input[0] ^ 0xff), header: { offset: 0, size: 2 },
      tagRange: { offset: 0, size: 1 }, lengthRange: { offset: 1, size: 1 },
      value: { offset: 2, size: input[1] } };
  },
  measure(element) {
    if (formatFailure) throw formatMarker;
    return { header: 2, value: element.valueSize };
  },
  encode(element) {
    if (customDocument) assert.throws(() => customDocument.close(), error => error.code === 12 && error.query.kind === 12);
    return Uint8Array.of(element.tag[0] ^ 0xff, element.valueSize, ...element.value);
  },
});
const customFormatProgram = api.compileQuery("//5A", { format: customFormat });
const customWire = hexToBytes("a50107");
assert.deepEqual(customFormatProgram.evaluate(customWire)[0].tag, hexToBytes("5a"));
customDocument = api.document(customWire, { format: customFormat });
assert.deepEqual(customDocument.first.tag, hexToBytes("5a"));
assert.deepEqual(customDocument.encode(), customWire);
customDocument.first.setValue(hexToBytes("09"));
assert.deepEqual(customDocument.encode(), hexToBytes("a50109"));
const customAssertion = api.compileQuery("num(.) > 0", { format: customFormat });
const customSchema = api.querySchema([{ context: customFormatProgram, assertion: customAssertion }], { format: customFormat });
customAssertion.close();
customSchema.validateDocument(customDocument);
customSchema.validateBuffer(customWire);
formatFailure = true;
assert.throws(() => customFormatProgram.evaluate(customWire), error => error === formatMarker);
assert.throws(() => customDocument.encode(), error => error === formatMarker);
assert.throws(() => customSchema.validateBuffer(customWire), error => error === formatMarker);
formatFailure = false;
const customFormatExecution = customFormatProgram.execution().setInput(customWire);
customFormat.close(); customFormatProgram.close();
assert.equal(customFormatExecution.next().value[0], 7);
customSchema.validateBuffer(customWire); customSchema.close();
customFormatExecution.close(); customDocument.close(); customDocument = null;
const readOnlyFormat = api.Format.custom({ decode(input) {
  if (!input.length) return { code: 3 };
  return { tag: input.subarray(0, 1), header: { offset: 0, size: 1 }, value: { offset: 1, size: 0 } };
} });
const readOnlyProgram = api.compileQuery("//51", { format: readOnlyFormat });
assert.equal(readOnlyProgram.evaluate(hexToBytes("51")).length, 1);
readOnlyProgram.close(); readOnlyFormat.close();
const nestedFixed = api.Format.fixed({ isConstructed: tag => tag[0] === 0x70 });
const nestedProgram = api.compileQuery("//5A", { format: nestedFixed });
assert.equal(nestedProgram.evaluate(hexToBytes("70025a00")).length, 1);
nestedProgram.close(); nestedFixed.close();

const sourceProgram = api.compileQuery("//5A[@offset=9 and @hlen=2]");
const sourced = sourceProgram.execution({ retained: false });
assert.equal(sourced.feed({ kind: "element", source: hexToBytes("5a0107"), offset: 9 }).offset, 9);
sourced.finish(); sourced.close(); sourceProgram.close();
const ordinalProgram = api.compileQuery("//5A");
const ordinals = ordinalProgram.execution();
ordinals.feed({ kind: "element", tag: hexToBytes("5a"), offset: 0 });
ordinals.feed({ kind: "element", tag: hexToBytes("5a"), offset: 0 });
ordinals.finish();
assert.equal(ordinals.nextOrdinal().ordinal, 0);
assert.equal(ordinals.nextOrdinal().ordinal, 1);
assert.equal(ordinals.nextOrdinal(), null);
ordinals.close(); ordinalProgram.close();
const legacy = new api.V1Query("70/5a");
assert.deepEqual(legacy.steps, [hexToBytes("70"), hexToBytes("5a")]);
const legacyMatcher = legacy.matcher();
assert.equal(legacy.evaluate(hexToBytes("70025a00")).length, 1);
legacy.close();
assert.equal(legacyMatcher.feed(hexToBytes("70"), 0), false);
assert.equal(legacyMatcher.feed(hexToBytes("5a"), 1), true);
legacyMatcher.reset(); legacyMatcher.close();
assert.throws(() => new api.V1Query("70\0/5a"));
assert.throws(() => new api.V1Query("70/5"), error =>
  error.code === 8 && error.query.kind_name === "syntax" && error.location.begin === 3 &&
  error.location.end === 4 && error.query.expression.kind === "unknown");
assert.throws(() => new api.V1Query(Array(66).fill("5a").join("/")), error =>
  error.code === 15 && error.query.kind_name === "limit" && error.location.domain === "expression" &&
  error.query.limit === "path-steps" && error.query.configured === 65);
assert.throws(() => new api.V1Query("5a".repeat(513)), error =>
  error.code === 15 && error.query.kind_name === "limit" && error.query.limit === "path-bytes" &&
  error.query.configured === 512);
const requirements = api.compileQuery("//5A[num(.)=$amount]", { variables: { unused: "bytes", amount: "integer" } });
assert.deepEqual(requirements.variables, { amount: "integer" });
const requiredLoaded = api.loadQuery(requirements.image(), { variables: { amount: "integer" } });
assert.deepEqual(requiredLoaded.variables, requirements.variables);
requiredLoaded.close(); requirements.close();
const diagnosticProgram = api.compileQuery("//5A");
let readerFailure;
assert.throws(() => diagnosticProgram.evaluate(hexToBytes("5a82010200")), error => {
  readerFailure = error; return error.code === 3 && error.query.reader.raw_length === "820102";
});
diagnosticProgram.close();
assert.equal(readerFailure.query.reader.declared_length, 258);
assert.equal(readerFailure.query.reader.tag, "5A");
assert.equal(readerFailure.query.diagnostic.path_omitted, 0);
// Common evidence is emitted once, under query.diagnostic; the result code and
// primary location are the error's own.
assert.equal(readerFailure.query.reader.path_omitted, undefined);
assert.equal(readerFailure.query.diagnostic.location, undefined);
assert.equal(readerFailure.query.diagnostic.code, undefined);
assert.equal(readerFailure.query.kind_name, "reader");
assert.equal(readerFailure.query.reader.operation_name, "value");
assert.equal(readerFailure.message, "truncated input");
assert.throws(() => api.compileQuery("/"), error =>
  error.query.kind_name === "syntax" && error.location.domain === "expression");
let nestedFailureWire = hexToBytes("5a0300");
for (let depth = 0; depth < 35; depth++) {
  nestedFailureWire = Uint8Array.from([0x70, nestedFailureWire.length, ...nestedFailureWire]);
}
const deepFailureProgram = api.compileQuery("//5A");
assert.throws(() => deepFailureProgram.evaluate(nestedFailureWire), error =>
  error.query.diagnostic.has_path === false && error.query.diagnostic.path_omitted === 0 &&
  error.query.diagnostic.severity_name === "error");
deepFailureProgram.close();
console.log("JS/WASM extensions: checked resolvers, Tag adapters, Formats, Source feeds, ordinals and V1 passed");
