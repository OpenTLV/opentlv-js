# JS/WASM validation

The JS repository tests its public JavaScript facade and C-to-WASM boundary.
Native parsing, writing, Document, Query and Schema behavior suites remain in
Core. The migrated smoke test (`tests/smoke.mjs`), parse example
(`examples/parse.mjs`) and Query facade runner retain their behavior.

## Tiers

All runtime jobs use Ubuntu 24.04, Emscripten **4.0.10**, Node **22**, Ninja and
the exact Core revision in `cmake/core-source.json`. Node is selected after the
Emscripten environment, so the SDK's bundled Node cannot silently replace it.

| Workflow | Trigger | Runtime checks |
| --- | --- | --- |
| JS Pull Request CI | PR targeting `main`, without path filters | Release build, smoke, parse example, Query facade, WASM Query ABI, private package checks |
| JS Main CI | Push to `main` | Same checks on the actual merged commit; upload outputs |
| JS Full CI | Manual or reusable workflow call | Release and Debug, each with the same checks; upload outputs |
| JS Release reproducibility | Version-shaped tag push or manual rehearsal | Two fresh Release builds, all checks in each, compare all four output and private package hashes |

Full's Release configuration and the Release workflow additionally rebuild the
historical Core WASM target and require migration compatibility as described
below. Debug retains its own runtime/package checks without comparison to a
Release binary.

Each workflow also runs the migration verifier, Python infrastructure
regressions and actionlint 1.7.7. The reusable `js-checks.yml` provides a final
`JS quality gate` that requires every infrastructure and runtime job to succeed;
failed, cancelled or skipped prerequisites cannot pass it. Branch protection is
configured separately in GitHub and must require the PR gate.

The tag patterns preserve the baseline's unprefixed and `v`-prefixed version
shapes. They are triggers, not a package version policy. A manual Release run
rehearses the same checks without creating a tag. No workflow publishes an npm
package, creates a GitHub release or claims release attestation.

## Pinned Core API reference report

The infrastructure job also runs `scripts/api_coverage.py`, adapted from the
Python binding's reporter and its Go port. It writes
`build/api-coverage/report.json`, uploads `js-api-coverage-<tier>-<attempt>` and
appends a Markdown report to the GitHub Step Summary. PRs compare the current
lock with `cmake/core-source.json` at the event's exact base SHA. Main, Full and
Release report the current pin without inventing a previous revision.

The report is **informational**: missing symbols and stale ignore patterns do
not fail CI or impose a percentage threshold. Invalid inputs, unknown `TLV_API`
declarations, missing Git objects or failed report generation do fail the
infrastructure job. The report lists generic Core and Builtins separately,
per-header referenced/missing/ignored names, exclusion reasons, stale patterns,
and symbols added or removed by a Core-pin change, with their header and kind.
This is a symbol-name diff, not a C signature or ABI compatibility checker.

Run from the repository root with Python and Git; Emscripten is not required:

```sh
# Fetch only the exact locked Core commit into build/api-coverage/core.git.
python -B scripts/api_coverage.py --output build/api-coverage/report.json
# Read committed blobs from an existing Core repository, without fetching.
python -B scripts/api_coverage.py --core ../opentlv --base origin/main \
  --output build/api-coverage/report.json
```

`--base` names a **binding** revision containing the previous lock;
`--base-commit` names a previous **Core** revision. `--commit` is an explicit
exploratory Core override and is recorded in the report; CI never uses it.
`--summary <file>` appends Markdown to an existing summary. Without `--core`,
the tool shallow-fetches required commits; with it, all requested commits must
already exist. Header inventories always use Git blobs at those commits, even
if the Core checkout has moved or contains uncommitted edits.

### Initial inventory for #2

Reviewed against JS source `72338d8` and locked Core
`a9a6f9470c2b285744738b40196bef9d0341fead`. The source patterns in
`cmake/api-coverage.json` select `native/*.c` and `native/*.h`, including private
adapters. Comments and C literals do not count. Docs, tests, generated output,
dependency sources and migration inventories are outside these patterns.
`src/*.mjs` calls the separate `opentlv_wasm_*` bridge namespace and contributes
no direct Core symbol references; TypeScript declarations do not yet exist.

