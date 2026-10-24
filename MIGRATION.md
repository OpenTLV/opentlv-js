# WASM / JavaScript migration provenance

Tracking: [Core #697](https://github.com/OpenTLV/opentlv/issues/697),
[source transfer #8](https://github.com/OpenTLV/opentlv-js/issues/8),
[standalone build #9](https://github.com/OpenTLV/opentlv-js/issues/9),
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
| `bindings/wasm/src/*` | Same path in JS; shared helper include paths adapted in #9 |
| `bindings/wasm/js/*` | Same path in JS; preserve both ES modules |
| `bindings/wasm/test/*` | Same path in JS; preserve smoke behavior |
| `bindings/wasm/examples/*` | Same path in JS; preserve parse example |
| `bindings/wasm/CMakeLists.txt` | Same path; standalone target adaptation recorded in #9 |
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

All seven files under `bindings/wasm/` and `tests/query/wasm_facade.mjs` were
imported byte-for-byte from the immutable baseline at their original paths.
Their existing license notices, error handling, memory ownership, exports and
test expectations are unchanged. Git attributes preserve LF line endings in
these files on Windows so checkout conversion cannot invalidate their hashes.

The immutable baseline inventory remains unchanged. The migration verifier
now accounts for the narrowly recorded #9 adaptations below while checking the
eight-file set, ownership/destinations and all 57 bridge declarations. It
requires no Core checkout. Add `--core-source ../opentlv` to also compare the
baseline tree and original source bytes with Core Git objects; the Core working
tree and current branch are not used for migration parity checks.

The initial transfer did not provide a standalone entry point. The CMake file
depended on Core's `tlv` target and compiler policy, while the bridge used
relative includes for shared helpers. These Core-owned headers were not copied.
The Query facade runner accepts the output directory and a fixture JSON path
as arguments; fixture generation, the shared corpus/oracle and ABI tests remain
in Core. CI wiring belongs to #10 and manual migration to #13.

Source parity alone does not establish runtime or release readiness. No
generated outputs are imported.

## Standalone build adaptations (#9)

- The root CMake project selects Emscripten 4.0.10 and a verified source Core,
  then builds the existing `opentlv-wasm` target. Node tests require Node 22.
- `bindings/wasm/CMakeLists.txt` links public `OpenTLV::tlv` and adds the selected
  Core's `bindings/common` include directory. The command comment is updated;
  output names, link flags, wrapper copying and test bodies are unchanged.
  [build-adaptations.json](migration/build-adaptations.json) records its original
  and adapted SHA-256 hashes.
- `opentlv_wasm.c` changes only the two shared helper includes from
  `../../common/<name>` to `<name>`. The verifier reverses these exact include
  changes before comparing the full file to the baseline hashes.
- The other six transferred files remain byte-identical. The bridge
  declarations, wrappers, smoke test, example and Query facade expectations
  retain their original contracts.

[core-source.json](cmake/core-source.json) pins the baseline commit/tree and the
SHA-256 of all 217 Core build inputs. It also locks the Git metadata used by
Core's version generator, including semantic tags on the selected tag commit.
The default FetchContent path verifies these values before evaluating Core
CMake and before building. No package search, binary fallback, moving branch or
unverified source fallback is used. All 17 baseline capabilities are required.

An explicit `FETCHCONTENT_SOURCE_DIR_OPENTLV_CORE` selects local development;
its actual commit, input checksum and dirty state are recorded separately in
`core-selection.json`. This supports sibling edits without representing them
as pinned or attested release inputs. See the [build instructions](README.md#standalone-build).

Reproducibility means byte-identical hashes for all four outputs from two fresh
Release builds with the pinned source and toolchain. Hosted CI, browser/worker
execution, tag-triggered validation and release attestation remain separate
gates; this step does not claim them.

## Next work

- [Workspace #42](https://github.com/OpenTLV/opentlv-workspace/issues/42): registration and sibling development.
- [#10](https://github.com/OpenTLV/opentlv-js/issues/10): tests and PR/Main/Full CI.
- [#11](https://github.com/OpenTLV/opentlv-js/issues/11): package identity; no npm publication.
- [#12](https://github.com/OpenTLV/opentlv-js/issues/12): layout.
- [#13](https://github.com/OpenTLV/opentlv-js/issues/13) and [Docs #93](https://github.com/OpenTLV/opentlv-docs/issues/93): documentation handoff.
- [Core #698](https://github.com/OpenTLV/opentlv/issues/698): remove old sources only after standalone checks pass.
- [#14](https://github.com/OpenTLV/opentlv-js/issues/14): coordinated final validation.
