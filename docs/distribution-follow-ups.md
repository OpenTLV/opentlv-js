# JS/WASM distribution follow-up register

These open work items are deferred from
[#11](https://github.com/OpenTLV/opentlv-js/issues/11) and must be reviewed during
the [final migration assessment (#14)](https://github.com/OpenTLV/opentlv-js/issues/14).
This versioned register tracks the scope without creating remote issues or
claiming publication readiness. Each item needs a separately approved
implementation before the private-package restriction can change.

Reviewed for #14 on 2026-10-26: all items remain open. The
[migration assessment](../MIGRATION.md#validation-review-14) records compatibility
and the outstanding coordinated gates; local archive validation does not
complete any publication item.

## NPM-1: Registry publication (open)

- Decide and verify registry name/scope ownership; the local `opentlv-js` name
  is not a registry reservation or availability claim.
- Define release versions, tag matching, prerelease/dist-tag policy and the
  relationship to pinned Core compatibility metadata.
- Establish authorized publishing identities, trusted publishing or credential
  handling, protected environments and required hosted gates.
- Bind the exact checked archive to repository commit, workflow run/attempt,
  checksum and provenance; establish retention and verification of evidence.
- Review package contents/license obligations and publish/install verification,
  rollback/deprecation policy and registry account recovery.
- Remove `private: true` only in the separately reviewed publication change.

## SEC-1: Security and advisory process (open)

- Define supported binding/Core versions, private reporting channels, triage
  ownership and coordinated advisories across the JS bridge and native Core.
- Define dependency/security update handling, affected-version assessment,
  advisory publication and patch/release responsibilities.
- Document the reviewed process without implying that this migration provides
  an existing response SLA or public reporting contact.

## DIST-1: Distribution improvements (open)

- Validate browsers, workers, bundlers and asset URL deployment before claiming
  those package environments are supported.
- Decide CDN/static hosting, source maps, TypeScript declarations and any
  additional module interfaces based on tested consumer requirements.
- Keep wrapper semantics, Core ownership and WASM memory/lifetime contracts;
  coordinate API coverage with [#1](https://github.com/OpenTLV/opentlv-js/issues/1)
  and Docs integration with [#13](https://github.com/OpenTLV/opentlv-js/issues/13).

## MOD-1: Post-migration modernization (open)

- Review Core pin and Emscripten/Node upgrades separately from source extraction.
- Replace the historical binary-equality gate deliberately when an intentional
  dependency/runtime change requires it, preserving the immutable baseline and
  adding evidence for the new compatibility contract.
- Keep API redesign and broader facade coverage separate from the migration's
  behavior-preservation result; TypeScript and browser/worker coverage remain
  tracked under DIST-1.
