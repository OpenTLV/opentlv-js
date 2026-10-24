# JS/WASM validation

The JS repository tests its public JavaScript facade and C-to-WASM boundary.
Native parsing, writing, Document, Query and Schema behavior suites remain in
Core. The migrated smoke test, parse example and Query facade runner are
unchanged.

## Tiers

All runtime jobs use Ubuntu 24.04, Emscripten **4.0.10**, Node **22**, Ninja and
the exact Core revision in `cmake/core-source.json`. Node is selected after the
Emscripten environment, so the SDK's bundled Node cannot silently replace it.

| Workflow | Trigger | Runtime checks |
| --- | --- | --- |
| JS Pull Request CI | PR targeting `main`, without path filters | Release build, smoke, parse example, Query facade, WASM Query ABI |
| JS Main CI | Push to `main` | Same checks on the actual merged commit; upload outputs |
| JS Full CI | Manual or reusable workflow call | Release and Debug, each with the same checks; upload outputs |
| JS Release reproducibility | Version-shaped tag push or manual rehearsal | Two fresh Release builds, all checks in each, compare SHA-256 of all four outputs |

Each workflow also runs the migration verifier, Python infrastructure
regressions and actionlint 1.7.7. The reusable `js-checks.yml` provides a final
`JS quality gate` that requires every infrastructure and runtime job to succeed;
failed, cancelled or skipped prerequisites cannot pass it. Branch protection is
configured separately in GitHub and must require the PR gate.

The tag patterns preserve the baseline's unprefixed and `v`-prefixed version
shapes. They are triggers, not a package version policy. A manual Release run
rehearses the same checks without creating a tag. No workflow publishes an npm
package, creates a GitHub release or claims release attestation.

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
A mismatch in any one fails the run. Main and Full do not implicitly prove
reproducibility; only the double-build check does.

## Evidence

`evidence/result.json` records the tier, configuration, checkout commit/dirty
state, tool versions, GitHub repository/SHA/ref/run/attempt when present, Core
selection receipts, Query input identity, output hashes and command results.
Logs, generated fixtures and observed ABI JSON accompany it. Failures retain a
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
