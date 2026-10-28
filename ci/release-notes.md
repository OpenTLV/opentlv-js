# OpenTLV JS v0.1.0

First standalone JavaScript/WebAssembly release: `opentlv-js` is versioned as
**0.1.0**, independently of Core. The unreleased `0.1.0-dev.0` development
identity is not a previous JS release.

- Builds OpenTLV Core **v0.8.0** from its exact source commit
  `345c77acb29266036df5f27d04ce315bb61853cc`, verified against the commit,
  tree, build-input SHA-256 and Git version inputs in `cmake/core-source.json`.
- Includes the JavaScript facade and WebAssembly bridge with Format and field
  composition, Reader/Writer and tree streaming, Document, Query, Schema,
  generic Codec, StructureCodec and deterministic Generator APIs, and
  TypeScript declarations.
- Requires Node 22 and ES modules. Built with Emscripten 4.0.10; installed
  consumers are type-checked with TypeScript 5.9.3 (NodeNext and Bundler).
- Distributes the reproduced and tested npm archive `opentlv-js-0.1.0.tgz`,
  release evidence and SHA-256 checksums through GitHub Releases. Install it
  with `npm install ./opentlv-js-0.1.0.tgz`. The archive contains the four
  runtime files and the Core, Emscripten, musl and compiler-rt notices. See
  [packaging](https://github.com/OpenTLV/opentlv-js/blob/v0.1.0/docs/packaging.md).

npm registry publication remains a separate follow-up; the package stays
`private`. Browser, worker and bundler environments are not validated. Symbol
references do not prove functional parity, and Builtins-specific parity remains
outside this release.
