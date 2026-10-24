# OpenTLV JavaScript / WebAssembly

This repository owns the experimental JavaScript facade and WebAssembly
bridge for [OpenTLV](https://github.com/OpenTLV/opentlv). Parsing, writing,
Document, Query and Schema semantics remain in the canonical C Core.

## Status

The C bridge, JavaScript wrappers, smoke test, Query facade runner and parse
example have been transferred byte-for-byte from the recorded Core baseline.
The original CMake file is included for traceability; it still depends on the
Core build and shared helper headers. A standalone build follows in
[#9](https://github.com/OpenTLV/opentlv-js/issues/9).
There is no JavaScript package, TypeScript declaration set or published npm
artifact yet. Core retains its implementation until the standalone gates pass.

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

This checks source parity, not standalone build or runtime compatibility.

## Ownership

`opentlv-js` owns the C-to-WASM bridge, JavaScript wrappers, facade interoperability
tests, examples, standalone build, packaging and binding documentation.
Core owns the native implementation, shared helper headers, Query corpus/oracle
and public ABI snapshots. The Docs portal owns assembly and playground UI;
Workspace owns repository registration and integration smoke coverage.

The original API and four outputs (`opentlv-core.js`, `opentlv-core.wasm`,
`opentlv.mjs`, `query.mjs`) are preserved by the migration. Package naming,
TypeScript support, toolchain upgrades and API redesign are not part of it.

## License

[MIT](LICENSE). Transferred Core sources retain their original Marek Cingel
copyright and license notices alongside the repository's OpenTLV attribution.
