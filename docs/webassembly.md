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
Automated runtime evidence covers Node only; web/worker loader flags do not
establish browser or worker runtime validation.

## Package version

The independent JS package version comes from [package.json](../package.json).
The [private package guide](packaging.md) documents `packageVersion` and
`opentlv-js/version`. The existing `(await loadOpenTLV()).version` identifies the
embedded Core, not the JS package. The example catalog records the JS version;
a documentation pin does not establish compatibility with the portal's Core pin.

## Binding contracts and examples

This repository owns WASM, JavaScript and TypeScript integration, including the
private native adapters, API documentation, examples and tests. TypeScript
declarations are not available yet; their addition belongs here. Core owns the
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
`Format.custom(options)` remain available. TypeScript declarations are still a
separate distribution follow-up.

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
