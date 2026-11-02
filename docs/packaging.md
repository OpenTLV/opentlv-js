# Private JS/WASM package preparation

The canonical [package.json](../package.json) defines the independent
`@opentlv/opentlv` version. The first standalone release is `0.1.0` (#32), prepared
against Core `v0.8.0`. The earlier `0.1.0-dev.0` was an unreleased development
identity, not a previous JS release; there were no JS repository tags or GitHub
releases when checked on 2026-10-28. The JS version is not the pinned Core
version: change it explicitly when advancing the binding; a Core pin change
never changes it automatically. Record binding changes under `Unreleased` in
[CHANGELOG.md](../CHANGELOG.md).

Release tags are `vMAJOR.MINOR.PATCH` and must equal `v` plus the
`package.json` version, the `component_version` in
[docs-examples.json](../docs-examples.json) and the heading of
[ci/release-notes.md](../ci/release-notes.md). Prerelease tags and npm
dist-tags are not used.

`private: true` makes npm refuse publication, as described in the
[npm package metadata contract](https://docs.npmjs.com/cli/v10/configuring-npm/package-json/#private).
The [GitHub release](#github-release) workflow attaches the tested archive to a
GitHub release. Its optional [npm publication](#npm-publication) publishes that
same archive after an explicit approval, and rejects the request while the
package is private. No registry credential or lifecycle hook is added.

## Package identity

The package is `@opentlv/opentlv`, selected in #37 and checked on 2026-10-30:

| Item | Decision | Evidence |
| --- | --- | --- |
| Organization | `opentlv` | The public registry lists the scope with no packages (`/-/org/opentlv/package` returns `{}`) |
| Owner | npm account `marekcingel` | Recorded by the maintainer in [#36](https://github.com/OpenTLV/opentlv-js/issues/36); the registry does not show it without signing in |
| Package name | `@opentlv/opentlv` | The registry has no such package (`404`), so nothing has been published under it |
| Access | Public once published | Scoped packages need an [explicit `--access public`](https://docs.npmjs.com/creating-and-publishing-scoped-public-packages/) |

The scope limits who can publish, while the package name is created only by its
first publication. Selecting the name therefore publishes nothing and changes no
access: `private: true` stays until the separately approved publication.
The release workflow passes `--access public` on the command line (#39), so
`publishConfig` remains rejected. Whether the organization enforces 2FA for all members still has
to be confirmed in its npm settings; it is not visible from the public registry.

`opentlv-js` remains the name of the repository, its CMake targets and the
migration owner. Imports use `@opentlv/opentlv`, and `npm pack` names the archive
`opentlv-opentlv-<version>.tgz`. The `v0.1.0` GitHub release predates this
selection: its asset stays `opentlv-js-0.1.0.tgz` and is imported as `opentlv-js`.

## Build and check

Activate Emscripten 4.0.10, Node 22 (including npm) and TypeScript 5.9.3 (`tsc` on
`PATH`), and provide Chrome or Chromium (`google-chrome`, `chromium` or
`chromium-browser` on `PATH`, or `OPENTLV_BROWSER` set to its path), then run:

```sh
emcmake cmake -S . -B build-wasm -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build-wasm --target opentlv-wasm --parallel
ctest --test-dir build-wasm --output-on-failure --no-tests=error
python -B scripts/package.py --build build-wasm --output build/package-check
```

Use the default pinned Core build. The command verifies its live source receipt
and rejects sibling development overrides. It checks all four nonempty outputs
in `<build>/dist/`, the WASM header and wrapper equality with `src/*.mjs`.
It runs the smoke, Format/field and Reader/Writer streaming suites and their
parse, fields and streaming examples against the installed package. It also runs
the Document/Schema suite and example, and compiles the installed TypeScript
consumer with strict NodeNext and Bundler resolution, without the DOM library.
These checks establish local package consistency, not attestation of arbitrary
prebuilt binaries. CI builds the inputs afresh before packaging.

The output directory must be new. The script stages an exact file allowlist,
generates `version.mjs` from `package.json`, and runs
[`npm pack`](https://docs.npmjs.com/cli/v10/commands/npm-pack/) first with
`--dry-run`, then as a local archive. Both calls use `--offline --ignore-scripts`.
The actual archive must contain exactly the expected regular files, with the
expected SHA-256 bytes; missing, extra, duplicate and symlink entries fail.

It then installs the archive into an isolated consumer using offline npm with
scripts, audit and funding requests disabled. The consumer checks every public
export, the independent version, the preserved Core version, WASM asset lookup,
default/explicit loader locations and parsing. The original smoke/parse checks
and the generic field/streaming suites and examples run against the installed
archive. CI also runs the Core-owned Query
fixtures through the installed package's original facade runner.

The check then repeats the install and consumer test in a clean project outside
the checkout. Its path contains a space and a non-ASCII character, its working
directory is that project, and `NODE_*` and `npm_*` settings and the user's home
are not inherited. The TypeScript checks run there, so the checkout's
`node_modules` cannot satisfy them.

[`tests/package_browser.mjs`](../tests/package_browser.mjs) serves the installed
package from a local HTTP server and loads it in headless Chrome, as a module
page using the documented import map and as a module worker. Each loads the WASM
from its adjacent default and from a separate `locateFile` URL, then parses and
encodes a Document. The result records the browser version. CI uses the Chrome
preinstalled on the runner, so its version follows the runner image.

The source checkout is a metadata/build source, not an installable package:
generated `index.mjs`, `version.mjs` and `dist/` live only in the staging area.
Do not pack or install the source root directly. For local experimentation,
install the checked `build/package-check/opentlv-opentlv-<version>.tgz` archive.
The exact archive name, hashes and commands are in `build/package-check/result.json`.

## API and evidence

The [package README](../packaging/README.md) describes each export and asset
location. The four original runtime filenames remain unchanged; API additions
are tracked separately from the immutable migration baseline.
`packaging/index.mjs` re-exports the existing facade and adds `packageVersion`.
The `@opentlv/opentlv/version` subpath exposes that value without loading the facade.
Existing `(await loadOpenTLV()).version` and the C bridge version entry point continue
to identify Core, preserving their migration contract.

`package-info.json` includes binding identity and separate immutable Core source
identity/output hashes. It excludes machine-specific build paths so identical
builds can produce identical packages. Node 22 is the validated runtime; ESM is
the only package module interface. The exact 22-file archive includes five
`.d.mts` declarations, with `types` exports for every JavaScript entry point.
TypeScript 5.9.3 checks both NodeNext and Bundler resolution; this does not
establish bundler runtime compatibility. Browser and worker evidence is the
headless Chrome check above; other browsers, bundlers, CommonJS and CDN support
are not claimed.

The package keeps `license: "MIT"` for original binding code and includes the
root `LICENSE`, `LICENSES/MIT.txt`, `THIRD_PARTY.md` and four upstream `notices/`
files for Core, Emscripten, musl and compiler-rt. The generated `version.mjs`
has the binding's SPDX/author header. Runtime JS/WASM retains its upstream
ownership; the package MIT field does not replace those terms. Missing, empty
or symlinked notices fail staging, and archive/installed-consumer checks verify
their exact bytes. Keep notices with copied runtime assets. See
[dependency attribution](../THIRD_PARTY.md) before changing Core or toolchains.

All [CI tiers](ci.md) run package checks. The double-build tier in Full CI also
compares the complete private archive hash, metadata and file hashes across two
independent builds and uploads the first build's archive as
`js-package-<attempt>`. Package reports keep `published` and `release_verified`
false: they are build results. A passing local run does not establish hosted CI
or a verified release.

## GitHub release

The manual `JS Release` workflow
([js-release.yml](../.github/workflows/js-release.yml)) accepts an unused tag
matching the versions above. Changes stay under `Unreleased` during
development; close the changelog under the matching version without the tag's
`v` prefix and the release date before dispatching the release (for example,
`## [0.1.0] - 2026-10-28`). The release rejects a changelog without that
section. The versioned release notes are the publication text.

1. Review and merge the release preparation. Wait for successful JS Main CI on
   that exact commit. Dispatch `JS Release` on `main` with `tag: v0.1.0`.
2. `scripts/release.py prepare` rejects a missing, unprefixed or otherwise
   malformed tag, a foreign, dirty or non-main checkout, a dispatch from another
   workflow revision, a changed main tip, an existing tag or release, differing
   versions, notes or changelog, a Core lock that is not an exact `v` release
   tag commit (currently Core `v0.8.0`), and missing or failed Main CI,
   including its `JS quality gate` (#34).
3. The workflow then runs [Full CI](ci.md#tiers) in the same attempt: Release and
   Debug, the double-build reproducibility tier, migration compatibility,
   package checks and both quality gates.
4. Assembly revalidates the request and every Full record against the commit,
   run, attempt and Core lock. It copies the exact `opentlv-opentlv-<version>.tgz`
   whose SHA-256 and file hashes the reproduced builds recorded; it does not
   rebuild it. The workflow attests all four assets: the archive,
   `release-manifest.json`, `release-notes.md` and `SHA256SUMS`.
5. Publication rechecks evidence, checksums, attestations and unused tag status,
   then creates the tag and a draft release. Only after the uploaded asset
   names, sizes, SHA-256 digests, notes and tag commit match does it publish the
   draft and verify the public result. It emits `js-published-<attempt>` with
   the URL, source and asset identities.
6. Record the published URL, exact commit, Main and release run links in
   [issue #32](https://github.com/OpenTLV/opentlv-js/issues/32) and
   [Core epic #718](https://github.com/OpenTLV/opentlv/issues/718). Close the
   tracking only after publication and asset verification.

If a failure occurs after creating a tag or draft, inspect that state before
retrying; the workflow refuses to overwrite either. Earlier attempts' artifacts
cannot satisfy a new attempt. A new main commit or Main run requires a new
release attempt. No workflow has a tag-push trigger, so creating or pushing a
tag cannot run checks or publish outside this gated workflow; a regression test
enforces this for every workflow.

Install a downloaded release archive after checking it against `SHA256SUMS`
and its attestation:

```sh
gh attestation verify opentlv-opentlv-<version>.tgz --repo OpenTLV/opentlv-js
npm install ./opentlv-opentlv-<version>.tgz
```

The archive contains the four runtime files, so consumers do not need
Emscripten or Core. `packageVersion` reports `0.1.0`; the existing
`(await loadOpenTLV()).version` reports the embedded Core `0.8.0`.

### Local preparation evidence (2026-10-28)

WSL Ubuntu with Emscripten 4.0.10, Node 22.16.0 and TypeScript 5.9.3 passed the
PR and Main tiers of `scripts/ci.py` against the fetched Core `v0.8.0` pin: all
CTest suites, the Core-owned Query fixtures through the source and installed
facades, the wasm32 Query ABI check and the installed 21-file archive with its
runtime, example and TypeScript checks. Both tiers produced the same archive
SHA-256. The changed migration gate was run on its own against the PR build:
the reconstructed migration sources rebuilt from `ci/migration-core-source.json`
matched all four historical Core outputs. The Python infrastructure suite passed
on Linux and Windows. The Core API report lists 197/197 generic symbols
referenced with 100 exclusions, and the Core pin diff adds or removes no public
symbols.

Full CI (Debug, double build), attestations and publication were not run
locally; they require the hosted release run on the merged commit. Local logs are
under `build/issue32-validation/`; they are not committed release evidence.

## Archive audit (#38)

Audited on 2026-10-30 against an archive built by the local PR tier, then repeated
after the fixes below. Nothing was published.

| Area | Checked on the actual archive | Result |
| --- | --- | --- |
| Contents | `npm pack` inventory, member types, modes and timestamps, machine paths in every file | Exact allowlist, regular files, fixed timestamps, no build paths |
| Metadata | [`publint`](https://publint.dev/) and `npm pkg fix` | `repository.url` needed correcting at publish time; fixed |
| WASM loading | Node from a path needing URL escaping; Chrome with the adjacent default and `locateFile` | Passes |
| ESM exports | Every export, unexported paths, `require()` | Passes; `require()` is rejected as documented and dynamic import works |
| Declarations | [`arethetypeswrong`](https://arethetypeswrong.github.io/) and strict `tsc` | `./opentlv-core.js` had no types and failed with TS7016; fixed. The WASM asset, CommonJS and `node10` results are expected for an ESM-only package |
| Node | Installed suites and examples on Node 22 | Passes |
| Browser | Chrome 156 module page and module worker | Passes; other browsers and bundlers are not tested |
| License | Notices against the Core source and Emscripten 4.0.10 upstream files | Byte-identical |
| Provenance | `package-info.json` against the build; published `v0.1.0` assets | Core commit and output hashes match. `SHA256SUMS` verifies, and the four runtime files equal the local build |
| Publication | Real `npm publish` against an unreachable registry | `EPRIVATE`; a regression test keeps registry tokens out of workflows and scripts and, since #39, allows `npm publish` only in the approved release job |

These checks now run in every CI tier except for the external tools, the
upstream notice comparison, the `v0.1.0` comparison and the `npm publish` refusal,
which were one-off audit steps. The `v0.1.0` attestation was not verified here. It
covers the earlier `opentlv-js` asset, not the renamed archive.

`package-info.json` stays outside the export map; read it from the installed
package directory. Before registry publication, #39 and #40 must:

- Choose a new version, because the `v0.1.0` tag is already used.
- Replace the packaged README's statements that the package is not on the registry
  and its archive-based install instructions.
- Decide whether `engines` stays at `22.x`. Other Node versions are untested and get
  an npm warning, not a refusal.
- Confirm organization-wide 2FA enforcement.

## npm publication

The `npm` input of `JS Release` (#39) publishes the GitHub release archive of the
same run to npm as `@opentlv/opentlv`. Nothing is rebuilt: npm receives the bytes
that Full CI reproduced and tested and that the release attested. Pull requests,
Main, Full and manual Full runs cannot publish.

| Protection | How |
| --- | --- |
| Explicit approval | The `npm` job uses the GitHub environment `npm`, which must require a reviewer, deploy only from `main` and not let administrators bypass it |
| No registry token | npm [trusted publishing](https://docs.npmjs.com/trusted-publishers) accepts an OIDC token only from this repository, `js-release.yml` and the `npm` environment. Besides release attestation, only this job has `id-token: write` |
| Immutable archive | The job publishes `opentlv-opentlv-<version>.tgz` from the release assets after rechecking the manifest, Full evidence, checksums, attestations and the public GitHub release |
| One version, once | npm versions cannot be replaced: a version that npm already has with other bytes fails, and a new version must be newer than `latest` |
| Provenance | npm generates SLSA provenance for trusted publishing from a public repository. The job requires it to name the archive's SHA-512, this workflow on `main`, the release commit and the run |

Preflight rejects `npm: true` before Full CI starts if `package.json` still has
`private: true`, the environment lacks any of its protections, the package does not
exist on npm yet, or the version is not newer than npm's `latest`. Until the
approved publication change removes `private: true`, every npm request therefore
fails. The request records the npm state it saw, so assembly and GitHub
publication fail if that state changes.

After the GitHub release is public, the `npm` job waits for approval. The approved
job then:

1. Installs npm 11.21.1 on Node 22. Trusted publishing needs npm 11.5.1 and
   Node 22.14 or later; npm 12 would need Node 22.22.2.
2. Runs `scripts/publish_npm.py prepare`. It takes the release assets of the
   attempt that published the GitHub release and verifies them as the GitHub
   publication did: request, Full records and gates, checksums, notes and the
   attestation of each asset. The public release and tag must hold exactly these
   assets, the environment must keep its protections, and the run must record an
   approval of `npm`. The archive's `package.json` must name `@opentlv/opentlv`,
   the release version and this repository, without `private`.
3. Runs `npm publish ./build/npm/opentlv-opentlv-<version>.tgz --access public
   --provenance --tag latest --ignore-scripts` against `https://registry.npmjs.org/`.
   If npm already has the version with the same SHA-512 and SHA-1, it publishes
   nothing and only confirms.
4. Runs `scripts/publish_npm.py confirm`. It waits until npm serves the version as
   `latest` with the archive's integrity and provenance, and checks the provenance
   statement. It then installs the version from the registry into a clean project,
   compares the lockfile integrity and runs `npm audit signatures`.
5. Uploads `js-npm-<attempt>` with `plan.json` and `receipt.json`. The receipt
   names the npm URL, GitHub release, commit, run, integrity, provenance run and
   the approving reviewers.

If the approval is rejected or the npm job fails, use **Re-run failed jobs**. The
GitHub release and its tag remain, so a new dispatch of the same tag fails. The
re-run downloads the earlier attempt's assets, verifies them again and asks for
approval again.

### Setup and first version

npm can configure trusted publishing only for an existing package. The maintainer
therefore publishes the first version once, from the attested release asset;
later versions use the workflow:

1. In the repository settings, create the environment `npm`: add a required
   reviewer, disallow administrator bypass, limit deployment branches to the
   single branch rule `main`, and add no secrets or variables.
2. In the approved publication change, remove `private: true`, choose a new
   version and update the packaged README.
3. Dispatch `JS Release` with `npm: false`. After it publishes the GitHub release,
   download its assets and run `sha256sum -c SHA256SUMS` and
   `gh attestation verify opentlv-opentlv-<version>.tgz --repo OpenTLV/opentlv-js`.
   Then publish the archive from an npm account with 2FA:
   `npm publish ./opentlv-opentlv-<version>.tgz --access public`. This version has
   the GitHub attestation but no npm provenance.
4. Check that `npm view @opentlv/opentlv@<version> dist.integrity` equals the
   archive's SHA-512 as `sha512-<base64>`.
5. In the package settings on npmjs.com, add a GitHub Actions trusted publisher
   for `OpenTLV/opentlv-js`, workflow `js-release.yml` and environment `npm`, and
   allow `npm publish`: configurations created since 2026-09-03 allow only staged
   publishing by default. An unused configuration expires after two days, so add
   it shortly before the next npm release. Then select **Require two-factor
   authentication and disallow tokens** under publishing access, and confirm
   that the `opentlv` organization enforces 2FA.
6. Dispatch later releases with `npm: true`.

npm's [staged publishing](https://docs.npmjs.com/staged-publishing) would add an
approval on npmjs.com, but `npm stage publish` packs a directory instead of
publishing a given archive, so the workflow does not use it.

### Local validation (#39)

The Python infrastructure suite covers the environment protections, approvals,
toolchain pins, the assets of the publishing attempt, rejected requests, archives
and registry states, retries with the same or different bytes, provenance
subjects, workflows, commits and runs, and the workflow structure. GitHub and the
registry are mocked. The provenance checks follow the attestation of a published
scoped package (`@sigstore/core`). No environment was created, no trusted
publisher was configured and nothing was published. npm documents publishing a
prebuilt archive, but its trusted publishing documentation does not show it, so
the first workflow publication (#40) verifies that path.

## Separate distribution work

The [distribution follow-up register](distribution-follow-ups.md) tracks npm
publishing, security/advisory procedures and distribution improvements separately
from this migration preparation. None is enabled by this change.
