# WASM / JavaScript migration provenance

Tracking: [Core #697](https://github.com/OpenTLV/opentlv/issues/697),
[source transfer #8](https://github.com/OpenTLV/opentlv-js/issues/8),
[epic #696](https://github.com/OpenTLV/opentlv/issues/696).

## Immutable baseline

| Identity | Value |
| --- | --- |
| Original repository | `https://github.com/OpenTLV/opentlv` |
| Core commit | `a9a6f9470c2b285744738b40196bef9d0341fead` |
| Core root tree | `d1f63cbc2064a5d19c3dd6f19b97ddab427cfe64` |
| Git description | `0.7.1-40-ga9a6f9470`; not a tagged release |
| Nearest tag | `0.7.1` at `e12a52ff69a64468eecab084795a0530c273efea` |
| Initial standalone commit | `9a651e0da14cfca26c4770bb15e79432904bcba1` |
| Toolchain | Emscripten 4.0.10 / Node 22 / CMake Release / Ninja |

[source-inventory.json](migration/source-inventory.json) is the companion Core
baseline inventory, copied byte-for-byte. It records Git blobs, SHA-256, sizes,
ownership, proposed destinations, bridge declarations and build flags. The Core
version is dependency provenance, not the future JS package version.
The original [CMake target](https://github.com/OpenTLV/opentlv/blob/a9a6f9470c2b285744738b40196bef9d0341fead/bindings/wasm/CMakeLists.txt),
[workflow](https://github.com/OpenTLV/opentlv/blob/a9a6f9470c2b285744738b40196bef9d0341fead/.github/workflows/wasm.yml)
and [manual](https://github.com/OpenTLV/opentlv/blob/a9a6f9470c2b285744738b40196bef9d0341fead/docs/development/webassembly.md)
remain immutable references.

## Transfer map

| Original Core path | Initial destination or dependency |
| --- | --- |
| `bindings/wasm/src/*` | Same path in JS; preserve C bridge and signatures |
| `bindings/wasm/js/*` | Same path in JS; preserve both ES modules |
| `bindings/wasm/test/*` | Same path in JS; preserve smoke behavior |
| `bindings/wasm/examples/*` | Same path in JS; preserve parse example |
| `bindings/wasm/CMakeLists.txt` | Same initial path; standalone adaptation in #9 |
| `tests/query/wasm_facade.mjs` | JS facade runner, consuming selected Core fixtures |
| `docs/development/webassembly.md` | JS-owned manual after #13 |
| `.github/workflows/wasm.yml` | Adapt contracts into JS tiers under #10 |
| `bindings/common/*` | Consume from pinned Core; do not duplicate native helpers |
| `tlv/*`, `cmake/*`, shared Query corpus/oracle/ABI tests | Stay in Core |
| Generated `dist/*` | Rebuild from exact source/toolchain; not migrated source |

Later layout normalization belongs to #12. Existing browser/worker/Node loader
flags, `createOpenTLV`, growing memory, callback table growth, no filesystem,
ES module exports and explicit object lifetimes remain unchanged.

Preserve Node smoke/example, Query facade and Emscripten public Query ABI checks.
Preserve the tag-only double-build SHA-256 comparison of all four outputs.
The original CI executes Node, not browser/worker runtimes. Local baseline
evidence does not establish hosted CI, tag release, standalone compatibility,
browser behavior or npm publication.

## Source transfer (#8)

All seven files under `bindings/wasm/` and `tests/query/wasm_facade.mjs` are
imported byte-for-byte from the immutable baseline at their original paths.
Their existing license notices, error handling, memory ownership, exports and
test expectations are unchanged. Git attributes preserve LF line endings in
these files on Windows so checkout conversion cannot invalidate their hashes.

Run `python scripts/verify_migration.py` to check the exact eight-file set,
recorded sizes, SHA-256 and Git blob hashes, ownership/destinations and all 57
bridge declarations. The verifier uses the unchanged baseline inventory and
requires no Core checkout. Add `--core-source ../opentlv` to also compare the
baseline tree and source bytes with Core Git objects; the Core working tree and
current branch are not used. This verifier intentionally describes the initial
source transfer; later build/layout changes must record their adaptations.

The transferred CMake file is not a standalone entry point. It still requires
Core's `tlv` target and `opentlv_configure_compiler`, and the C bridge still
includes `../../common/query_schema.h` and `../../common/path_query.h`. These
Core-owned headers are not copied. Resolving that dependency belongs to #9.
The Query facade runner accepts the output directory and a fixture JSON path
as arguments; fixture generation, the shared corpus/oracle and ABI tests remain
in Core. CI wiring belongs to #10 and manual migration to #13.

Source parity does not establish standalone runtime, browser/worker, hosted CI,
tag reproducibility or release readiness. No generated outputs are imported.

## Next work

- [Workspace #42](https://github.com/OpenTLV/opentlv-workspace/issues/42): registration and sibling development.
- [#9](https://github.com/OpenTLV/opentlv-js/issues/9): standalone build and verified Core dependency.
- [#10](https://github.com/OpenTLV/opentlv-js/issues/10): tests and PR/Main/Full CI.
- [#11](https://github.com/OpenTLV/opentlv-js/issues/11): package identity; no npm publication.
- [#12](https://github.com/OpenTLV/opentlv-js/issues/12): layout.
- [#13](https://github.com/OpenTLV/opentlv-js/issues/13) and [Docs #93](https://github.com/OpenTLV/opentlv-docs/issues/93): documentation handoff.
- [Core #698](https://github.com/OpenTLV/opentlv/issues/698): remove old sources only after standalone checks pass.
- [#14](https://github.com/OpenTLV/opentlv-js/issues/14): coordinated final validation.
