# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- Add independent private JS package version metadata, explicit ESM/asset exports, offline archive and installed-consumer checks in every CI tier, package reproducibility and separate distribution follow-up tracking without publishing. (#11)
- Add JS-owned PR/Main/Full CI and tag-triggered double-build reproducibility with pinned Emscripten/Node, preserved smoke/facade checks, verified Core-owned Query/ABI inputs and per-run evidence. (#10)
- Add a standalone Emscripten 4.0.10 build with a pinned, checksum-verified Core dependency, explicit sibling development override and preserved WASM outputs. (#9)
- Import the existing WASM bridge, JavaScript wrappers, tests, parse example and CMake definition from the recorded Core baseline, with repeatable source/API parity verification. (#8)
- Record immutable Core provenance, source mapping and ownership for the behavior-preserving WASM/JavaScript migration. (OpenTLV/opentlv#697)
