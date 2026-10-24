# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- Add a standalone Emscripten 4.0.10 build with a pinned, checksum-verified Core dependency, explicit sibling development override and preserved WASM outputs. (#9)
- Import the existing WASM bridge, JavaScript wrappers, tests, parse example and CMake definition from the recorded Core baseline, with repeatable source/API parity verification. (#8)
- Record immutable Core provenance, source mapping and ownership for the behavior-preserving WASM/JavaScript migration. (OpenTLV/opentlv#697)
