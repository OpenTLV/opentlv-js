# WASM / JavaScript migration provenance

Tracking: [Core #697](https://github.com/OpenTLV/opentlv/issues/697),
[source transfer #8](https://github.com/OpenTLV/opentlv-js/issues/8),
[standalone build #9](https://github.com/OpenTLV/opentlv-js/issues/9),
[epic #696](https://github.com/OpenTLV/opentlv/issues/696).

## Immutable baseline

Documentation ownership transferred separately in #13. The
[documentation source record](migration/documentation-source.json) identifies
the exact Core revision of [the migrated WASM manual](docs/webassembly.md).
Its API section and code examples are preserved; only standalone build paths,
owner links, notification instructions and version identity are adapted.
The runtime source inventory and example bytes remain unchanged.

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
| `bindings/common/*` | Initially consumed from Core; transferred to JS `native/` under Core #698 |
| `tlv/*`, `cmake/*`, shared Query corpus/oracle/ABI tests | Stay in Core |
| Generated `dist/*` | Rebuild from exact source/toolchain; not migrated source |

The [standalone layout](#standalone-layout-12) maps these initial destinations
to their current paths after #12. Existing browser/worker/Node loader
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
accounts for the narrowly recorded #9 and #12 adaptations below while checking the
original eight-file set plus the two private adapters transferred under Core #698,
baseline ownership/destinations and all 57 bridge declarations. It
requires no Core checkout. Add `--core-source ../opentlv` to also compare the
baseline tree and original source bytes with Core Git objects; the Core working
tree and current branch are not used for migration parity checks.

The initial transfer did not provide a standalone entry point. The CMake file
depended on Core's `tlv` target and compiler policy, while the bridge used
relative includes for shared helpers. These Core-owned headers were not copied.
The Query facade runner accepts the output directory and a fixture JSON path
as arguments; fixture generation, the shared corpus/oracle and ABI tests remain
in Core. CI wiring is documented below; manual migration belongs to #13.

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
SHA-256 of the Core build inputs (originally 217; 215 after the private helper
transfer under Core #698). It also locks the Git metadata used by
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

## JS-owned CI (#10)

The [PR/Main/Full and Release workflows](docs/ci.md) now own the original Node
smoke/example, JS Query facade and Emscripten public Query ABI checks. They use
the selected pinned Core's fixture generator, corpus/reference helper and ABI
snapshots without migrating or duplicating those Core suites. Query inputs are
verified against the selected commit before execution.

PR and Main run Release; Full runs Release and Debug. Tag-triggered Release
validation preserves the independent double-build comparison of all four
outputs, and can also be rehearsed manually or locally. Emscripten 4.0.10 and
Node 22 remain fixed at the baseline versions. The eight transferred source
files and recorded #9 adaptations are unchanged by this CI wiring.

Logs and result manifests distinguish local runs, hosted run identity and
double-build reproducibility. Workflow implementation and local success do not
establish hosted success or tag-triggered execution. No browser/worker runtime
suite, package publication or release attestation is added.

## Private package preparation (#11)

The independent version in `package.json` starts at `0.1.0-dev.0`. Private
staging wraps the unchanged four outputs with explicit ESM/asset exports and
adds `packageVersion`; the existing loaded facade's `version` remains Core's
version. No transferred source or bridge declaration changes. Every CI tier
checks an offline npm archive and installed consumer; Release also compares
the private archives across its independent builds. This is not publication
or release attestation. See [packaging](docs/packaging.md) and the separate
[distribution follow-up register](docs/distribution-follow-ups.md).

## Standalone layout (#12)

The immutable inventory above retains its original paths, proposed destinations,
sizes, blobs and hashes. `scripts/verify_migration.py` maps those eight baseline
paths to the current source locations:

| Original Core / initial JS path | Current JS path |
| --- | --- |
| `bindings/wasm/js/opentlv.mjs` | `src/opentlv.mjs` |
| `bindings/wasm/js/query.mjs` | `src/query.mjs` |
| `bindings/wasm/src/opentlv_wasm.c` | `native/opentlv_wasm.c` |
| `bindings/wasm/src/opentlv_wasm.h` | `native/opentlv_wasm.h` |
| `bindings/wasm/test/smoke.mjs` | `tests/smoke.mjs` |
| `bindings/wasm/examples/parse.mjs` | `examples/parse.mjs` |
| `bindings/wasm/CMakeLists.txt` | `cmake/Wasm.cmake` |
| `tests/query/wasm_facade.mjs` | `tests/query/wasm_facade.mjs` |

The root project now includes the WASM target definition from `cmake/`.
Its source, wrapper and test paths follow this map; output placement changes
from `<build>/bindings/wasm/dist/` to `<build>/dist/`. The existing target name,
compiler policy, link options, output names, CTest names and test arguments
are preserved. CI, package staging and artifact uploads consume the new output
directory. Start with a fresh build directory when changing layouts.

The `layout_sha256` in `build-adaptations.json` records the relocated CMake
definition; the original baseline and #9 adapted hashes remain recorded.
Only path comments change in the bridge header and parse example; the verifier
reverses these exact edits before comparing baseline bytes. The #9 helper
include adaptation still applies to the C source. JS wrappers, smoke and Query
test bodies remain byte-identical, with the same 57 bridge declarations.
The verifier rejects missing/extra transferred files and the obsolete source
tree. No Core source inventory or native implementation is rewritten.

Package exports, facade imports, adjacent runtime assets, independent package
version and Core version semantics remain unchanged. The
[repository layout guide](README.md#repository-layout) documents directory
ownership and direct smoke/example commands.

## Private adapter ownership (Core #698)

The final extraction transfers `bindings/common/path_query.h` and
`bindings/common/query_schema.h` to `native/path_query.h` and
`native/query_schema.h`. These are binding allocation/diagnostic adapters over
public C APIs; Core has no consumer of them. Lua and Python own their copies in
their standalone repositories. This repository owns the WASM copies and all
JavaScript/TypeScript-specific sources, documentation and examples.

The original inventory still records its historical Core ownership. The verifier
maps both additional files and checks their exact baseline bytes, Git blobs and
SHA-256 hashes without changing that immutable record. The new
`helper_ownership_sha256` records the final CMake adaptation while preserving
both earlier hashes. The Core lock retains the same commit, tree and version
inputs; only its input checksum is recalculated over `CMakeLists.txt`, `cmake/`
and `tlv/`, excluding the two adapters now checked as JS sources.

Current builds work with both the historical pinned Core and a cleaned sibling
Core without `bindings/`. Merge and validate this JS change before Core removal.
The remaining binding-specific guide content transferred from Core commit
`ec89b763` is maintained in [the WASM manual](docs/webassembly.md#binding-contracts-and-examples).

## Validation review (#14)

Reviewed **2026-10-26** for [#14](https://github.com/OpenTLV/opentlv-js/issues/14)
and [Core epic #696](https://github.com/OpenTLV/opentlv/issues/696). This is a
dated acceptance record, not a release approval. Earlier sections describe the
migration stages; the outstanding work below supersedes their future-tense
handoff instructions. **Coordinated acceptance remains pending** because the
Workspace runtime integration and final hosted gates are not yet established.

### Reviewed identities and ownership

| Source | Exact revision / meaning |
| --- | --- |
| Immutable Core baseline and JS dependency | `a9a6f9470c2b285744738b40196bef9d0341fead`; original tree/version and 215 native inputs remain pinned |
| JS Main before this review | `c971205a1afeaeb2907998a60a0cc3448d1cd738`; includes final private adapter transfer |
| Cleaned Core Main | `1043bdccb0b5d3b519c5dd05cfc69bcdab511530`; merged Core #698 through PR #700 |
| Hosted Docs source set | `da7e1d7b14d5d34e851fb7ba2519431b66a198ac`; pins the JS and cleaned Core revisions above |
| Workspace Main | `c3cea9d82710346a1b91164a355a1cd1e7006487`; registers JS but pins scaffold `0e71aa6da491397b6c6dec2c258dff0bf65bab44` and baseline Core |

The source verifier passes for ten transferred files and 57 bridge declarations
against the original Core Git objects. Both facade modules, smoke test, Query
runner and private adapters retain baseline bytes; the bridge include paths,
two path comments and CMake adaptations are the recorded exceptions. The
documentation regression preserves the original API section/examples.

Core's cleaned revision contains no `bindings/`, `cmake/Wasm.cmake` or
`.github/workflows/wasm.yml`, and no active `OPENTLV_BUILD_WASM` or WASM
subdirectory wiring. Comparing its entire `tests/query/` tree with the baseline
shows only deletion of `wasm_facade.mjs`, whose exact bytes are in JS. The corpus,
fixture generator, reference helper, ABI probe/checker/snapshots and all other
Query tests are unchanged. Core retains native semantic test ownership; JS
executes the selected Core's fixtures and ABI checks without copying them.

### Compatibility and local execution

The [executable migration gate](docs/ci.md#executable-migration-comparison-14)
compares real generated contracts and all four outputs with a fresh historical
Core build. It runs in Full/Release, in addition to existing facade, ABI and
private-package checks. A failure cannot pass the aggregate workflow gate.

Local review uses Linux under WSL, Emscripten 4.0.10 and Node 22.16.0. Evidence
under `build/issue14-validation/` belongs to the uncommitted issue #14 working
tree based on the JS revision above; it is not evidence for a hosted commit.
The Release and Debug runner manifests retain their exact Core receipts and
command results. The historical and standalone Release outputs compare as:

| Output | SHA-256 (both build systems) |
| --- | --- |
| `opentlv-core.js` | `600e1fac532c89aa92b4b72877268cb14d1f824c5e27eb747e6a27dc90a8ab5c` |
| `opentlv-core.wasm` | `9e50172279416c7b55431528f137cf254918da4100c6dd548eba34dbe0bf24a9` |
| `opentlv.mjs` | `73be28ae8af25e78829671218dbb62e6392b786a18664c51aaa70a2a85f0b1a7` |
| `query.mjs` | `4a966ea90a314c1d3e017713d4e842831ba593a21915ab5eafa7ceafb9d6a5de` |

Completed local checks:

- 68 infrastructure regressions passed on Linux; Windows passed with four
  symlink-dependent skips. Source parity and actionlint passed.
- Pinned Release double-build and Debug passed smoke/parse CTests, 171 Query
  fixtures / 3,422 backend-window checks plus the existing extension/lifetime
  regressions, wasm32 ABI snapshot `32-8`, offline packing/install and installed
  consumer/facade checks.
- The fresh historical Release build passed both CTests and matched all 60
  binary export descriptors, imports, ES-module/runtime surfaces and the 57
  public bridge functions. All four output hashes match the table above.
- Two fresh standalone Release builds produced the identical private archive
  SHA-256 `5895c3293903faa2a52b338a60b27daa44b95550a6e2c252c0bd0bdb942c2b2e`.
  `release-evidence/result.json` records both reproducibility and migration
  compatibility as passed; `debug-evidence/result.json` records Debug success.
- Direct sibling Release against cleaned Core `1043bdcc` passed the same two
  CTests, Query facade and ABI checks. Its receipt correctly says
  `local-development`, `dirty: true`: all 215 native inputs differ from Git
  only by Windows CRLF checkout conversion, verified separately without
  normalizing the build inputs or weakening checks. This is not a pinned-source
  result or a Workspace Full run.

The source/runtime evidence establishes no unintended change within the
migrated contracts and exercised behavior. It is not exhaustive proof of every
input. Loader flags retain `web,worker,node`, memory/table growth, ES modules,
`createOpenTLV` and no filesystem. Baseline and standalone CI execute Node;
browser/worker execution remains unverified, as in the baseline.

### Hosted evidence

All listed runs were inspected with their **attempt 1** job conclusions; JS
runtime and Docs smoke logs were also reviewed. These runs predate this change
and cannot certify the new migration gate. Links identify exact runs and gates.

| Gate | Result and boundary |
| --- | --- |
| JS PR for adapter transfer | [40116931975](https://github.com/OpenTLV/opentlv-js/actions/runs/40116931975), `2ecf8a6f90f057875592b75ab0cdb67f1a3128bc`: infrastructure, Release and [aggregate gate](https://github.com/OpenTLV/opentlv-js/actions/runs/40116931975/job/120940282130) passed |
| JS Main after transfer | [40117119940](https://github.com/OpenTLV/opentlv-js/actions/runs/40117119940), reviewed JS Main: infrastructure, Release, [aggregate gate](https://github.com/OpenTLV/opentlv-js/actions/runs/40117119940/job/120940869832) and notification evidence passed |
| Historical JS Full | [40110137590](https://github.com/OpenTLV/opentlv-js/actions/runs/40110137590), `e9d14f452bc024da3bc5ee1a474d3aba8944a076`: Release, Debug, infrastructure and [gate](https://github.com/OpenTLV/opentlv-js/actions/runs/40110137590/job/120920217329) passed **before** private adapter transfer |
| JS notifier | [40117237919](https://github.com/OpenTLV/opentlv-js/actions/runs/40117237919), reviewed JS Main: successful delivery workflow; consumed JS pin is separately confirmed in Docs |
| Core cleanup PR | [40116852347](https://github.com/OpenTLV/opentlv/actions/runs/40116852347), `14e5102e93ba616d52db7b04b8d8a78200a40355`: selected PR checks and [gate](https://github.com/OpenTLV/opentlv/actions/runs/40116852347/job/120942918944) passed; Full-only jobs were skipped |
| Core cleanup Main | [40121519262](https://github.com/OpenTLV/opentlv/actions/runs/40121519262), reviewed Core Main: consumer smoke and [gate](https://github.com/OpenTLV/opentlv/actions/runs/40121519262/job/120954051777) passed; no Core Full run found on this SHA |
| Docs Main | [40216050919](https://github.com/OpenTLV/opentlv-docs/actions/runs/40216050919), reviewed Docs source set: smoke and [gate](https://github.com/OpenTLV/opentlv-docs/actions/runs/40216050919/job/121237896079) passed; logs confirm exact JS/Core pins. Playground artifacts were absent; this is not publication/browser evidence |
| Workspace Main | [40077184574](https://github.com/OpenTLV/opentlv-workspace/actions/runs/40077184574), reviewed Workspace Main: fast smoke and gate passed; no JS runtime checks |
| Historical Workspace Full | [40073235768](https://github.com/OpenTLV/opentlv-workspace/actions/runs/40073235768), `7390f94cefc7e1ab12c71b02b64c7b54a8a74698`: sibling, remote and gate passed **before JS registration**; not JS acceptance evidence |

### Docs and Workspace alignment

The [reviewed Docs manifest](https://github.com/OpenTLV/opentlv-docs/blob/da7e1d7b14d5d34e851fb7ba2519431b66a198ac/docs-sources.json)
mounts JS at `js`, registers `js-main.yml` documentation updates, and navigates
all four Markdown files at the pinned JS revision: manual, CI, packaging and
distribution follow-ups. Its example catalog uses the independent JS package
version. Source ownership and reviewed pin consumption are established;
publication of this final review requires separate evidence.

Workspace registration is present, but its [integration runner](https://github.com/OpenTLV/opentlv-workspace/blob/c3cea9d82710346a1b91164a355a1cd1e7006487/scripts/integration.py)
still treats JS as a metadata-only scaffold. Full records a JS checkout but does
not build it, run its smoke tests, or pass it to the Docs integration smoke.
The old JS pin has no standalone build. This is an explicit acceptance gap,
not a successful JS Workspace gate. A direct local sibling build is narrower
evidence than the Workspace aggregate.

### Deviations, release readiness and completion

Migration-only changes are standalone dependency/CI ownership, explicit source
selection and receipts, private package staging with additive `packageVersion`,
normalized paths, JS-owned adapters and documentation notifications. Existing
facade `version` still reports Core. No semantic API redesign, TypeScript
declarations, dependency upgrade or new runtime implementation is introduced.
The package remains private at `0.1.0-dev.0`; publication and release verification
remain false. Historical Core pinning is intentional and is compatible with
removing the obsolete implementation from current Core.

| #14 acceptance criterion | Status |
| --- | --- |
| No unintended API or behavior changes | Supported within source parity, binary equality and existing runtime coverage; browser/worker execution unverified |
| Independent build and all migration gates pass | Local validation and historical hosted JS checks available; final candidate Full/Release and Workspace integration pending |
| Core cleanup without loss of Core-owned tests | Source cleanup and retained Query suites verified; Core PR/Main passed, cleaned-revision Full pending |
| Release readiness and compatibility recorded | Recorded here; coordinated readiness is pending, npm publication is outside migration |

Completion sequence:

1. **JS:** commit/review this candidate, require PR and Full including the new
   comparison, and run manual Release reproducibility on that exact revision.
   After merge, retain the actual Main result. A manual Release rehearsal does
   not prove a tag-triggered run.
2. **Core:** retain a successful Core Full aggregate on the cleaned source set;
   PR/Main smoke cannot substitute for skipped Full-only coverage.
3. **Workspace:** implement JS runtime and Docs smoke in sibling and remote
   modes, review pins to merged standalone JS/cleaned Core/compatible Docs, and
   require both integration jobs plus Full's aggregate at that exact combination.
4. **Docs:** consume the merged review through the existing notification/pin
   process, validate the locked source set, and record publication separately
   if claiming that revision is live.
5. **Release owner:** assess the final gate evidence and independently authorize
   version/tag/distribution work. [Distribution follow-ups](docs/distribution-follow-ups.md)
   track npm naming/publication, TypeScript, browser/worker coverage, toolchain
   modernization and security/distribution policy. None is silently completed
   by migration checks.

Keep #14 and epic #696 open until the outstanding coordinated gates are recorded.
