# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2026-11-03

### Fixed

- Identify newly created GitHub release drafts by the REST response ID and upload, verify and publish through that ID, avoiding delayed release-list visibility. Recover a failed publishing job from the original run's attested payload, accepting only the exact tag, commit, metadata and asset bytes; reject partial or conflicting drafts and preserve the original Full CI evidence through npm publication. (#47)

### Changed

- Prepare JS `0.2.1` with Core still pinned to `v0.8.0`: close the changelog and write the `v0.2.1` release notes; document direct npm publishing, protected-environment checks, recovery and the outstanding first live OIDC/provenance validation. (#47)

## [0.2.0] - 2026-11-02

### Changed

- Approve the first npm publication of `@opentlv/opentlv` as `0.2.0`: remove `private: true`, which package checks and the installed consumer now reject, close the changelog, write the `v0.2.0` release notes and replace the packaged README's archive-only install with `npm install @opentlv/opentlv`. Add `scripts/publish_npm.py verify`, which checks a published version against its public GitHub release (asset digests, checksums, the Full-tested archive and file hashes, tag commit), the registry metadata, integrity and `latest`, and the npm provenance when present. It then installs the version from npm into a clean consumer for the Node suites and examples, headless Chrome, strict TypeScript NodeNext and Bundler checks and `npm audit signatures`. Only the manually published first version may lack provenance (`--unattested`). (#40)
- Record the npm archive audit of contents, metadata, WASM loading, ESM exports, declarations, Node and browser targets, license notices and provenance, with what publication must still change. The runtime files equal the published `v0.1.0` assets, `private: true` stays and a regression keeps npm publish commands and registry tokens out of workflows and scripts. (#38)
- Select `@opentlv/opentlv` in the `opentlv` npm organization as the package identity, verified against the public registry, and document ownership and public access. Package imports and the release archive `opentlv-opentlv-<version>.tgz` use the new name, while the package stays `private: true` and nothing is published. The `opentlv-js` repository name and the published `v0.1.0` release asset are unchanged. (#37)

### Added

- Add optional npm publication to the `JS Release` workflow (`npm: true`). After the GitHub release of the same run, a job in the protected `npm` environment (required reviewer, `main` only, no administrator bypass) publishes the attested release archive, without rebuilding it, through npm trusted publishing with no registry token. It rechecks the Full evidence, checksums, attestations, the public release and the recorded approval, refuses versions that npm already has with other bytes or that are not newer than `latest`, and confirms the registry integrity, the SLSA provenance of this workflow, commit and run, and `npm audit signatures` from a clean install. Preflight rejects the request before Full CI while the package is `private: true`, so nothing can be published until the approved publication change. The first version and the trusted publisher setup are documented as manual steps. (#39)
- Check the installed npm archive in headless Chrome, as a module page with the import map and as a module worker, and in a clean consumer outside the checkout with no inherited Node or npm settings. Package checks now require Chrome or Chromium. (#38)

### Fixed

- Restrict `publish_npm.py verify --unattested` to `0.2.0`, the manually published first version, and reject it for any other version before downloading anything, so every later version without npm provenance fails verification. (#40)
- Add the missing TypeScript declaration for the `./opentlv-core.js` export, which failed strict consumers with TS7016, and use the `git+https` repository URL that npm otherwise corrects at publish time. The archive now has 22 files. (#38)

## [0.1.0] - 2026-10-28

### Changed

- Require the release preflight to find OpenTLV Core locked to an exact `v`-prefixed release tag commit (Core `v0.8.0`) and reject missing, unprefixed and malformed release tags. Regression tests cover the required `tag` input and keep tag pushes from triggering any workflow, so a tag cannot bypass the release gate or publish twice. (#34)
- Prepare the first standalone JS/WASM release as `0.1.0`, replacing the unreleased `0.1.0-dev.0` development version independently of Core. Pin Core `v0.8.0` at `345c77acb29266036df5f27d04ce315bb61853cc` and keep the migration compatibility gate on the recorded baseline Core lock (`ci/migration-core-source.json`). Full CI now includes the double-build reproducibility tier and uploads its tested npm archive. The manual `JS Release` workflow replaces the tag-triggered reproducibility run: it requires a changelog closed under the release version, Main on the exact commit and same-attempt Full evidence, publishes that archive with release notes, evidence, checksums and attestations to GitHub Releases, and verifies the tag, notes and uploaded assets before publishing. npm registry publication remains separate. (#32)
- Correct original-author copyright attribution, add exact-path REUSE coverage and pinned contributor checks, preserve upstream runtime notices in private npm archives, and link shared community/security policies. (#30)
- Use Ninja provided by the Ubuntu CI runner and verify its availability without refreshing APT package indexes. (#7)
- Own the private Query/Schema adapters and remaining WASM guide content; build against Core without its removed `bindings/` tree while retaining immutable migration provenance. (OpenTLV/opentlv#698)
- Normalize the standalone layout into `src/`, `native/`, `tests/`, `examples/` and `cmake/`, with build outputs in `<build>/dist/`; preserve public imports and immutable migration provenance. (#12)

### Added

- Complete the generic API review with Core-backed scalar ValueConstraint and Tag operations, exact 64-bit inputs, binding/package/type regressions and per-header functional coverage with justified exclusions. (#7)
- Complete generic value and structure Codec APIs, Schema-number composition and deterministic wire Generator with copied diagnostics, exact 64-bit values, TypeScript declarations and binding/package regressions. (#6)
- Complete owned Document construction, insertion, lookup, source locations, encoding and incremental building; add contextual Query evaluation/editing, structural Schema validation with copied reports, TypeScript package declarations and binding/consumer regressions. (#5)
- Expose owned Reader/Writer and tree streaming APIs with incremental windows, resumable visitors, balanced events, bounded output, exact tree measurement, structured diagnostics and binding/package regressions. (#4)
- Expose owned generic field encodings, mixed/tag-only, Variable, Escaped and Packed Format composition, direct decode/measure/encode/preserve operations and binding regressions; retain immutable migration provenance separately from reviewed API additions. (#3)
- Report exact pinned Core API symbol references in CI, with separate generic/Builtins inventories, per-header gaps, justified exclusions and PR Core-pin diffs; keep coverage informational. (#2)
- Validate migration compatibility by rebuilding the immutable Core baseline in Full/Release CI, comparing emitted WASM/JS contracts and all four output hashes; record cross-repository evidence and remaining acceptance gates. (#14)
- Own the migrated WASM manual and versioned example catalog, with attempt-bound Main documentation notifications and standalone Docs portal integration. (#13)
- Add independent private JS package version metadata, explicit ESM/asset exports, offline archive and installed-consumer checks in every CI tier, package reproducibility and separate distribution follow-up tracking without publishing. (#11)
- Add JS-owned PR/Main/Full CI and tag-triggered double-build reproducibility with pinned Emscripten/Node, preserved smoke/facade checks, verified Core-owned Query/ABI inputs and per-run evidence. (#10)
- Add a standalone Emscripten 4.0.10 build with a pinned, checksum-verified Core dependency, explicit sibling development override and preserved WASM outputs. (#9)
- Import the existing WASM bridge, JavaScript wrappers, tests, parse example and CMake definition from the recorded Core baseline, with repeatable source/API parity verification. (#8)
- Record immutable Core provenance, source mapping and ownership for the behavior-preserving WASM/JavaScript migration. (OpenTLV/opentlv#697)
