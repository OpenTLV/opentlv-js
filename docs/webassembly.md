# WebAssembly build (experimental)

This manual is owned by `opentlv-js`. The standalone build compiles the selected
OpenTLV C Core to WebAssembly with [Emscripten](https://emscripten.org/).
See the [migration record](../MIGRATION.md) for immutable source provenance.

The module provides parse tooling plus owning compiled Query, checked Document
editing and contextual Query Schema validation. It wraps the existing C API in
`native/opentlv_wasm.c`; no parsing or Query semantics are duplicated.
The EMV dictionary is available as an annotation module (below). Remaining
public-facade gaps are described in [Binding contracts and examples](#binding-contracts-and-examples).

## Build

From the `opentlv-js` checkout, activate Emscripten **4.0.10** and Node **22**,
with CMake **3.24+**, Ninja, Python **3.9+** and Git available, then:

```sh
emcmake cmake -S . -B build-wasm -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build-wasm --target opentlv-wasm
```

The [standalone build contract](../README.md#standalone-build) describes the
checksum-verified Core pin and explicit sibling development override.

The artifacts are written to `build-wasm/dist/`:

| File | Purpose |
| --- | --- |
| `opentlv.mjs` | JavaScript entry point (`loadOpenTLV`, `hexToBytes`) |
| `query.mjs` | Owning compiled Query and checked Document facade |
| `opentlv-core.js` | Generated Emscripten ES module loader |
| `opentlv-core.wasm` | The compiled OpenTLV core |

Serve these files from the same directory. With the same Emscripten version
and configuration the artifacts are byte-for-byte identical; CI builds twice
and compares them. Format options such as `OPENTLV_FORMAT_BER` apply as in
native builds, and disabled formats are unavailable to the facade.

## Use from JavaScript

### Compiled Query and Document

`loadOpenTLV()` also provides `compileQuery(text, options)`, `loadQuery(image,
options)` and `document(input, options)`. Compilation and evaluation delegate to
the native C engine. Query and Document accept `ber`, `ber-indefinite`, `der`,
`cer`, `emv`, `nfc-type2`, `lldp`, `dhcpv4`, `bluetooth-ltv`, `bluetooth-ad` and
`fixed`, or an owning `Format` object. Disabled components report unsupported
type. Query's `bluetooth-ad` alias uses strict element framing; container padding
is handled by the separate parse tooling. Writer restrictions of each native
Format also apply to `document.encode()`.

Programs expose `info`, `format()`, `explain()`, `image()`, `evaluate(input)` and
`execution(limits)`. Declare `variables: { name: "integer" | "bytes" | "string" }`
at compilation; bind values with `execution.bind(name, value)` or the `bindings`
option of `evaluate`. Integer inputs accept safe JS integers or signed 64-bit
`bigint`; results outside the safe integer range return `bigint`. Named Tags can
be supplied as `names: { symbol: Uint8Array }`. `program.variables` reports the
native unique referenced variables, excluding unused declarations.

`resolve(scope, name)` can supply dynamic scoped names, returning a copied
`Uint8Array` or `null` for an unknown identifier. `resolve: "emv"` selects the
native EMV registry. `nameResolver({ "scope:name": tag })` and
`definitionResolver({ scope: [{ name, tag }] })` create immutable lookup snapshots;
an unqualified name must be unique across scopes. Checked compilation rejects
resolver changes between preparation and final compilation, including equal-size
Tag changes. Resolver exceptions preserve their original JavaScript identity.

`tags: { id, classOf?, numberOf? }` supplies optional semantic Tag callbacks.
Callbacks receive copied Tag bytes and return signed 64-bit integers. The
nonzero stable `id` is checked when loading an image; capabilities remain alive
while an execution or schema retains the program.

`Format.fixed({ tag_size, length_size, byte_order, element_order, length_scope,
isConstructed? })` owns the complete native Fixed configuration. Defaults are
one-byte fields, `"big"`, `"tlv"` and `"value"`; alternatives are `"little"`,
`"ltv"` and `"tag-and-value"`. Share the Format object between programs and
Documents using the same configuration. Closing its public handle leaves
existing dependent objects usable.

`Format.custom({ decode, measure?, encode?, isConstructed? })` registers native
Format callbacks with owned lifetimes. `decode(bytes)` receives a copy and returns
`{ tag, header, value, trailer?, tagRange?, lengthRange? }`; each range contains
`{ offset, size }` relative to the supplied bytes. The returned `tag` is a semantic
`Uint8Array`, which may differ from the wire field. Native framing validation
checks the layout. Complete semantic Tags are retained until the Format's final
dependent owner closes. `measure({ tag, value, valueSize })` returns numeric
`{ header, value, trailer? }` sizes, and `encode(element)` returns encoded bytes.
During measurement, `value` may be `null`. Supply both Writer callbacks together
to support Documents; read-only custom Formats support Query execution. Any
callback can report a native failure as `{ code }`, or throw its original
JavaScript exception. Callbacks cannot reenter an object using the same Format.

`providers: { num: { id, decode }, ... }` selects callbacks for the closed `num`,
`bcd`, `text` and `date` conversions. Callbacks receive copied bytes and optional
event metadata; return a signed 64-bit integer or a string for `text`. Text
providers require `max_result_bytes` for bounded native scratch. The owning
program retains callback registrations until all executions and schemas release
them. Callback exceptions propagate and reentry is rejected. Loading an image
requires matching provider IDs and contracts.

`execution.feed(event)` accepts canonical `begin`, `element` and `end` events.
For `begin` and `element`, `source: Uint8Array` supplies the complete encoded
element; the owning Format derives the Tag, Value and Source ranges. Without
`source`, supply copied `tag` and `value` bytes. `offset` stays absolute in either
case. After a retained raw feed is finalized, `nextOrdinal()` returns
`{ ordinal, match }` using traversal identity independently of Source offsets.
`finish()` finalizes deferred results; raw events and Reader input require
separate resets. After evaluating a Document selection,
`editDocument("remove" | "replace" | "insert_after", options)` applies edits with
explicit `target_capacity`. Short target storage reports `error.applied === 0`
and permits retry; partial failures preserve their applied count.

`querySchema([{ context, assertion, name }], { format })` owns references to
compiled context selectors and relative Boolean assertion programs. Its
`validateBuffer` and `validateDocument` methods accept depth/node/work/context
and snapshot limits. Errors own rule, Query and Schema diagnostic context.
Close the schema when finished. Document mutation and close are rejected while
provider callbacks inspect it.

An execution owns its native workspace. `setInput(input, { discard, final })`
copies and retains input windows until `reset()` or `close()`; original source
offsets survive legal continuation. `next()` returns a copied match or `null`
at final exhaustion; needing input raises `QueryError` with the native status.
`visit(callback)` stops when the callback returns `false` and resumes on the next
call. Callback exceptions invalidate the execution until reset; reentrant calls
on that execution are rejected. Scalars use `finish()` then `result()`; `info`
reports native validation and resource coverage. Explicit limits include
`max_depth`, `max_nodes` and `max_work`.
Reader failures preserve copied field offsets, Tag and raw length in
`error.query.reader`; expected/actual text, path and diagnostic context appear
once in `error.query.diagnostic`, shared with any `codec_detail`. The result
code and primary location are `error.code` and `error.location`;
`error.query.expression` is the related expression span when another location
is primary and has kind `unknown` otherwise. A Schema Query failure's
`error.schema` holds only the assertion's `tag`, `field`, `kind` and
`kind_name`, and is `null` for any other failure.

`new V1Query("70/5A")` exposes bounded legacy parsing, `format()`, copied `steps`,
`evaluate(input, options)` and a native preorder matcher. `matcher()` creates an
independent owner; feed every Tag and depth with `feed(tag, depth)`, and call
`reset()` before starting a new traversal. An independent matcher remains valid
after the original Query closes.

`evaluateDocument(document, { value_capacity })` evaluates the canonical Document
backend. Results are checked Nodes with `tag`, `value`, `constructed`,
`firstChild`, `next`, `parent`, `setValue(bytes)` and `erase()`. Constructed Nodes
return `null` for `value`. Document edits invalidate previous Query selections;
erased and closed handles raise `QueryError`. Call `close()` on executions,
programs and Documents for deterministic release. Native executions retain their
program and Document owners, while the public facade rejects access after a
Document is closed.

### Parse tooling

```js
import { loadOpenTLV, hexToBytes } from "./opentlv.mjs";

const opentlv = await loadOpenTLV();
const result = opentlv.parse(
  hexToBytes("6F 0A 84 03 41 42 43 A5 03 50 01 01"),
  { format: "ber" },
);
```

`parse` takes a `Uint8Array`, a `format` (`fixed`, `bluetooth-ltv`, `bluetooth-ad`,
`ber`, `der`, `cer` or `emv`; default `ber`) and optionally a `module` (`none` or `emv`; default
`none`) and returns:

Bluetooth modes annotate known AD Types with `name` from the C registry.
`bluetooth-ltv` keeps strict element framing. `bluetooth-ad` adds Advertising
Data container semantics: validated trailing zeros are reported separately as
`padding: { offset, length }`. Nonzero padding is an error at its original
source offset. Neither mode validates schemas or decodes value payloads.

For `format: "fixed"`, `fixedTagSize` (default `1`), `fixedLengthSize` (1-8, default
`1`) and `fixedByteOrder` (`"big"` or `"little"`, default `"big"`) configure the
configurable fixed-width format's tag width, length width and length byte order
(`tlv_fixed_format_t`). `fixedElementOrder` selects `"tlv"` (default) or `"ltv"`;
`fixedLengthScope` selects `"value"` (default) or `"tag-and-value"`.
These options apply only to Fixed. Invalid JavaScript configuration values throw
`TypeError`; invalid encoded input is reported through `result.error`.
`opentlv.formats` and `opentlv.modules` list the modes supported by the loaded build.

```json
{
  "format": "ber",
  "elements": [
    {
      "offset": 0, "depth": 0, "tag": "6F", "length": 10, "headerSize": 2, "constructed": true,
      "children": [
        { "offset": 2, "depth": 1, "tag": "84", "length": 3, "headerSize": 2, "constructed": false, "value": "414243" },
        { "offset": 7, "depth": 1, "tag": "A5", "length": 3, "headerSize": 2, "constructed": true,
          "children": [
            { "offset": 9, "depth": 2, "tag": "50", "length": 1, "headerSize": 2, "constructed": false, "value": "01" }
          ] }
      ]
    }
  ]
}
```

Tags and values are uppercase hexadecimal. Only BER, DER, CER and EMV elements can be
constructed; the other formats return flat elements with opaque values. An
element occupies `encodedSize` bytes from `offset`, including any trailer.
`source` contains absolute `{offset, length}` ranges for `header`, `tag`,
`length`, `value` and `trailer`; empty regions have length zero. The logical
Value excludes the enclosing trailer. Field order comes from these ranges,
so LTV and BER end-of-contents need no wire-framing guessing in the viewer.
The JSON example above omits `encodedSize` and `source` for brevity.

`format: "cer"` uses the generic tree visitor with `tlv_format_cer`, preserving
preorder output and EOC source ranges. It checks framing only; full CER
validation (including string segmentation and semantic values) is not applied.

With `module: "emv"` (BER or EMV framing; other formats report an invalid-argument
error) the result also has `"module": "emv"`. Every element the
[EMV dictionary](https://github.com/OpenTLV/opentlv/blob/main/docs/standards/emv/README.md) knows carries `symbol` (the
dictionary name), `name` (a display name) and `lengthValid` (whether `length`
is permitted for the tag); other elements carry none of these.

Invalid input does not throw. The result carries an `error` object with the
numeric `code` of `tlv_result_t`, its `message` and the input `offset`, together
with every element read before the failure:

```json
{ "format": "ber", "elements": [ ... ],
  "error": { "code": 3, "message": "truncated input", "offset": 5 } }
```

`parse` throws only for programming errors (a non-`Uint8Array` argument) or
when memory runs out. Input is processed entirely in the browser. A single
call reads at most 65,536 elements and 64 levels of nesting.

## Documentation playground

The [TLV playground](https://github.com/OpenTLV/opentlv-docs/blob/main/docs/playground/index.md)
is owned by the Docs portal. Its `docs/playground/playground.js` calls `parse`
once and renders the result as tree, hex and JSON views, with no parsing logic
of its own; the JSON view serializes the parse result itself.

JS owns this module's standalone CMake target and smoke tests. The portal's
existing playground builder still consumes its selected Core WASM target;
documentation source integration does not switch that binary producer.
The portal verifies all four distribution files and `wasm-source.json` before
embedding them. Bare CMake output is not a verified portal distribution.
See the [portal build contract](https://github.com/OpenTLV/opentlv-docs/blob/main/README.md#playground-builds).

After a successful official `JS Main CI`, a separate notifier proposes an exact
JS documentation pin. See [documentation updates](ci.md#documentation-updates)
for credentials, validation, retry and the Docs #93 handoff. This notification
does not publish a package, a component release or the playground.

## Testing

[`tests/smoke.mjs`](../tests/smoke.mjs) runs the module in Node 22 and is
registered with CTest unless `OPENTLV_BUILD_WASM_TESTS=OFF`:

```sh
ctest --test-dir build-wasm -L wasm --output-on-failure --no-tests=error
```

The unchanged [Node parse example](../examples/parse.mjs) traverses a nested
BER document and checks its four elements:

```sh
node examples/parse.mjs build-wasm/dist
```

The [CI guide](ci.md) describes Query facade, ABI and private-package checks.
Runtime suites execute in Node only. Package checks also load the installed
archive in headless Chrome as a module page and module worker, covering WASM
loading, parsing and Document encoding; other browsers and bundlers are not
established.

## Package version

The independent JS package version comes from [package.json](../package.json).
The [private package guide](packaging.md) documents `packageVersion` and
`@opentlv/opentlv/version`. The existing `(await loadOpenTLV()).version` identifies the
embedded Core, not the JS package. The example catalog records the JS version;
a documentation pin does not establish compatibility with the portal's Core pin.

## Binding contracts and examples

This repository owns WASM, JavaScript and TypeScript integration, including the
private native adapters, API documentation, examples and tests. TypeScript
declarations are included by #5 in the checked private package. Core owns the
public C execution contracts and canonical Query fixtures/ABI snapshots.

### Native adapters and capabilities

`native/path_query.h` translates bounded V1 path failures to Query diagnostics.
`native/query_schema.h` owns temporary workspace for the public Query Schema
validator. Both are private binding adapters; parsing and validation semantics
remain in Core. The build consumes public C headers through `OpenTLV::tlv` and
does not require a Core `bindings/` directory.

The facade includes parse-to-JSON tooling and owning compiled Query/Document
operations. Query supports configured/custom Formats, semantic Tag adapters,
scoped/Definition/EMV resolvers, NUM/BCD/TEXT/DATE conversion callbacks, contextual
Schema validation, selection edits, source events, ordinals and bounded V1 path
queries. General Reader/Writer parity and deterministic wire generation are not
exposed. Native C capability availability alone does not establish JS coverage.

Document options accept `retain_source_locations`; unretained or invalidated
source properties produce Query SOURCE diagnostics. Semantic visitor records do
not expose raw Length. The parse presentation adapter has its own 64-level
output capacity, separate from native Reader/Schema workspace limits.

`QueryError` carries the C message, structured `location` and owned Query
evidence. `query.kind_name`, Reader `operation_name` and Codec names accompany
numeric categories. Common evidence appears once in `query.diagnostic`.

### Format selection and LLDP example

The `lldp` and `nfc-type2` formats appear in the loaded instance's `formats` only
when compiled in. Neither interprets NDEF or adds an implicit NFC Terminator
stop. Parse tooling does not add a general writing API; Document encoding has
the selected native Format's writer restrictions.

```javascript
// After loadOpenTLV() resolves to opentlv:
const result = opentlv.parse(new Uint8Array([6, 2, 0, 120]), { format: "lldp" });
console.assert(result.elements[0].tag === "03");
```

The `emv` Format selects definite framing. The `emv` annotation module supplies
definitions for display independently of framing: using it with `ber` does not
enforce EMV framing. Module selection does not load `.otlv` files or require a
runtime interpreter.

The earlier `profile` JSON field and parse option are now `module`;
`PROFILES` and `api.profiles` became `MODULES` and `api.modules`. The old names
have no compatibility aliases.

### Executable example coverage

[examples/parse.mjs](../examples/parse.mjs) demonstrates nested BER parsing and
traversal through the supported JavaScript loader. [examples/fields.mjs](../examples/fields.mjs)
demonstrates a composed-format round trip. There are no dedicated
Writer, construction, Document, Query, Schema or Codec
example programs yet. This is example coverage, not a claim that those APIs all
lack implementations.

After an Emscripten build, run the Node example explicitly, or run CTest with
`OPENTLV_BUILD_WASM_TESTS=ON`; building WASM alone does not prove execution.
The smoke test, Query facade regressions and wasm32 ABI check are owned by this
repository's [CI](ci.md), consuming the selected Core's shared fixtures and ABI
contract. A future iterable Reader must follow JavaScript iteration/error
conventions while preserving the public C execution semantics.

## Generic formats and field encodings

Available after `loadOpenTLV()` as `Field`, `Format` and `FormatError`. These
operations use public Core headers at pinned commit
`a9a6f9470c2b285744738b40196bef9d0341fead`; JavaScript marshals inputs and owns
native allocations. Core validates configuration, interprets fields and performs
framing. The existing named formats, `Format.fixed(options)` and
`Format.custom(options)` remain available. Issue #5 adds package declarations;
field composition option objects remain structurally open.

```javascript
const { Field, Format } = await loadOpenTLV();
const identifier = Field.fixedIdentifier(1);
const length = Field.variableLength({ policy: { require_minimal: true } });
let format;
try {
  format = Format.compose(identifier, length);
  identifier.close(); length.close(); // format owns independent native references
  const wire = format.encode({ tag: hexToBytes("42"), value: hexToBytes("AABB") });
  const decoded = format.decode(wire);
  console.log(decoded.tag, decoded.value, decoded.source);
} finally { format?.close(); identifier.close(); length.close(); }
```

### Field factories and operations

| Factory | Configuration |
| --- | --- |
| `Field.fixedIdentifier(size = 1)` | Nonzero raw identifier width |
| `Field.fixedLength(size = 1, byte_order = "big")` | Count width 1–8, `big` or `little` |
| `Field.variableIdentifier(options)` | `inline_mask=31`, `escape=31`, `continuation_bit=128`, `payload_mask=127`, `max_size=16`, optional `policy` |
| `Field.variableLength(options)` | `long_form_bit=128`, `payload_mask=127`, `byte_order="big"`, optional `policy` |
| `Field.escapedLength(options)` | `escape=255`, `extended_size=2`, `byte_order="big"`, `min_extended=255`, `max_length=65535` |
| `Field.packed(options)` | `storage_size=1`, `bit_offset=0`, `bit_width=8`, `byte_order="big"` |

Identifier policy accepts `forbidden_leading: Uint8Array`,
`reject_zero_first_payload: boolean` and `require_minimal: boolean` (both default
false). Length policy accepts `allow_short=true`, `allow_long=true`,
`require_minimal=false`, `max_long_octets=8` and `max_value=2^64-1`.
Omitting a policy selects Core's unconstrained encoding; an explicit policy is
snapshotted, including its byte table.

`field.read(bytes)` returns `{tag: Uint8Array, consumed}` for identifiers and
`{value, consumed}` for counts/packed fields. `field.encode(tagBytes)` validates
and copies an identifier; `field.encode(count)` creates encoded count bytes.
For a packed field, `field.encode(count, storageBytes)` returns a modified copy
of storage, preserving other bits and leaving the caller's input unchanged.
Packed tags and length fields in a Format must both use its `header_size` as
their `storage_size`.

Counts accept safe integer Numbers or unsigned 64-bit BigInts. Numeric results
are Numbers when safe and BigInts otherwise. JS checks scalar representation,
byte-array types and wasm32 allocation sizes; Core checks encoding constraints.
Invalid configuration and wire input raise `FormatError` with the Core `code`.
Field read failures also report Core's `consumed` prefix (Packed has no partial
consumption and reports zero on failure). Type/representation
errors raise `TypeError` or `RangeError` before entering WASM.

### Composition and Format operations

| Factory | Inputs |
| --- | --- |
| `Format.compose(identifier, length, options)` | Two live Fields; identifier must be Fixed/Variable, length Fixed/Variable/Escaped |
| `Format.variable(options)` | `identifier` and `length` configuration objects for Variable fields |
| `Format.escaped(options)` | `tag_size=1` and an Escaped `length` configuration object |
| `Format.packed(options)` | `header_size`, `tag_size`, `tag_storage: Uint8Array`, Packed `tag` and `length` configuration objects |

Composition options are `element_order: "tlv" | "ltv"` (default `tlv`),
`length_scope: "value" | "tag-and-value"` (default `value`) and optional
`constructed: {byte_index, mask, value}`. Mixed and Escaped compositions also
accept `tag_only: Uint8Array[]`; these tags have no length/value on the wire.
Variable and Packed reject nonempty tag-only tables. Packed requires `tlv`
order: its fields share the header. Its tag-storage entry `i` must contain the
big-endian representation of `i`, with all `2^tag.bit_width` entries present.
The binding copies this table; Core checks layout capacity at construction and
canonical table entries when decoding. An `isConstructed(tag)` callback is also
supported as with existing Formats and overrides the declarative predicate.

All Formats expose:

- `canRead`, `canWrite`: descriptor capabilities.
- `decode(bytes)`: one element as `{tag, value, encodedSize, constructed, source}`.
  Tag/value bytes are copies; absent tags are `null`, explicit empty tags remain
  empty arrays. Source has `header`, `tag`, `length`, `value`, `trailer` ranges
  `{offset, size}` relative to this input, or `null` for absent fields. Trailing
  elements are not consumed. Empty input raises `FormatError` with Core's `END`.
- `measure({tag, value})`: logical `{header, value, trailer, total}` sizes. For
  content-independent Core formats, omit value bytes and pass `valueSize`
  instead. Counts retain all 64 bits even when the wire would exceed wasm32.
  Existing custom callback arguments are wasm32-sized; larger custom size-only
  requests raise `RangeError` before a callback can receive a truncated value.
- `encode({tag, value})`: newly allocated canonical bytes. Both tag and value
  use `Uint8Array` (an absent tag can be `null`). If supplied, `valueSize` must
  equal the supplied value's byte count.
- `preserve(sourceBytes, {tag, value})`: decode the original first element and
  invoke Core source preservation after comparing its semantic content.
  Nonminimal accepted framing survives; changed content fails. This operation
  re-decodes input using the live Format, so custom callbacks execute again.

Format failures include `.format` with Core's region, optional offset and
required extent, and partial tag/length/value ranges. Custom callback exceptions
are rethrown unchanged. No operation retains caller input buffers or returns
WASM heap views. Close Fields and Formats explicitly; `close()` is idempotent
and operations on closed handles fail. A composition retains its Fields;
Query and Document retain their Format even after its public handle closes.
Callback functions stay alive until all dependent objects close. Reentrant
Format operations and closing a Format during its callback are rejected.

Run `node tests/format_fields.mjs <build>/dist` or CTest for binding tests covering
configuration copies, errors, 64-bit marshalling, packed/tag-only layouts, source
preservation, heap growth and dependent lifetimes. The same tests and runnable
example execute against the installed private package in CI. Builtins parity,
general Reader/Writer APIs and TypeScript declarations are outside #3.

## Reader, Writer and tree streams

Issue #4 adds `Reader`, `TreeReader`, `Writer`, `TreeWriter`, `StreamError`,
`StreamResult` and `Visit` to the object returned by `loadOpenTLV()`. These are
JavaScript APIs, with package declarations added in #5.
All parsing, traversal, encoding and wire validation runs in the pinned C Core.

```js
const { Reader, TreeReader, Writer, TreeWriter, Visit } = await loadOpenTLV();
const reader = new Reader(new Uint8Array([4, 2]), { incremental: true });
try {
  console.log(reader.next().status); // "need-more-data"
  reader.setInput(new Uint8Array([4, 2, 0xCA, 0xFE]), { final: true });
  const { item } = reader.next();
  console.log(Writer.encode(item)); // Uint8Array [4, 2, 202, 254]
  console.log(reader.next().status); // "end"
} finally { reader.close(); }
```

### Ownership and failures

Every cursor owns its native buffers and retains its Format, including composed
fields and JS callbacks. Input, tags and output returned to JavaScript are copies.
They remain valid after input replacement, cursor advancement, `close()` or WASM
memory growth. `close()` is idempotent and releases native storage; call it in
`finally`. Closing the public Format handle does not invalidate existing cursors.
There is no implicit finalizer or I/O. Avoid sharing a cursor across concurrent
operations; callbacks must be synchronous. Reentry and closing the active cursor
or using its Format from inside a Format callback fail with `INVALID_STATE`.

Native failures throw `StreamError` with Core's numeric `code`; compare it with
the frozen `StreamResult` constants. When available, `diagnostic` contains
severity, location, path and contexts, and `reader` or `writer` contains operation
and required/available sizes. Reader logical lengths exceeding the safe integer
range are `bigint`. Coordinates and capacities are bounded by wasm32. Type and
representation failures throw `TypeError` or `RangeError`. Original callback
exceptions are rethrown unchanged, including non-Error thrown values.

### Reader and incremental input

`new Reader(bytes, {format = "ber", incremental = false})` accepts a format name
or a live `Format` from the same loaded module. `Reader.read(bytes, options)`
performs one pull and closes its temporary cursor.

- `next()` returns `{status, code, item, consumed, offset, atEnd}`. Status is
  `"ok"`, `"end"` or `"need-more-data"`; the latter two have `item: null`.
  Need-more-data can also carry Reader diagnostics. An item has copied `tag`
  (`Uint8Array` or `null`), `value`, `encoded`, absolute `offset`, and `source`
  ranges (`header`, `tag`, `length`, `value`, `trailer`). Each present range is
  `{offset, size}` relative to `item.encoded`; absent ranges are `null`.
- `state` returns `{consumed, offset, atEnd}` without decoding. `consumed` is the
  discardable prefix of the current input window; `offset` is absolute.
- `setInput(bytes, {discard = 0, final = false})` replaces the contiguous window.
  Preserve all old bytes after `discard`, then append new bytes. The binding
  verifies prefix identity before calling Core. Only consumed bytes can be
  discarded. Finalized input cannot be extended or reopened.
- `reset(bytes = new Uint8Array(), {incremental = false})` abandons the current
  input/traversal and starts at absolute offset zero, retaining Format and limits.

Only successful pulls advance. Incomplete non-final input yields need-more-data;
the same incomplete final input throws `TRUNCATED`. No partial element is exposed
and no bytes are buffered beyond the explicitly supplied window. A failed input
replacement leaves the old window intact.

### Tree Reader and visitors

`new TreeReader(bytes, options)` adds `frame_capacity=64`, `max_depth=64` and
`max_elements=65536`. These are independent runtime limits; zero is allowed.
Roots have depth zero. `next()` returns preorder nodes with `depth` and
`constructed`, hiding closing events. `nextEvent()` instead returns nodes with
`kind: "begin" | "element" | "end"`, `depth`, `offset` and `skipped`. An END
has no tag/value/source payload. Empty containers produce BEGIN then END.
Choose one projection per reset; mixing node/visitor and event pulls is rejected.

`skipSubtree()` omits descendants of the last nonempty constructed item. In event
mode it schedules an END with `skipped: true`. Descendants are not validated or
counted. Parent publication waits for the complete encoded parent; this API does
not emit early headers. Known END events precede need-more-data. Frame exhaustion
and depth/count limits leave pending descent available for skipping or retry.

`Reader.visit(callback)` and `TreeReader.visit(callback)` consume remaining nodes
through Core's visitor adapters. The callback receives copied tag/value bytes;
tree callbacks also receive depth and absolute offset. Return `Visit.CONTINUE`,
`Visit.STOP` or `Visit.ERROR` explicitly. Promises and other returns are rejected.
The return value contains `status: "ok"` for stop/final exhaustion or
`"need-more-data"` for incomplete input. ERROR throws `StreamError` with
`StreamResult.VISITOR`. The current node has already been consumed when the
callback runs, including when it stops or throws; a later visit resumes at the
next node. After stopping on a parent, resumption visits children unless skipped.
Do not mutate the cursor from its callback.

### Writer and bounded tree output

`new Writer({format = "ber", capacity = 65536})` owns fixed output storage:

- `write({tag, value})` appends a canonical semantic element, including a complete
  constructed value. `Writer.encode(element, options)` is the one-shot equivalent.
- `measure(element)` calls Core's content-aware measurement without advancing.
  For size-only logical measurement, use `Format.measure({tag, valueSize})`.
- `copyEncoded(bytes)` appends bytes without validating them.
- `preserve(source, element = source)` accepts a Reader item with `encoded` bytes,
  re-decodes its first element using this Writer's Format and asks Core to compare
  semantic content before copying the original framing. Custom decoders run again.
  Caller-supplied JS source ranges are ignored; source bytes must use the Writer's
  format. Semantic changes fail rather than silently re-encoding.
- `size`, `remaining` and `bytes` expose the written size, remaining capacity and
  a fresh copy of output. Errors preserve the cursor and previously written prefix.

`new TreeWriter(options)` adds `frame_capacity=64`, `max_depth=64`,
`max_elements=65536`, `scratch_capacity=65536` and `tag_capacity=4096`:

- `begin(tag)` copies an open constructed identifier into bounded tag storage;
  `write(element)` appends a complete child; `end()` closes the innermost parent.
- `writeEvent(event)` consumes the canonical TreeReader event shape. It checks
  ordering, depth and destination classification. Skipped END events are rejected.
  BEGIN's source value is ignored; children are rebuilt from later events.
- `finish()` checks balanced closure and returns a copy of the output. It does
  not seal the writer. `bytes` and `size` expose only completed root elements;
  `remaining` accounts for provisional children as well.
- `measure(element)` measures one complete element without advancing.

Output, frames, scratch and open-tag storage never grow implicitly. An `end()`
failure retains the open parent and accumulated bytes, including callback
failure. Scratch must fit the largest closed value. Use a new writer with larger
explicit capacities and replay input when storage is insufficient. There is no
header patching or format-specific encoding in the binding. Format capabilities
still apply: for example, the pinned `ber-indefinite` descriptor writes only
constructed elements, while the ordinary BER reader accepts indefinite sources.

`TreeWriter.measure(nodes, options)` accepts an array of preorder
`{tag, value, depth, constructed}` items; constructed values are ignored.
`TreeWriter.measureEvents(events, options)` accepts a balanced event array.
Both call the corresponding Core measurement helper once with explicit bounded
workspace and return `{size, bytes}` containing the exact staged encoding.
They call both measure and encode callbacks. On storage failure, `StreamError`
adds `requiredData` and `requiredScratch`: lower bounds for replay, not a promise
of final capacity. No automatic callback replay occurs.

Run `node examples/streaming.mjs <build>/dist` for an incremental event round trip.
`tests/streaming.mjs` covers every chunk split, visitor stop/resume and errors,
limits, prefix validation, balanced events, preservation, measurement, rollback,
retained formats, copied results and memory growth. CTest and private-package
checks run these tests and the example. See the [coverage inventory](ci.md#readerwriter-inventory-4)
for pinned symbols and equivalent C entry points. Browser/worker execution and
TypeScript runtime integration beyond the installed consumer checks requires its own validation.

## Document, Query and structural Schema

The post-migration #5 API uses Core
`a9a6f9470c2b285744738b40196bef9d0341fead`. It adds owning document construction,
incremental materialization and structural validation. All tree, Query and
Schema semantics execute in Core. See the
[symbol inventory and exclusions](ci.md#documentqueryschema-inventory-5).

```js
const { Document, Schema, compileQuery } = await loadOpenTLV();
const document = Document.create({ max_depth: 16, max_elements: 100 });
const query = compileQuery('//5A');
const schema = new Schema({ rules: [
  { tag: hexToBytes('5A'), min_occurs: 1, max_occurs: 1,
    min_length: 1, max_length: 1, kind: 'primitive', name: 'value' },
] });
try {
  document.insert(hexToBytes('5A'), hexToBytes('01'));
  query.editDocument(document, 'replace', { value: hexToBytes('02') });
  schema.validate(document.encode());
} finally {
  schema.close(); query.close(); document.close();
}
```

Run `node examples/document_schema.mjs <build>/dist` for the complete example.

### Owned Documents and Nodes

`new Document(bytes, options)` copies and parses input; `Document.create(options)`
creates an empty tree. Both accept `format`, `max_depth` (default 64),
`max_elements` (65536) and `retain_source_locations` (false).

| Operation | Result |
| --- | --- |
| `document.insert(tag, value, { parent, before })` | New owned Node; null parent means a root, null before appends |
| `document.find(tag, parent)` | First matching direct child, or null |
| `document.findPath('70/5A')` | First V1 path match, or null; this is the legacy path grammar |
| `document.count`, `revision`, `retireEpoch` | Node count and exact `bigint` mutation/retirement counters |
| `node.nextSameTag` | Following sibling with the same tag, or null |
| `node.sourceLocation` | Copied `{ offset, headerSize }`, each nullable |
| `document.encodedSize(format?)`, `node.encodedSize(format?)` | Exact native encoded size |
| `document.encodeAs(format)`, `node.encode(format?)` | Copied canonical encoding; optional alternate Format |
| `document.queryValueSize(max_depth?)` | Native constructed-value staging requirement for compiled Query |

Existing `first`, `firstChild`, `next`, `parent`, `tag`, `value`, `constructed`,
`setValue`, `erase` and `document.encode()` remain available. Encoding normalizes
wire spelling; source locations refer to the original input, not new output.
Edits invalidate affected locations; unchanged siblings retain their coordinates.
Inserted nodes have no original source location.

Nodes belong to one loaded module and Document. Foreign Nodes are rejected before
native access; erased nodes and descendants of replaced constructed values fail
identity checks before dereference. Closing a Document invalidates its JS Nodes
and selections, even when native execution storage retains it until reset/close.
Bytes and diagnostic strings are copied before native buffers are reused or freed.

### Incremental DocumentBuilder

`new DocumentBuilder(input, options)` owns an internal TreeReader and accepts
Document options plus `incremental` and `frame_capacity`. `consume()` returns
`{ status: 'need-more-data', document: null }` or transfers a complete Document
as `{ status: 'ok', document }`. Replace input with
`setInput(bytes, { discard, final })`, retaining the undiscarded prefix exactly.
`state` exposes the reader's consumed count and offset. Completion and terminal
errors prohibit further consumption; `close()` releases the builder and reader.
The transferred Document remains usable after builder closure.

The builder materializes a whole owned input stream. Borrowing an external
TreeReader or selecting its last published subtree is not exposed; this avoids
sharing a mutable native cursor across two public owners. This is a deliberate
surface restriction despite references to all three native builder functions.

### Query evaluation and edits

`program.evaluateDocument(document, options)` returns copied scalars or live Node
handles. `execution.evaluateDocument(document, { context, value_capacity })`
accepts an optional Node from that Document as the contextual root. Convenience
evaluation/editing also accepts variable `bindings` and execution limits.

`program.editDocument(document, kind, options)` evaluates a fresh selection and
applies `remove`, `replace` or `insert_after`. The existing execution method allows
explicit control of selection and `target_capacity`. Insufficient target storage
preserves the selection for retry. Successful edits invalidate the execution's
revision. Native partial-application failures retain `QueryError.applied`.
No automatic rollback is promised for allocation or user callback failures.

Default constructed-value storage is measured from the current Document as one
complete canonical encoded snapshot. It no longer depends on the original input size.
An explicit `value_capacity` remains a hard bound. Query Schema validation
continues to allocate a current encoded snapshot when its capacity is omitted.

Synchronous visit callbacks can stop with `false`. They cannot close or mutate
the active Document or execution. Provider and Format callback exceptions retain
their original JS identity. Reset an execution after a failed visitor/provider;
do not reuse a failed builder. Native limits, diagnostics and revision checks
remain authoritative.

### Structural Schema

`new Schema(definition, { format })` copies tags, names, rules and groups into
native-owned storage, then prepares/checks the complete definition. Mutation of
the original JS objects has no effect. Shared and recursive table objects are
supported, with at most 256 distinct tables and native validation depth limits.

A table has `rules`, `allow_unknown` (false), `order` (`any` or `sequence`) and
optional `groups`. A rule contains a byte `tag`, optional `name`, inclusive
`min_length`/`max_length` (0/4294967295), `length_multiple` (0 disables),
`endpoints` (false), `min_occurs`/`max_occurs` (0/1), `kind`
(`any`, `primitive` or `constructed`), optional `children` table and `group` ID.
A group has `id`, optional `name`, and occurrence bounds (0/1 by default).
Use 4294967295 for an unrestricted wasm32 upper bound. Group member rules must
have `min_occurs: 0`; Core checks definition consistency.

`validate(bytes, { max_depth, max_elements })` returns normally on success or
throws `SchemaError`. `validateAll(bytes, { capacity, unknown, ...limits })`
collects up to `capacity` diagnostics (default 64), still throwing on violations
or terminal failures. The error owns `diagnostics`, a terminal `diagnostic`,
`cause`, and Schema or Reader detail. A full/zero-capacity report does not imply
validation succeeded. Unknown policy is `schema` (default), `allow` or `reject`.
Reports retain path/location and occurrence/length/kind/definition evidence after
later validation or schema closure.

`find(tag, tableIndex = 0)` returns a copied length entry or null;
`validateLength(tag, length, tableIndex = 0)` validates length without wire parsing.
Table indices follow first-encounter depth-first order, root zero. `QuerySchema`
continues to provide contextual Query assertions for buffers and Documents.
Structural Schema validates encoded buffers; use `schema.validate(document.encode())`
when validation of the current canonical Document representation is desired.
Its locations then refer to that encoding, not the original parsed input.

### TypeScript declarations

The private package ships `.d.mts` declarations for the root, facade, Query and
version entry points, using matching
[ES module declarations](https://www.typescriptlang.org/docs/handbook/modules/theory.html).
Runtime constructors are properties of the object returned by `loadOpenTLV()`;
interfaces such as `Document`, `Node`, `QueryProgram` and `SchemaTable` are type-only
exports. TypeScript 5.9.3 strict consumer checks cover NodeNext and Bundler module
resolution, positive calls and rejected argument types. This is not a bundler or
browser runtime test. Existing Format/streaming types are included; generic
field-composition option objects remain structurally open.

The four existing runtime output names are unchanged. Two declaration files are
also copied beside the build outputs; the checked package adds root/version
declarations and explicit `types` exports. Install the checked private archive,
not the source checkout. All owned objects still require explicit `close()`.

## Generic codecs and wire Generator

Issue #6 adds the Core generic conversion and Generator surfaces. Obtain their
constructors from `await loadOpenTLV()`. Every factory returns an object with
idempotent `close()`; operations after closing fail. Codec configuration and
Generator candidate tags are copied at construction, and returned byte arrays
are independent copies. Callers never retain pointers into growable WASM memory.

### Value codecs

All codecs provide `decode(bytes)`, `encode(value, { capacity? })` and
`measure(value)`. `measure` validates through Core and returns the exact encoded
byte count. Encode allocates that size by default; an explicit smaller capacity
produces a Core buffer error. A capacity of `0xffffffff` selects automatic sizing.

| Factory | JS representation and policy |
| --- | --- |
| `Codec.builtin('uint8')` | Number, 0 through 255 |
| `Codec.builtin('uint16-be' / 'uint16-le')` | Number, unsigned 16-bit |
| `Codec.builtin('uint32-be' / 'uint32-le')` | Number, unsigned 32-bit |
| `Codec.builtin('int64-minimal-be')` | BigInt, minimal signed two's-complement bytes |
| `Codec.builtin('bytes')` | Copied `Uint8Array`, including empty values |
| `Codec.builtin('ipv4')` | Four network-order octets as `Uint8Array` |
| `Codec.builtin('ipv4-list')` | Concatenated network-order octets; `at(bytes, index)` copies one address |
| `Codec.number({ encoding, width, digits })` | BigInt, unsigned 64-bit binary or packed numeric BCD |
| `Codec.digits({ width })` | String, preserving leading zeros and using trailing F padding |
| `Codec.text({ alphabet, width, zero_padding })` | String, explicitly printable ASCII or alphanumeric ASCII |
| `Codec.schemaNumber(options)` | BigInt, numeric representation composed with field-length constraints |

Integer encoders accept a `bigint` or safe integer `number` and reject out-of-range
values before transfer. All 64-bit decoders return `bigint`, including small
values. Number encoding is `big` (default), `little` or `bcd`. Width zero means
minimal encoding; binary widths are 1–8 bytes and BCD widths 1–9 bytes. BCD requires
`digits` in 1–18; binary requires zero digits. Core validates representation
configuration on use. Numeric BCD does not imply decimal scaling.

Digits width zero means minimal packing; a positive width pads with F nibbles.
Text alphabet is `printable` (default) or `alnum`; width zero is variable length.
With a positive width, `zero_padding: true` pads/strips trailing zero bytes;
without padding the text must occupy the entire width. Embedded NUL, non-ASCII
and disallowed characters fail in Core.

Schema-number options add `min_length` (default 0), `max_length` (default
`0xffffffff`), `length_multiple` (default 0) and `endpoints` (default false).
Width zero chooses the shortest schema-permitted representation that fits.
A fixed width must satisfy the constraints and is never silently widened.
These are copied field constraints; this adapter performs no tag lookup.

```js
const { Codec } = await loadOpenTLV();
const amount = Codec.schemaNumber({
  encoding: 'bcd', digits: 12, min_length: 6, max_length: 6,
});
try {
  const wire = amount.encode(12345n); // 00 00 00 01 23 45
  console.log(amount.decode(wire)); // 12345n
} finally { amount.close(); }
```

Core conversion failures throw `CodecError` with `code`, copied `diagnostic`
(including location) and `codec` (operation, reported result, reason, violation,
representation and delegated Reader/Schema evidence). Invalid JS types/ranges
throw `TypeError`/`RangeError`; closed or reentrant operations throw `QueryError`.
No partial output is returned after an error. Borrowed C descriptors, native
application layouts and raw value-codec function pointers are not exposed.

### Structure object adapters

`new StructureCodec({ format = 'ber', schema?, max_depth = 64,
max_elements = 65536, decode?, encode? })` maps complete TLV sequences to
application objects. It retains its Format and snapshots/prepares an optional
`SchemaTable`. Caller-owned Formats can be closed after construction.

The synchronous `decode(bytes)` callback receives copied bytes only after Core
validates the entire sequence, nesting, limits and optional Schema. The
`encode(object)` callback returns a `Uint8Array`, which is copied and validated
by `tlv_structure_encode` before it is returned. Compose existing Reader/Writer,
Document and value codecs inside these callbacks to define the object mapping.
Missing directions fail as unsupported; thrown callback values propagate
unchanged. Promise results and reentrant use/close are rejected. A callback may
use other independent objects. Callbacks should not mutate shared Format state.

```js
const { StructureCodec, Writer } = await loadOpenTLV();
const codec = new StructureCodec({
  schema: { rules: [{ tag: Uint8Array.of(4), min_occurs: 1,
    max_occurs: 1, min_length: 1, max_length: 1 }] },
  decode: bytes => ({ id: bytes[2] }),
  encode: object => Writer.encode({
    tag: Uint8Array.of(4), value: Uint8Array.of(object.id),
  }),
});
try { console.log(codec.decode(codec.encode({ id: 7 }))); }
finally { codec.close(); }
```

`measure(object)` encodes and validates once and returns the byte count; unlike
the raw C size query, it allocates complete output and catches invalid framing
and Schema violations. Explicit output capacity is supported by `encode`.
JS callbacks define object mapping; Core retains all wire and validation rules.

### Deterministic wire generation

`new Generator({ format = 'ber', candidates, seed = 0n, max_elements = 64,
max_depth = 8, max_value_size = 256, max_case_size = 4096 })` owns a snapshot
of the ordered candidate table and retains the Format. A candidate is
`{ tag, min_value_size = 0, max_value_size }`; its maximum defaults to the global
maximum. Tags are `Uint8Array`, or `null` for an absent identifier; an empty
array is an explicitly present empty tag. Format decides whether an identifier
is constructed. Only use independently composable candidates; exclude stream
terminators and context-dependent ordering.

Custom Format decode callbacks may return `tag: null`; their measure/encode
callbacks receive the same absent-versus-empty distinction. The Format must
round-trip candidate tag presence as well as its bytes.

`generate(case_index = 0n)` returns one nonempty stream. Seed and index accept
safe integer numbers or unsigned 64-bit BigInts. The same algorithm version,
Format configuration, ordered candidates, bounds, seed and index produce the
same bytes, independent of call history. `version` reports the Core algorithm
version (2 at this pin), and `workspaceSize` reports the required native scratch
bytes. Storage is allocated per operation and released even on error. Format
callbacks must be deterministic. Core validates limits and rejects impossible
cases; errors preserve their result code and Format callback exceptions.

```js
const { Generator } = await loadOpenTLV();
const cases = new Generator({ seed: 42n,
  candidates: [{ tag: Uint8Array.of(4), max_value_size: 16 }],
  max_case_size: 128,
});
try { console.log(cases.generate(7n)); }
finally { cases.close(); }
```

Generation delegates to the canonical Core Writer and verifies byte-exact
Reader/Writer reconstruction. Primitive contents are arbitrary bytes: this API
does not generate Schema-valid or Codec-valid application values. Builtins
parity, broader browser/worker coverage and publication remain separate work.

## Scalar constraints and tag operations

`ValueConstraint.none()`, `ValueConstraint.range(min, max)` and
`ValueConstraint.allowed([{ value, name? }, ...])` construct checked snapshots
of a decoded scalar constraint. Bounds and values accept safe integer numbers
or signed 64-bit BigInts, including both endpoints. Use a Codec to decode wire
bytes first; a constraint does not infer an encoding or enforce byte lengths.

`validate(value)` returns `undefined` on success and throws `ConstraintError`
with Core's `code` and message on rejection (`StreamResult.SCHEMA`). Reversed
bounds fail construction with `StreamResult.INVALID_SCHEMA`. `name(value)`
returns the first matching allowed value's name, or `null` for an unnamed,
absent, range or unconstrained value. Empty names are preserved. Names are
NUL-free strings; duplicate values retain Core's first-match behavior. An empty
allowed set rejects every value. This API returns scalar result codes; it does
not manufacture wire locations or structural Schema diagnostics.

Configuration changes after construction have no effect. `close()` is
idempotent; subsequent operations throw `QueryError` with `INVALID_STATE`.
JS type errors and out-of-int64 values throw `TypeError` or `RangeError` before
native transfer. No C pointer survives an operation, and temporary WASM storage
is released on both success and failure.

```js
const { Codec, ValueConstraint } = await loadOpenTLV();
const codec = Codec.builtin('int64-minimal-be');
const constraint = ValueConstraint.allowed([{ value: 7n, name: 'ready' }]);
try {
  const value = codec.decode(Uint8Array.of(7));
  constraint.validate(value);
  console.log(constraint.name(value)); // ready
} finally { constraint.close(); codec.close(); }
```

`Tag.compare(left, right)` compares `Uint8Array` contents lexicographically as
unsigned bytes and returns `-1`, `0` or `1`. Prefixes sort before longer tags.
`Tag.equal(left, right)` tests byte equality, including empty tags.
`Tag.hash(bytes)` returns Core's unsigned wasm32 hash. Equal byte sequences
hash equally; the hash may change across versions, platforms and builds and
must never be persisted or transmitted. These operations do not interpret tag
bytes or validate their Format. They accept subarrays, leave inputs unchanged
and return no borrowed memory.

Run `node tests/generic.mjs <build>/dist` for constraint/tag tests and examples
of composing Codec and ValueConstraint with Query providers and scoped name
resolution. See the [coverage review](#generic-api-coverage-review) for the native adapter
representation differences and remaining intentional exclusions.

## Generic API coverage review

Issue #7 reviews the immutable Core commit
`a9a6f9470c2b285744738b40196bef9d0341fead`. The before/after inventory is
192/197 referenced, 47/0 unclassified and 58/100 excluded generic `TLV_API`
symbols (297 total). Five new references back public ValueConstraint and Tag
operations. The other 42 were reviewed individually and classified as
representation or convenience exclusions. Builtins coverage is unchanged and
outside this review; the official pinned build still enables all components.

The table below covers every generic header with `TLV_API` declarations at this
pin. R means referenced in production native sources, E means explicitly
excluded, and G means unclassified gap. These lexical counts do not establish
functional parity, reachable operations or exhaustive behavior coverage.
Macros, inline helpers, generated configuration/version declarations and C++
interfaces are outside this source-header inventory. The runtime Core version
is available through `api.version`; native configuration queries do not change
the official all-components build contract.

Functional groups name the usable JS surfaces and binding-owned test files,
not a claim that every referenced C branch or excluded C function is tested:

| Group | Public behavior | Binding tests under `tests/` |
| --- | --- | --- |
| fields | Field and Format factories, decode/measure/encode/preserve | `format_fields.mjs` |
| stream | Reader, TreeReader, Writer, TreeWriter; copied diagnostics | `streaming.mjs` |
| document | Document, Node, DocumentBuilder, Schema, QuerySchema | `document_schema.mjs` |
| query | QueryProgram, QueryExecution, V1Query; images, callbacks and diagnostics | `query/wasm_facade.mjs` |
| codec | Codec, StructureCodec, Generator; copied codec diagnostics | `codecs_generator.mjs` |
| generic | ValueConstraint, Tag and Codec/Query composition | `generic.mjs` |

| Pinned header | R | E | G | Functional group |
| --- | ---: | ---: | ---: | --- |
| `tlv/codec/codec.h` | 2 | 0 | 0 | codec |
| `tlv/codec/diagnostic.h` | 5 | 0 | 0 | codec |
| `tlv/codec/digits.h` | 2 | 0 | 0 | codec |
| `tlv/codec/ipv4.h` | 3 | 0 | 0 | codec |
| `tlv/codec/number.h` | 2 | 0 | 0 | codec |
| `tlv/codec/structure.h` | 2 | 0 | 0 | codec |
| `tlv/codec/text.h` | 2 | 0 | 0 | codec |
| `tlv/codec/values.h` | 7 | 0 | 0 | codec |
| `tlv/copy.h` | 0 | 3 | 0 | stream |
| `tlv/definition.h` | 1 | 0 | 0 | document |
| `tlv/diagnostic.h` | 5 | 9 | 0 | stream |
| `tlv/document/document.h` | 37 | 4 | 0 | document |
| `tlv/endian.h` | 0 | 15 | 0 | codec |
| `tlv/field/escaped.h` | 2 | 0 | 0 | fields |
| `tlv/field/fixed.h` | 4 | 0 | 0 | fields |
| `tlv/field/packed.h` | 2 | 0 | 0 | fields |
| `tlv/field/variable.h` | 4 | 0 | 0 | fields |
| `tlv/format.h` | 8 | 0 | 0 | fields |
| `tlv/formats/compose.h` | 2 | 13 | 0 | fields |
| `tlv/formats/escaped.h` | 1 | 3 | 0 | fields |
| `tlv/formats/fixed.h` | 1 | 0 | 0 | fields |
| `tlv/formats/packed.h` | 4 | 0 | 0 | fields |
| `tlv/formats/variable.h` | 2 | 4 | 0 | fields |
| `tlv/generator.h` | 2 | 0 | 0 | codec |
| `tlv/query/adapters.h` | 1 | 2 | 0 | generic |
| `tlv/query/plan.h` | 0 | 2 | 0 | query |
| `tlv/query/program.h` | 28 | 3 | 0 | query |
| `tlv/query/query.h` | 6 | 4 | 0 | query |
| `tlv/reader/diagnostic.h` | 1 | 0 | 0 | stream |
| `tlv/reader/reader.h` | 10 | 3 | 0 | stream |
| `tlv/reader/tree.h` | 9 | 2 | 0 | stream |
| `tlv/reader/visitor.h` | 2 | 1 | 0 | stream |
| `tlv/result.h` | 1 | 0 | 0 | stream |
| `tlv/schema/constraint.h` | 3 | 0 | 0 | generic |
| `tlv/schema/detail.h` | 2 | 0 | 0 | document |
| `tlv/schema/number.h` | 2 | 0 | 0 | codec |
| `tlv/schema/query.h` | 3 | 0 | 0 | document |
| `tlv/schema/schema.h` | 7 | 3 | 0 | document |
| `tlv/size.h` | 1 | 3 | 0 | codec |
| `tlv/tag.h` | 2 | 3 | 0 | generic |
| `tlv/value.h` | 0 | 7 | 0 | codec |
| `tlv/writer/tree.h` | 10 | 4 | 0 | stream |
| `tlv/writer/writer.h` | 9 | 12 | 0 | stream |

### Reviewed exclusions and representation boundaries

The exact symbol lists and reasons live in
[`cmake/api-coverage.json`](../cmake/api-coverage.json). The generated report
expands them per symbol and header. No broad new header wildcard or artificial
symbol reference is used to hide later Core additions. Regenerate it with:

```sh
python -B scripts/api_coverage.py --core ../opentlv \
  --output build/api-coverage/report.json
```

- Copy, tag and value storage use `Uint8Array`. `slice()` copies owned bytes;
  `subarray()` intentionally shares JS storage. `length` supplies the size,
  and `Tag.compare/equal` compare raw bytes for either tags or values. Core
  native pointer validity, borrowed spans, overlap/capacity copy interfaces and
  raw C ownership are not public JS interfaces. Writer handles canonical
  serialization and validated source preservation separately.
- Endian load/store helpers are represented by `Codec.number` with explicit
  `big`/`little` encoding and widths 1 through 8, plus fixed integer codecs.
  Exact `bigint` values avoid JS precision loss. Unchecked C loads/stores and
  native host byte order have no separate wire-facing operation. JS sizes are
  validated as wasm32 integers; logical wire sizes and uint64 values use exact
  Core operations and bigint where needed.
- Diagnostic producer APIs mutate linked C context/path storage or enrich
  locations. JS receives copied result codes, locations, paths, Reader details,
  Query causes, Schema reports and Codec diagnostics instead. Native diagnostic
  editing/formatting is intentionally excluded; applications can attach their
  own presentation records without exposing WASM pointers.
- `definitionResolver` snapshots explicit namespaces and labels; ambiguity
  and unknown-name handling are tested. Query providers compose `Codec.decode`
  with application policy, optional ValueConstraint validation, stable
  capability IDs and bounded text output. Keep callback-owned codecs open
  until their programs/executions are finished. A closed codec fails safely;
  unsigned results beyond signed int64 are rejected. UTF-8 text decoding is
  strict. Native registry/codec/scratch adapters are not exposed verbatim:
  callback exceptions (including the original `CodecError`) propagate rather
  than synthesizing native adapter statuses and diagnostic nesting.
- Previous reviewed aliases retain their published contracts: diagnostic
  Reader/Writer/Schema variants; element-based writing; explicit-format Node
  encoding; length-bounded V1 parsing; owned Query compilation, reset and
  visitation; descriptor callbacks invoked through Format; and validated owned
  Query images instead of borrowed relocatable plan pointers.

### Functional validation boundary

CTest runs the binding suites; `scripts/package.py` repeats the generic suite
against the offline installed archive and checks positive/negative TypeScript
consumers in NodeNext and Bundler modes. `tests/generic.mjs` covers signed-int64
endpoints, invalid definitions and values, names and duplicates, configuration
snapshots, empty sets, close behavior, memory growth, byte ordering/hashing and
Codec/constraint/Query composition with failure propagation. The other suites
exercise framing, streams, documents, schemas, images, ownership and callbacks.
Core-owned Query fixtures and ABI checks remain separate inputs to CI.

Coverage reports stay informational: future pin changes must be reviewed, and
zero unclassified symbols does not remove the representation boundaries above.
Local Node and type checks do not prove browser/worker execution, hosted CI,
publication or release attestation. Builtins parity and performance work remain
separate follow-ups.
