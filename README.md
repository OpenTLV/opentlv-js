# OpenTLV JavaScript / WebAssembly

This repository owns the experimental JavaScript facade and WebAssembly
bridge for [OpenTLV](https://github.com/OpenTLV/opentlv). Parsing, writing,
Document, Query and Schema semantics remain in the canonical C Core.

## Status

The C bridge, JavaScript wrappers, smoke test, Query facade runner and parse
example are migrated from the recorded Core baseline. The standalone CMake
build compiles the selected Core and bridge together with Emscripten, preserving
the original JavaScript API and output names. Build adaptations are recorded in
[MIGRATION.md](MIGRATION.md).
Private local JS/WASM package preparation is available with independent version
metadata and explicit ESM exports. There is no published npm artifact. The private package includes TypeScript
declarations checked with TypeScript 5.9.3. WASM, JavaScript and TypeScript APIs,
private native adapters, examples and documentation belong to this repository.

The behavior-preserving baseline is Core commit
`a9a6f9470c2b285744738b40196bef9d0341fead`, using Emscripten 4.0.10 and Node 22.
See [MIGRATION.md](MIGRATION.md) and the exact
[source inventory](migration/source-inventory.json).

Verify the transferred source files and bridge declarations with Python 3:

```sh
python scripts/verify_migration.py
# Also compare with Git objects from a local Core checkout:
python scripts/verify_migration.py --core-source ../opentlv
```

This checks source parity with the recorded build adaptations, not runtime
compatibility.

## Repository layout

| Path | Responsibility |
| --- | --- |
| `src/` | JavaScript facade and Query ES modules |
| `native/` | C-to-WASM bridge and private Query/Schema adapters |
| `tests/` | Node smoke/package checks and Python infrastructure regressions |
| `tests/query/` | JS facade runner consuming Core-owned fixtures |
| `examples/` | Runnable Node parse example |
| `cmake/` | WASM target, Core selection and immutable dependency pin |
| `scripts/` | Migration verification, CI and private package preparation |
| `packaging/` | Package entry point and packaged README templates |
| `docs/` | Binding build, validation and distribution documentation |
| `migration/` | Immutable source inventory and recorded build adaptations |

The root CMake project includes `cmake/Core.cmake` and `cmake/Wasm.cmake`.
Generated files belong in a separate build directory; the four distributable
files are adjacent in `<build>/dist/`. Since layout normalization (#12), use a
fresh build directory and replace the former `<build>/bindings/wasm/dist/`
argument with `<build>/dist/` in local commands. For example:

```sh
node examples/parse.mjs build-wasm/dist
node tests/smoke.mjs build-wasm/dist
```

Package imports, relative imports within the distributed modules and WASM asset
names are unchanged. The source checkout is not an installable package; use the
[checked private archive](docs/packaging.md). The
[migration map](MIGRATION.md#standalone-layout-12) relates current paths to the
immutable Core inventory.

## Standalone build

The [JS/WASM manual](docs/webassembly.md) contains the preserved JavaScript API,
examples and limitations. [Documentation updates](docs/ci.md#documentation-updates)
describes its integration with the central Docs portal.

Use Emscripten **4.0.10**, Node **22**, CMake **3.24 or newer**, Python **3.9 or
newer**, Git and Ninja. Activate the Emscripten environment and put Node 22 on
`PATH` before configuring:

```sh
emcmake cmake -S . -B build-wasm -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build-wasm --target opentlv-wasm --parallel
ctest --test-dir build-wasm --output-on-failure --no-tests=error
```

The four outputs are in `build-wasm/dist/`:
`opentlv-core.js`, `opentlv-core.wasm`, `opentlv.mjs` and `query.mjs`.
The generated ES module retains the `createOpenTLV` factory and its
web/worker/Node loader flags. CTest runs the existing Node smoke test and parse
example. Set `OPENTLV_NODE_EXECUTABLE` to an explicit Node 22 executable if
needed; `OPENTLV_BUILD_WASM_TESTS=OFF` disables Node test registration.

The default dependency is the exact Git commit in
[cmake/core-source.json](cmake/core-source.json). CMake FetchContent obtains it
without package discovery or a floating branch. Before configuring Core, the
verifier checks the commit, tree, SHA-256 of 215 build inputs and Git version
metadata. It checks the same inputs again before each build. Checksum or
identity failures stop the build. All baseline capabilities are enabled and
Core is linked statically through `OpenTLV::tlv`; prebuilt native libraries are
not accepted as WASM dependencies.

The source checksum is SHA-256 of UTF-8 JSON containing sorted
`[relative_path, file_sha256]` pairs, using compact separators, for
`CMakeLists.txt`, `cmake/` and `tlv/`. Added files in those
directories also change the checksum. `build-wasm/core-selection.json` records
the selected path, commit, tree, checksum, Git version inputs and mode. This is
source provenance, not release attestation.

For explicit sibling development, use a separate build directory:

```sh
emcmake cmake -S . -B build-local -G Ninja \
  -DFETCHCONTENT_SOURCE_DIR_OPENTLV_CORE=../opentlv
cmake --build build-local --target opentlv-wasm --parallel
ctest --test-dir build-local --output-on-failure --no-tests=error
```

The override must be a compatible Core Git checkout and is recorded as
`local-development`, even when its commit matches the pin. Local edits to build
inputs are allowed and recorded with their checksum and dirty status. Changes
after configuration require reconfiguration. A receipt from this mode is not
evidence of the official pinned build. The private adapters in `native/` use
public C headers and are owned here; the selected Core needs no `bindings/` tree.

## Build verification

Run the dependency regression tests with:

```sh
python -B -m unittest discover -s tests -p test_core_dependency.py -v
```

For reproducibility, configure and build again in a fresh `build-wasm-repeat`
directory with the same toolchain and Release configuration. Compare SHA-256
hashes for each of the four output files between the two `dist`
directories. Use independent default pinned builds, not a sibling override.

The Query facade runner remains at `tests/query/wasm_facade.mjs`; it accepts the
output directory and a fixture JSON generated by the selected Core's
`tests/query/facade_fixtures.py`. Query fixtures, oracle and ABI checks remain
Core-owned. [JS/WASM validation](docs/ci.md) documents the PR/Main/Full workflows,
the tag-triggered double-build check and the same local runner:

```sh
python -B -m unittest discover -s tests -v
python -B scripts/ci.py --tier pr
python -B scripts/ci.py --tier full --configuration Debug
python -B scripts/ci.py --tier release
```

Each invocation requires a fresh output directory; use `--output` for a repeat
run. CI consumes and verifies Query fixtures and ABI references from the pinned
Core checkout. It executes Node only, matching the baseline's coverage.
Browser/worker runtime, hosted CI and publication require separate evidence.

CI also publishes an informational [pinned Core API reference report](docs/ci.md#pinned-core-api-reference-report)
with per-header gaps, reviewed exclusions and PR Core-pin changes. It separates
generic Core from Builtins and does not measure functional JS/TypeScript parity.
The [generic API coverage review](docs/webassembly.md#generic-api-coverage-review) maps every generic header
at the exact pin to public operations, binding tests and reviewed exclusions.

The [generic Format and field API](docs/webassembly.md#generic-formats-and-field-encodings)
supports owned Fixed/Variable/Escaped/Packed field configuration, composition,
direct encoding/decoding, size measurement and source preservation. Run
`node examples/fields.mjs <build>/dist` for a composed-format round trip.

The [Reader/Writer API](docs/webassembly.md#reader-writer-and-tree-streams)
adds owned incremental cursors, resumable visitors, balanced tree events,
bounded writers and exact tree measurement. Run
`node examples/streaming.mjs <build>/dist` for an incremental event round trip.

The [Document, Query and Schema API](docs/webassembly.md#document-query-and-structural-schema)
adds owned tree construction and incremental building, contextual queries and edits,
structural validation and copied diagnostics. Run
`node examples/document_schema.mjs <build>/dist` for a create/edit/validate round trip.
The package includes declarations for these APIs and checks installed consumers
in TypeScript NodeNext and Bundler resolution modes.

The [generic Codec and wire Generator API](docs/webassembly.md#generic-codecs-and-wire-generator)
adds integer, BCD, digit, text, byte and IPv4 conversion, Schema-number composition,
validated application-object adapters and deterministic random-access wire cases.
Run `node examples/codecs_generator.mjs <build>/dist` for a BCD and generation example.
The [scalar constraint and tag API](docs/webassembly.md#scalar-constraints-and-tag-operations)
adds Core-backed decoded-value validation, named allowed values and bytewise tag
comparison/hashing, with exact signed 64-bit inputs.

## Private package and version

[package.json](package.json) defines the independent JS version, initially
`0.1.0-dev.0`, with `private: true`. After a default pinned build, put TypeScript 5.9.3 (`tsc`) on `PATH`, then run:

```sh
python -B scripts/package.py --build build-wasm --output build/package-check
```

This stages the four existing outputs, checks a local npm archive and installs
it offline into an isolated Node 22 consumer. Nothing is published. Use the
checked archive rather than installing the source checkout. The package root
adds `packageVersion`; `opentlv-js/version` exposes it without loading WASM.
The existing `(await loadOpenTLV()).version` continues to report the embedded Core
version. Core provenance is recorded separately in `package-info.json`.

See the [packaging guide](docs/packaging.md),
[package API/asset README](packaging/README.md) and
[separate distribution follow-ups](docs/distribution-follow-ups.md). The local
name does not reserve or promise an npm registry name/scope.

## Ownership

`opentlv-js` owns the C-to-WASM bridge, JavaScript wrappers, facade interoperability
tests, examples, standalone build, packaging and binding documentation.
Core owns the native implementation, shared helper headers, Query corpus/oracle
and public ABI snapshots. The Docs portal owns assembly and playground UI;
Workspace owns repository registration and integration smoke coverage.

The original API and four outputs (`opentlv-core.js`, `opentlv-core.wasm`,
`opentlv.mjs`, `query.mjs`) are preserved by the migration. Registry naming,
TypeScript support, toolchain upgrades and API redesign are not part of it.

## Contributing and security

Use the organization's [contribution guidelines](https://github.com/OpenTLV/.github/blob/main/CONTRIBUTING.md),
[Code of Conduct](https://github.com/OpenTLV/.github/blob/main/CODE_OF_CONDUCT.md)
and [security policy](https://github.com/OpenTLV/.github/blob/main/SECURITY.md).
Report suspected vulnerabilities privately through the affected repository's
Security tab; the shared policy documents a fallback when its reporting form is
unavailable. Inheriting the policy does not enable private reporting or scanning.
Community policies and templates stay in `OpenTLV/.github`; this repository
retains JS/WASM build, test, packaging and licensing instructions.

For contributor checks, create a Python **3.10+** virtual environment and run:

```sh
python -m pip install -r requirements-dev.txt
pre-commit install
pre-commit run --all-files --show-diff-on-failure
reuse lint
```

CI runs the same pinned checks. Source migration verification and the runtime
commands above remain required; REUSE alone does not validate build artifacts.
Formatting hooks exclude immutable migration sources, upstream notices and
generated/vendor paths; REUSE still requires their own licensing information.
The preserved API manual is excluded from Markdownlint because it includes a
hash-checked historical section. Add accurate headers to new source files and
use exact REUSE paths for formats without comments. Preserve other contributors'
and third parties' notices and years.

## License

[MIT](LICENSE). Marek Cingel retains copyright in his original contributions;
OpenTLV is the GitHub organization, not a separate legal copyright holder.
See [dependency and artifact attribution](THIRD_PARTY.md) for preserved Core,
Emscripten and runtime notices and the scope of [REUSE metadata](REUSE.toml).