| Scope | All symbols | Referenced | Missing | Ignored |
| --- | ---: | ---: | ---: | ---: |
| Generic Core | 297 | 83 | 212 | 2 |
| Builtins | 291 | 19 | 272 | 0 |

The adjusted generic reference ratio is 83/295 (28.1%); Builtins is 19/291
(6.5%). Only two redundant entry points are excluded: `tlv_reader_next`, whose
diagnostic form is used inside parsing, and NUL-terminated `tlv_query_parse`,
whose explicit-length form implements `V1Query`. The configuration records the
reason for each. Missing Writer, field, codec and other generic operations
remain visible; exclusions from other bindings are not assumed to apply here.

These numbers count lexical references, including private helper bodies and
conditional code. They do not prove linked WASM exports, JS reachability,
TypeScript support, executed paths or functional parity. Conversely, descriptor
callbacks may be usable without a direct symbol reference. The existing
migration contract checks cover the separate 57-function bridge baseline;
functional additions need public binding tests and a reviewed contract.

| Area | Existing public JS surface | Follow-up inventory |
| --- | --- | --- |
| Format | Named formats, Fixed options and custom callbacks | Generic field composition and additional format operations |
| Streaming | Query execution has incremental input | General Reader/Writer and tree APIs are absent |
| Document/Query/Schema | Parse/navigation, value edits, encode, compiled and V1 queries, QuerySchema | Document construction/insertion and general structural schema operations |
| Codec/generation | Query uses Core adapters internally | Public generic codecs and wire generation are absent |

This is the instrumentation step of epic #1, not a functional-completion claim.
The report changes no public API, ownership, lifecycle or error contract. Official
builds still enable all supported Core components and Builtins; Builtins parity
remains outside the generic epic.

### Generic Format/field update (#3)

