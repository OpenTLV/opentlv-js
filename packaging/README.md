# OpenTLV JavaScript / WebAssembly

Experimental JavaScript facade and WebAssembly bridge for
[OpenTLV](https://github.com/OpenTLV/opentlv-js). This is a **private local test
package**, not an npm release. `opentlv-js` is the repository/local package
identity; it does not reserve or promise a registry name or scope.

## Usage

After installing a locally prepared archive into a Node 22 project:

```js
import { loadOpenTLV, hexToBytes, packageVersion } from "opentlv-js";

const tlv = await loadOpenTLV();
console.log(packageVersion); // Independent JS package version.
console.log(tlv.version);    // Existing API: embedded Core version.
console.log(tlv.parse(hexToBytes("6F 03 84 01 41"), { format: "ber" }));
```

Read the binding version without importing the WASM loader:

```js
import { packageVersion } from "opentlv-js/version";
```

The package root exports `loadOpenTLV`, `hexToBytes`, `FORMATS`, `MODULES` and
`packageVersion`. Existing modules are also available as explicit subpaths:

| Import | Contract |
| --- | --- |
| `opentlv-js/opentlv.mjs` | Original JavaScript facade, unchanged |
| `opentlv-js/query.mjs` | Original `queryFacade(wasm)` factory |
| `opentlv-js/opentlv-core.js` | Default Emscripten `createOpenTLV` factory |
| `opentlv-js/opentlv-core.wasm` | Binary asset URL/path, not a JavaScript module |
| `opentlv-js/version` | Independent `packageVersion` constant |
| `opentlv-js/package.json` | Package metadata |

ESM is the supported module interface. There are no CommonJS entry points.
TypeScript declarations cover the loaded API, including Document, Query and
Schema; strict installed consumers are checked with TypeScript 5.9.3.
The tested runtime is Node 22. The generated loader
retains web/worker/Node flags, but this package check does not establish browser,
worker or bundler compatibility.

The four original outputs are adjacent in `dist/`. The default loader locates
`opentlv-core.wasm` beside `opentlv-core.js`; preserve that arrangement when
copying assets. `loadOpenTLV({ locateFile: name => "/assets/" + name })` can select
another served location. In Node ESM, use
`import.meta.resolve("opentlv-js/opentlv-core.wasm")` to obtain the asset URL.
Browsers need relative URLs or an import map; package export maps are not a
browser module resolver.

## Identity and limits

`package.json` owns the independent JS version; `CHANGELOG.md` records JS
changes. The existing `tlv.version` and `_opentlv_wasm_version()` retain their
Core-version meaning. `package-info.json` records the selected Core commit,
source checksum, version inputs and hashes of the four outputs separately.
It explicitly sets `release_verified: false`; it is build information, not
release attestation.

The package has no runtime npm dependencies or lifecycle hooks and remains
`private: true`. Registry publishing, security/advisory procedures and
distribution improvements are deferred in the repository's
[follow-up register](https://github.com/OpenTLV/opentlv-js/blob/main/docs/distribution-follow-ups.md).
See the repository's
[packaging guide](https://github.com/OpenTLV/opentlv-js/blob/main/docs/packaging.md)
for the local preparation and validation commands.

## License

[MIT](LICENSE). Core and transferred source copyright notices are retained.
