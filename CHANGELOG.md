# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Changed

- Own the private Query/Schema adapters and remaining WASM guide content; build against Core without its removed `bindings/` tree while retaining immutable migration provenance. (OpenTLV/opentlv#698)
- Normalize the standalone layout into `src/`, `native/`, `tests/`, `examples/` and `cmake/`, with build outputs in `<build>/dist/`; preserve public imports and immutable migration provenance. (#12)

### Added

- Validate migration compatibility by rebuilding the immutable Core baseline in Full/Release CI, comparing emitted WASM/JS contracts and all four output hashes; record cross-repository evidence and remaining acceptance gates. (#14)
- Own the migrated WASM manual and versioned example catalog, with attempt-bound Main documentation notifications and standalone Docs portal integration. (#13)
- Add independent private JS package version metadata, explicit ESM/asset exports, offline archive and installed-consumer checks in every CI tier, package reproducibility and separate distribution follow-up tracking without publishing. (#11)
- Add JS-owned PR/Main/Full CI and tag-triggered double-build reproducibility with pinned Emscripten/Node, preserved smoke/facade checks, verified Core-owned Query/ABI inputs and per-run evidence. (#10)
- Add a standalone Emscripten 4.0.10 build with a pinned, checksum-verified Core dependency, explicit sibling development override and preserved WASM outputs. (#9)
- Import the existing WASM bridge, JavaScript wrappers, tests, parse example and CMake definition from the recorded Core baseline, with repeatable source/API parity verification. (#8)
- Record immutable Core provenance, source mapping and ownership for the behavior-preserving WASM/JavaScript migration. (OpenTLV/opentlv#697)
