# Dependencies and attribution

Original contributions by Marek Cingel retain his copyright under the root
[MIT license](LICENSE). OpenTLV is a GitHub organization, not a separate legal
copyright holder. Other contributors retain their notices and years; MIT
contributions do not assign copyright.

## Core and generated runtime

Core is fetched at the immutable revision in `cmake/core-source.json` and linked
statically into `opentlv-core.wasm`. It is not vendored in this source checkout.
The package includes the unchanged [Core license](notices/core-LICENSE.txt) from
`a9a6f9470c2b285744738b40196bef9d0341fead`. It is byte-identical to `LICENSE` at
the current Core `v0.8.0` pin (`345c77acb29266036df5f27d04ce315bb61853cc`).
Recheck it whenever the pin changes. Migration source identities remain
in `migration/source-inventory.json`; later source changes are checked separately
by `ci/source-evolution.json`.

The Emscripten 4.0.10 toolchain generates `opentlv-core.js` and links runtime code
into WASM. These outputs include upstream contributions, so they must not receive
a blanket Marek Cingel copyright annotation. The following notices are copied
unchanged from Emscripten commit `d7b4130688bfa348392b921ab04015aa15c4f154`
([4.0.10 source](https://github.com/emscripten-core/emscripten/tree/4.0.10)):

| Packaged notice | Upstream path | Terms described by upstream |
| --- | --- | --- |
| [Emscripten](notices/emscripten-LICENSE.txt) | `LICENSE` | MIT or NCSA; also retains Node contributor notices |
| [musl](notices/musl-COPYRIGHT.txt) | `system/lib/libc/musl/COPYRIGHT` | MIT for musl as a whole; lists file-specific third-party origins |
| [compiler-rt](notices/compiler-rt-LICENSE.txt) | `system/lib/compiler-rt/LICENSE.TXT` | Apache-2.0 with LLVM exception and legacy MIT/NCSA terms |

The default allocator is Emscripten's adapted dlmalloc. Its upstream
`system/lib/dlmalloc.c` identifies Doug Lea's version 2.8.6 (2012) as public domain
with a CC0 reference; Emscripten's adaptations retain the toolchain's terms.
The notices describe upstream components, not a claim that every upstream source
file is linked. Toolchain, Core, allocator or optional library changes require a
fresh review of linked inputs and their file-specific redistribution notices.
Do not treat the package's MIT metadata as relicensing third-party runtime code.

## Source and package coverage

`REUSE.toml` uses exact paths for reviewed metadata, documentation and four
migrated files without inline notices. It leaves their original bytes intact.
New source files need accurate headers or narrowly scoped annotations; new
vendor or generated paths do not inherit the original author's attribution.
Upstream notice files have their own separate annotations.

Build directories, fetched Core/toolchain sources, staged packages and generated
JS/WASM stay in ignored `build*` directories. They are not part of source REUSE
coverage. The generated `version.mjs` carries the binding's MIT/author header;
copied JS/TypeScript files retain their source notices. Do not edit generated
binaries or prepend headers to the Emscripten loader manually.

Every private npm archive includes `LICENSE`, `LICENSES/MIT.txt`, this document
and the four `notices/` files. Packaging checks require their exact source bytes
in the staged tree, actual archive and installed consumer. Keep these notices
with redistributed JS/WASM assets. `LICENSES/MIT.txt` is REUSE's standard text;
the root license carries the original author's notice. Repository REUSE metadata
describes source paths and is not copied into the differently laid-out npm tree.

## Development tools

Node/npm, TypeScript, Emscripten/LLVM, Python, CMake, Ninja and Git retain their
upstream licenses. Pinned pre-commit, REUSE, Markdownlint and hook versions live
in `requirements-dev.txt` and `.pre-commit-config.yaml`; CI also uses actionlint
and the actions declared in `.github/workflows/`. These tools are not npm runtime
dependencies. There is no vendored third-party source tree in this repository;
the `notices/` directory contains only redistributed license/attribution texts.