At the same Core pin, the new [public APIs](webassembly.md#generic-formats-and-field-encodings)
raise the generic inventory to **109 referenced, 166 missing, 22 ignored**
(109/275, 39.6%). Builtins stays at 19 referenced / 272 missing.
All declarations in `tlv/field/{fixed,variable,escaped,packed}.h` and
`tlv/format.h` now have meaningful binding references. Descriptor callbacks
installed by bound initializers and equivalent specialized binary composition
entry points have explicit exclusion reasons. They are exercised through
Format operations, not artificially referenced to increase the count.

This closes the Format/field workstream, not the general API epic: Reader/Writer,
structural Schema, codecs and generation still require their own public API
work. Generic tests run as CTests and against the installed archive.

### Post-migration source evolution

`ci/source-evolution.json` records reviewed changed/added source hashes and exact
reversible changes for #3. The original migration inventory, build-adaptation
hashes, Core pin and 57 bridge declarations remain immutable. The source
verifier checks current additions, restores the recorded migration bytes in
memory, and verifies those against the original hashes/Git objects. Unknown
files, unrecorded edits and stale restoration rules fail verification.

Full/Release still rebuild the historical Core target. Since additive features
intentionally change current binaries, the runner also reconstructs and builds
the completed standalone migration sources and requires their exact contract
and all four output hashes to equal the historical Core build. A separate check
compares the current public Emscripten runtime and ES-module namespaces, allowing
only the five reviewed additional bridge exports. Current binary descriptors
are recorded, but their minified names are not an ABI contract. Feature CTests,
existing facade/ABI tests and installed-package tests run on the current build.
Release continues to compare two independent **current** builds and archives.

The evidence explicitly sets `current_is_migration_baseline: false`; historical
byte equality must not be reported as current byte equality. This keeps the
completed migration check distinct from post-migration feature validation.

## Core integration and ownership

Each build uses default FetchContent selection and verifies `pinned-source`
provenance before and after the integration tests. A sibling development
receipt is rejected by this CI runner. The native dependency checksum and Git
version metadata retain the [standalone build contract](../README.md#standalone-build).

The Query integration additionally verifies every file under the selected
Core's `tests/query/` against its exact commit's Git blobs. Modified, missing,
symlinked and extra files, including ignored files, fail before executing the
Core helpers. The evidence records this directory's aggregate SHA-256. Python
bytecode generation is disabled so helper imports do not modify those inputs.

The runner invokes Core's `facade_fixtures.py`, which consumes Core's corpus and
reference helper, then passes its generated JSON to the JS-owned
`tests/query/wasm_facade.mjs`. It compiles Core's `abi.c` using Emscripten and the
selected build's generated headers, executes it in Node, and invokes Core's
`check_abi.py` against Core's reviewed architecture snapshot. Python optimization
is disabled for that subprocess so assertions remain active. This checks the
public WASM interoperability layout; it does not duplicate native Core tests
or copy fixture, oracle or ABI snapshot ownership into JS.

The generated module retains `web,worker,node` loader support. As in the
immutable migration baseline, these workflows execute **Node only**. Browser
and worker runtime validation are not established by this CI.

## Local execution

Activate Emscripten 4.0.10 and put Node 22 first on `PATH`, then run:

```sh
python -B scripts/verify_migration.py
python -B -m unittest discover -s tests -v
python -B scripts/ci.py --tier pr
python -B scripts/ci.py --tier main
python -B scripts/ci.py --tier full --configuration Release
python -B scripts/ci.py --tier full --configuration Debug
python -B scripts/ci.py --tier release
```

The runner uses `build/ci/<tier>/<configuration>/` by default. Every invocation
requires a fresh output directory to prevent stale artifacts or evidence from
passing. For a repeat run, supply a new directory, for example
`--output build/ci/release-rehearsal-2`. Ordinary sibling development remains
available through the standalone CMake commands in the README.

`--tier release` builds independently under `first/` and `second/`, each with
its own fetched Core source and generated files. Every output must exist and
be nonempty: `opentlv-core.js`, `opentlv-core.wasm`, `opentlv.mjs`, `query.mjs`.
These files are in each build's `dist/` directory, also used by the workflow's
output artifact upload. Repository source paths are documented in the
[layout guide](../README.md#repository-layout).
A mismatch in any one fails the run. Main and Full do not implicitly prove
reproducibility; only the double-build check does. Each build also runs the
[private package checks](packaging.md): offline dry-run/real packing, exact
archive content checks, offline installation, package exports/version/asset
tests and the existing smoke/example/Query facade against the installed files.
The double-build tier additionally requires identical archive bytes, package
metadata and file hashes. Node's bundled npm is required and its version is
recorded in each package report.

## Evidence

### Executable migration comparison (#14)

`scripts/migration_compatibility.py` rebuilds the original WASM target from the
verified Core checkout at `a9a6f9470c2b285744738b40196bef9d0341fead`, using the
Release flags in the immutable source inventory and a fresh
`migration-baseline/` build directory. Historical bridge/helper inputs are
checked for exact file membership and SHA-256 before configuration and after
comparison. The standalone source verifier also compares its ten transferred
files with the original Git objects. The historical build runs its two CTests.

`scripts/inspect_wasm.mjs` compiles the actual WASM binary, records its export
and import names/kinds, imports the three ES modules and initializes the
Emscripten factory using the adjacent binary. It compares namespace names/types
and the initialized runtime surface, including all 57 public bridge functions.
This uses runtime bridge names because optimized binary exports are minified.
Both builds must have equal contracts and equal SHA-256 hashes for **every one
of the four outputs**. A mismatch fails the overall Full/Release run.

The CI result includes `migration_compatibility` only after this check succeeds;
`migration-*-contract.json` and command logs accompany the report. This is
distinct from double-build reproducibility: the latter compares two standalone
builds and their private archives; migration compares the old and new build
systems. Future intentional runtime changes or a Core/toolchain upgrade need a
reviewed replacement for this migration gate, retaining the historical record.
Neither check establishes browser/worker execution or release authorization.

See the [dated migration acceptance review](../MIGRATION.md#validation-review-14)
for cross-repository pins, hosted evidence, deviations and remaining gates.

### Run receipts

`evidence/result.json` records the tier, configuration, checkout commit/dirty
state, tool versions, GitHub repository/SHA/ref/run/attempt when present, Core
selection receipts, Query input identity, output hashes and command results.
`first-package.json` (and `second-package.json` for Release) record the private
package version, archive/file hashes, npm version and commands. Package staging,
archives, consumers and detailed logs remain in the local `first-package/` and
`second-package/` directories and are not included in uploaded release artifacts.
Logs, generated fixtures and observed ABI JSON accompany the CI report. Failures retain a
failed result and command logs; a failed comparison never sets
`reproducibility_verified`. `release_verified` remains false: these are build
and test results, not package/release attestation.

Hosted artifacts include the tier, configuration and run attempt in their names.
Evidence uploads run even after test failure. Output uploads require successful
runtime checks and are omitted for PRs. Downloaded outputs must be assessed
together with the matching evidence and final workflow gate; an artifact upload
alone does not prove all checks passed.

Local runs report `hosted: false`. They can establish local smoke, facade, ABI
and reproducibility results, but cannot establish a successful hosted PR/Main/
Full run, tag-triggered execution, branch protection or publication.

## Documentation updates

JS owns [the WASM manual](webassembly.md), the unchanged
[parse example](../examples/parse.mjs), and [docs-examples.json](../docs-examples.json).
The catalog's `component_version` must equal the independent version in
`package.json`; it is not the embedded Core version. Docs assembles these sources
at a reviewed commit, retaining JS source/edit links. A documentation update
does not establish runtime compatibility with the portal's selected Core.

After the complete `JS Main CI` checks succeed, `docs_changes` compares relevant
paths against the previous successful official Main push. This includes changes
from intervening failed or cancelled pushes. First runs inspect the complete
tree. Manuals, examples, packaging, package/Core metadata and notification
infrastructure count; unrelated runtime source changes do not notify Docs.
The producer uploads `docs-notification-<run_attempt>/notification.json` with
its exact repository, commit, run ID, attempt and change flag using read-only
credentials.

`docs-notify.yml` runs separately on successful Main completion. It performs no
checkout, validates that exact JSON against the official push run, and sends
`component-docs-updated` with source `js`, repository `OpenTLV/opentlv-js`, the
producer SHA, `ref: main` and producer run ID. The dispatch secret is available
only in the final inline step. No relevant change means no dispatch or token
requirement. Missing credentials, invalid evidence or failed dispatch fail the
notifier without changing the completed build result.

For the initial [Docs #93](https://github.com/OpenTLV/opentlv-docs/issues/93) handoff:

1. Configure this repository's `OPENTLV_DOCS_DISPATCH_TOKEN` with fine-grained
   **Contents: write** access to `OpenTLV/opentlv-docs` for repository dispatch.
   The ordinary `GITHUB_TOKEN` cannot dispatch to another repository.
2. Verify Docs has `DOCS_UPDATES_TOKEN` for creating update PRs that trigger CI.
   If its default token cannot read JS Actions/history, configure the separate
   `DOCS_SOURCE_READ_TOKEN` with **Actions: read** and **Contents: read** on JS.
3. Merge Docs registration/receiver support first. It pins the already merged
   layout baseline and keeps the historical Core manual available until the
   standalone manual is included in a reviewed JS pin.
4. Merge JS changes; successful JS Main and its notifier propose an exact-SHA
   Docs pin update. Review that pin and require Docs validation before merging.

The receiver verifies the configured producer and main ancestry, rejects stale
or divergent updates, and treats replay as a no-op. Retry a failed notifier
while its attempt-specific artifact is retained; if expired, a new successful
Main run is needed. HTTP 204 proves dispatch acceptance only. Receiver processing,
the pin PR, hosted checks and publication require their own evidence. Local tests
mock delivery and do not configure secrets or publish. Release/tag workflows do
not send this documentation notification. The portal's existing playground
binary producer remains separate from this documentation handoff.
