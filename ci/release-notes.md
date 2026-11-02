# OpenTLV JS v0.2.0

First npm registry release: the JavaScript/WebAssembly package is published as
**`@opentlv/opentlv`** in the `opentlv` npm organization, versioned
independently of Core. Install it with `npm install @opentlv/opentlv`.

- Renames the package from `opentlv-js`: imports, including every subpath, now
  use `@opentlv/opentlv`. The exported API is unchanged from v0.1.0.
- Builds OpenTLV Core **v0.8.0** from the same exact source commit as v0.1.0,
  `345c77acb29266036df5f27d04ce315bb61853cc`.
- Adds the missing TypeScript declaration for the `./opentlv-core.js` export,
  which strict consumers rejected with TS7016.
- Requires Node 22 and ES modules. Built with Emscripten 4.0.10; installed
  consumers are type-checked with TypeScript 5.9.3 (NodeNext and Bundler).
  Package checks also load the archive in headless Chrome, as a module page
  and a module worker.
- Distributes the reproduced and tested archive `opentlv-opentlv-0.2.0.tgz`,
  release evidence and SHA-256 checksums through GitHub Releases. npm serves
  these same bytes. See
  [packaging](https://github.com/OpenTLV/opentlv-js/blob/v0.2.0/docs/packaging.md).

This first registry version is published by the maintainer from the attested
release archive, so it has the GitHub attestation but no npm provenance. Later
versions are published by the release workflow with npm provenance. Other
browsers and bundlers are not validated. Symbol references do not prove
functional parity, and Builtins-specific parity remains outside this release.
