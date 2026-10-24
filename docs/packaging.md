# Private JS/WASM package preparation

The canonical [package.json](../package.json) defines the independent
`opentlv-js` version, initially `0.1.0-dev.0`. This is an unreleased development
identity, not the pinned Core version or a release tag. Change this version
explicitly when advancing the binding; a Core pin change never changes it
automatically. Record binding changes under `Unreleased` in
[CHANGELOG.md](../CHANGELOG.md). Release version/tag policy remains deferred.

The name `opentlv-js` identifies this repository and its private local package.
No npm registry name or scope is selected or reserved. `private: true` makes npm
refuse publication, as described in the
[npm package metadata contract](https://docs.npmjs.com/cli/v10/configuring-npm/package-json/#private).
No publish command, credentials, lifecycle hook or GitHub release action is added.

## Build and check

Activate Emscripten 4.0.10 and Node 22 (including its bundled npm), then run:

```sh
emcmake cmake -S . -B build-wasm -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build-wasm --target opentlv-wasm --parallel
ctest --test-dir build-wasm --output-on-failure --no-tests=error
python -B scripts/package.py --build build-wasm --output build/package-check
```

Use the default pinned Core build. The command verifies its live source receipt
and rejects sibling development overrides. It checks all four nonempty outputs,
the WASM header and wrapper equality with the current sources. These checks
establish local package consistency, not attestation of arbitrary prebuilt
binaries. CI builds the inputs afresh before packaging.

The output directory must be new. The script stages an exact file allowlist,
generates `version.mjs` from `package.json`, and runs
[`npm pack`](https://docs.npmjs.com/cli/v10/commands/npm-pack/) first with
`--dry-run`, then as a local archive. Both calls use `--offline --ignore-scripts`.
The actual archive must contain exactly the expected regular files, with the
expected SHA-256 bytes; missing, extra, duplicate and symlink entries fail.

It then installs the archive into an isolated consumer using offline npm with
scripts, audit and funding requests disabled. The consumer checks every public
export, the independent version, the preserved Core version, WASM asset lookup,
default/explicit loader locations and parsing. The original smoke test and parse
example run against the installed archive. CI also runs the Core-owned Query
fixtures through the installed package's original facade runner.

The source checkout is a metadata/build source, not an installable package:
generated `index.mjs`, `version.mjs` and `dist/` live only in the staging area.
Do not pack or install the source root directly. For local experimentation,
install the checked `build/package-check/opentlv-js-<version>.tgz` archive.
The exact archive name, hashes and commands are in `build/package-check/result.json`.

## API and evidence

The [package README](../packaging/README.md) describes each export and asset
location. The original four output filenames and bytes are preserved.
`packaging/index.mjs` re-exports the existing facade and adds `packageVersion`.
The `opentlv-js/version` subpath exposes that value without loading the facade.
Existing `(await loadOpenTLV()).version` and the C bridge version entry point continue
to identify Core, preserving their migration contract.

`package-info.json` includes binding identity and separate immutable Core source
identity/output hashes. It excludes machine-specific build paths so identical
builds can produce identical packages. Node 22 is the validated runtime; ESM is
the only package module interface. Browser/worker runtime tests, CommonJS,
TypeScript, CDN and bundler support are not claimed.

All [CI tiers](ci.md) run package checks. The Release reproducibility tier also
compares the complete private archive hash, metadata and file hashes across two
independent builds. CI evidence includes package reports, but the private npm
archives are not uploaded as release artifacts. `published` and
`release_verified` stay false. A passing local run does not establish hosted CI
or a verified release.

## Separate distribution work

The [distribution follow-up register](distribution-follow-ups.md) tracks npm
publishing, security/advisory procedures and distribution improvements separately
from this migration preparation. None is enabled by this change.
