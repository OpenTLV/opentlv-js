# JS/WASM distribution follow-up register

These open work items are deferred from
[#11](https://github.com/OpenTLV/opentlv-js/issues/11) and must be reviewed during
the [final migration assessment (#14)](https://github.com/OpenTLV/opentlv-js/issues/14).
This versioned register tracks the scope without creating remote issues or
claiming publication readiness. Each item needs a separately approved
implementation before the private-package restriction can change.

Reviewed for #14 on 2026-10-26: publication items remain open. Issue #5 adds
TypeScript declarations and installed consumer checks; runtime distribution
items below remain open. The
[migration assessment](../MIGRATION.md#validation-review-14) records compatibility
and the outstanding coordinated gates; local archive validation does not
complete any publication item.

## NPM-1: Registry publication (open)

- Issue #37 selects `@opentlv/opentlv` in the `opentlv` organization; see
  [Package identity](packaging.md#package-identity). Confirming organization-wide
  2FA enforcement remains open.
- Issue #32 defines release versions, `v`-prefixed tag matching and the GitHub
  release of the tested archive against the pinned Core (`v0.1.0` with Core
  `v0.8.0`); see [GitHub release](packaging.md#github-release). Registry
  dist-tags and prerelease policy remain open.
- Establish authorized publishing identities, trusted publishing or credential
  handling, protected environments and required hosted gates.
- Bind the exact checked archive to repository commit, workflow run/attempt,
  checksum and provenance; establish retention and verification of evidence.
- Review package contents/license obligations and publish/install verification,
  rollback/deprecation policy and registry account recovery.
- Issue #38 records what publication still has to change; see
  [Archive audit](packaging.md#archive-audit-38).
- Remove `private: true` only in the separately reviewed publication change.

## SEC-1: Security and advisory process (open)

- Issue #30 links the shared [private reporting and coordination policy](https://github.com/OpenTLV/.github/blob/main/SECURITY.md).
  Repository settings and component support commitments remain separate.
- Define supported binding/Core versions and component-specific maintenance
  commitments under that shared reporting and advisory process.
- Define dependency/security update handling, affected-version assessment,
  advisory publication and patch/release responsibilities.
- Document the remaining component-specific process without promising a response SLA.

## DIST-1: Distribution improvements (open)

- Issue #38 checks the installed archive in headless Chrome, as a module page and
  a module worker with `locateFile`. Validate other browsers, the full API in
  browsers, bundlers and deployed asset URLs before claiming them.
- Decide CDN/static hosting, source maps and any
  additional module interfaces based on tested consumer requirements.
- Keep wrapper semantics, Core ownership and WASM memory/lifetime contracts;
  coordinate API coverage with [#1](https://github.com/OpenTLV/opentlv-js/issues/1)
  and Docs integration with [#13](https://github.com/OpenTLV/opentlv-js/issues/13).

## MOD-1: Post-migration modernization (open)

- Review Core pin and Emscripten/Node upgrades separately from source extraction.
  Issue #32 moves the Core pin to `v0.8.0`; Emscripten/Node upgrades remain open.
- Replace the historical binary-equality gate deliberately when an intentional
  dependency/runtime change requires it, preserving the immutable baseline and
  adding evidence for the new compatibility contract. For the Core pin change,
  the gate now rebuilds the migration from its own recorded lock
  (`ci/migration-core-source.json`); a toolchain change still needs a reviewed
  replacement.
- Keep API redesign and broader facade coverage separate from the migration's
  behavior-preservation result; remaining browser/worker coverage is tracked under
  DIST-1. TypeScript declarations were added separately in #5.
