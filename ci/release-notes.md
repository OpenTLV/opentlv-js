# OpenTLV JS v0.2.1

Release recovery fixes for **`@opentlv/opentlv`**, versioned independently of
OpenTLV Core. Install with `npm install @opentlv/opentlv`.

- Uses the exact GitHub release ID returned when creating a draft, so delayed
  release-list visibility no longer prevents publication.
- Allows a failed publishing job to resume with the original attested assets
  and Full CI evidence. Conflicting tags, partial uploads, altered notes and
  different asset bytes stop recovery without replacing or deleting anything.
- Keeps the JavaScript API and pinned Core **v0.8.0** source commit
  `345c77acb29266036df5f27d04ce315bb61853cc` unchanged.
- Preserves Node 22, Emscripten 4.0.10, TypeScript 5.9.3, installed-consumer,
  headless Chrome page/worker and double-build reproducibility checks.
- Retains direct npm publication of the attested archive through the protected
  `npm` environment. Staged npm publishing is not implemented.

The release workflow is to publish this version to npm through trusted
publishing (OIDC, no registry token), the first time it does so; npm is then
expected to list its SLSA provenance. The `0.2.0` exception for a version
without provenance does not apply: verification fails if provenance is missing.
Verify the npm version with
[`scripts/publish_npm.py verify`](https://github.com/OpenTLV/opentlv-js/blob/v0.2.1/docs/packaging.md#verify-a-published-version).
