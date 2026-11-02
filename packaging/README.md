# OpenTLV JavaScript / WebAssembly

Experimental JavaScript facade and WebAssembly bridge for
[OpenTLV](https://github.com/OpenTLV/opentlv-js), published on npm as
`@opentlv/opentlv`. Each version's archive, release evidence and checksums are
also attached to its
[GitHub release](https://github.com/OpenTLV/opentlv-js/releases).

## Usage

Install the package into a Node 22 project:

```sh
npm install @opentlv/opentlv
```

```js
import { loadOpenTLV, hexToBytes, packageVersion } from "@opentlv/opentlv";

const tlv = await loadOpenTLV();
console.log(packageVersion); // Independent JS package version.
console.log(tlv.version);    // Existing API: embedded Core version.
console.log(tlv.parse(hexToBytes("6F 03 84 01 41"), { format: "ber" }));
```

Read the binding version without importing the WASM loader:

```js
import { packageVersion } from "@opentlv/opentlv/version";
```

The package root exports `loadOpenTLV`, `hexToBytes`, `FORMATS`, `MODULES` and
`packageVersion`. Existing modules are also available as explicit subpaths:

| Import | Contract |
| --- | --- |
| `@opentlv/opentlv/opentlv.mjs` | Original JavaScript facade, unchanged |
| `@opentlv/opentlv/query.mjs` | Original `queryFacade(wasm)` factory |
| `@opentlv/opentlv/opentlv-core.js` | Default Emscripten `createOpenTLV` factory |
| `@opentlv/opentlv/opentlv-core.wasm` | Binary asset URL/path, not a JavaScript module |
| `@opentlv/opentlv/version` | Independent `packageVersion` constant |
| `@opentlv/opentlv/package.json` | Package metadata |

ESM is the supported module interface. There are no CommonJS entry points.
TypeScript declarations cover the loaded API, including Document, Query and
Schema, and the low-level `createOpenTLV` factory; strict installed consumers are
checked with TypeScript 5.9.3.
The tested runtime is Node 22. Package checks also load this archive in headless
Chrome, as a module page with an import map and as a module worker, covering WASM
loading, parsing and Document encoding. Other browsers and bundlers are not tested
or claimed.

The four original outputs are adjacent in `dist/`. The default loader locates
`opentlv-core.wasm` beside `opentlv-core.js`; preserve that arrangement when
copying assets. `loadOpenTLV({ locateFile: name => "/assets/" + name })` can select
another served location. In Node ESM, use
`import.meta.resolve("@opentlv/opentlv/opentlv-core.wasm")` to obtain the asset URL.
Browsers need relative URLs or an import map; package export maps are not a
browser module resolver.

## Identity and limits

`package.json` owns the independent JS version; `CHANGELOG.md` records JS
changes. The existing `tlv.version` and `_opentlv_wasm_version()` retain their
Core-version meaning. `package-info.json` records the selected Core commit,
source checksum, version inputs and hashes of the four outputs separately.
It explicitly sets `release_verified: false`; it is build information, not
release attestation. GitHub release assets have separate build provenance
attestations and a `release-manifest.json` with the hosted evidence. npm serves
the same archive bytes. Versions published by the release workflow also have
npm provenance; the first registry version, 0.2.0, was published from the
attested archive without it.

The package has no runtime npm dependencies or lifecycle hooks. Component
support commitments and distribution improvements are tracked in the
repository's
[follow-up register](https://github.com/OpenTLV/opentlv-js/blob/main/docs/distribution-follow-ups.md).
See the repository's
[packaging guide](https://github.com/OpenTLV/opentlv-js/blob/main/docs/packaging.md)
for the local preparation, release and verification commands.

## License

[MIT](LICENSE) for original binding code, copyright Marek Cingel.
The archive includes `LICENSES/MIT.txt` and [dependency attribution](THIRD_PARTY.md)
with unchanged Core, Emscripten, musl and compiler-rt notices in `notices/`.
Keep these files with redistributed JS/WASM assets; the package's MIT field
does not replace third-party runtime terms.

Use the shared [contribution guidelines](https://github.com/OpenTLV/.github/blob/main/CONTRIBUTING.md),
[Code of Conduct](https://github.com/OpenTLV/.github/blob/main/CODE_OF_CONDUCT.md)
and [private security reporting policy](https://github.com/OpenTLV/.github/blob/main/SECURITY.md).
