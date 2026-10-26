# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Changed

- Use Ninja provided by the Ubuntu CI runner and verify its availability without refreshing APT package indexes. (#7)
- Own the private Query/Schema adapters and remaining WASM guide content; build against Core without its removed `bindings/` tree while retaining immutable migration provenance. (OpenTLV/opentlv#698)
- Normalize the standalone layout into `src/`, `native/`, `tests/`, `examples/` and `cmake/`, with build outputs in `<build>/dist/`; preserve public imports and immutable migration provenance. (#12)

### Added

- Complete the generic API review with Core-backed scalar ValueConstraint and Tag operations, exact 64-bit inputs, binding/package/type regressions and per-header functional coverage with justified exclusions. (#7)
- Complete generic value and structure Codec APIs, Schema-number composition and deterministic wire Generator with copied diagnostics, exact 64-bit values, TypeScript declarations and binding/package regressions. (#6)
- Complete owned Document construction, insertion, lookup, source locations, encoding and incremental building; add contextual Query evaluation/editing, structural Schema validation with copied reports, TypeScript package declarations and binding/consumer regressions. (#5)
- Expose owned Reader/Writer and tree streaming APIs with incremental windows, resumable visitors, balanced events, bounded output, exact tree measurement, structured diagnostics and binding/package regressions. (#4)
- Expose owned generic field encodings, mixed/tag-only, Variable, Escaped and Packed Format composition, direct decode/measure/encode/preserve operations and binding regressions; retain immutable migration provenance separately from reviewed API additions. (#3)
- Report exact pinned Core API symbol references in CI, with separate generic/Builtins inventories, per-header gaps, justified exclusions and PR Core-pin diffs; keep coverage informational. (#2)
- Validate migration compatibility by rebuilding the immutable Core baseline in Full/Release CI, comparing emitted WASM/JS contracts and all four output hashes; record cross-repository evidence and remaining acceptance gates. (#14)
- Own the migrated WASM manual and versioned example catalog, with attempt-bound Main documentation notifications and standalone Docs portal integration. (#13)
- Add independent private JS package version metadata, explicit ESM/asset exports, offline archive and installed-consumer checks in every CI tier, package reproducibility and separate distribution follow-up tracking without publishing. (#11)
- Add JS-owned PR/Main/Full CI and tag-triggered double-build reproducibility with pinned Emscripten/Node, preserved smoke/facade checks, verified Core-owned Query/ABI inputs and per-run evidence. (#10)
- Add a standalone Emscripten 4.0.10 build with a pinned, checksum-verified Core dependency, explicit sibling development override and preserved WASM outputs. (#9)
- Import the existing WASM bridge, JavaScript wrappers, tests, parse example and CMake definition from the recorded Core baseline, with repeatable source/API parity verification. (#8)
- Record immutable Core provenance, source mapping and ownership for the behavior-preserving WASM/JavaScript migration. (OpenTLV/opentlv#697)
