# OpenTLV JavaScript / WebAssembly

This repository will own the experimental JavaScript facade and WebAssembly
bridge for [OpenTLV](https://github.com/OpenTLV/opentlv). Parsing, writing,
Document, Query and Schema semantics remain in the canonical C Core.

## Status

This is a migration bootstrap with source provenance and ownership metadata.
It does not yet contain a standalone build, JavaScript package, TypeScript
declarations or published npm artifacts. The working implementation remains in
Core at `bindings/wasm/` until the source-transfer and standalone gates pass.

The behavior-preserving baseline is Core commit
`a9a6f9470c2b285744738b40196bef9d0341fead`, using Emscripten 4.0.10 and Node 22.
See [MIGRATION.md](MIGRATION.md) and the exact
[source inventory](migration/source-inventory.json).

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
