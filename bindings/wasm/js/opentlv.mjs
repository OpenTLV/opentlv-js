// Browser and Node.js entry point of the experimental OpenTLV WebAssembly build.
//
//   import { loadOpenTLV, hexToBytes } from "./opentlv.mjs";
//   const opentlv = await loadOpenTLV();
//   const result = opentlv.parse(hexToBytes("6F 0A 84 03 41 42 43 A5 03 50 01 01"), { format: "ber" });
//
// All parsing happens in the OpenTLV C core; this file only moves bytes in and
// the JSON result out. Parse failures are reported in `result.error`, they are
// not thrown.
import createOpenTLV from "./opentlv-core.js";
import { queryFacade } from "./query.mjs";

/** Formats the module can parse (a build may compile out some of them). */
export const FORMATS = Object.freeze(["fixed", "bluetooth-ltv", "bluetooth-ad", "ber", "der", "cer", "lldp", "emv", "nfc-type2"]);

/** Modules that annotate elements with known tag names ("none" adds nothing). */
export const MODULES = Object.freeze(["none", "emv"]);

/**
 * Converts hexadecimal text to bytes. Whitespace is ignored; an optional "0x"
 * prefix is not accepted. Throws a TypeError for invalid or odd-length input.
 */
export function hexToBytes(text) {
  const digits = String(text).replace(/\s+/g, "");
  if (!/^(?:[0-9a-fA-F]{2})*$/.test(digits)) {
    throw new TypeError("expected an even number of hexadecimal digits");
  }
  const bytes = new Uint8Array(digits.length / 2);
  for (let i = 0; i < bytes.length; i += 1) {
    bytes[i] = parseInt(digits.slice(i * 2, i * 2 + 2), 16);
  }
  return bytes;
}

/**
 * Loads the WebAssembly module.
 *
 * @param {object} [moduleOptions] Passed to the Emscripten factory, e.g.
 *   `{ locateFile: (name) => "/static/" + name }` to serve the .wasm file
 *   from another location.
 * @returns {Promise<{version: string, formats: readonly string[], modules: readonly string[], parse: Function}>}
 */
export async function loadOpenTLV(moduleOptions = {}) {
  const wasm = await createOpenTLV(moduleOptions);

  // Copies `size` bytes into module memory; the caller frees the result.
  function allocate(size) {
    const pointer = wasm._opentlv_wasm_alloc(size);
    if (!pointer) throw new Error("OpenTLV: out of memory");
    return pointer;
  }

  const api = {
    version: wasm.UTF8ToString(wasm._opentlv_wasm_version()),

    /**
     * Parses `bytes` and returns
     * `{ format, module?, elements: [{ offset, depth, tag, length, headerSize, constructed,
     * value | children, symbol?, name?, lengthValid? }], error? }`.
     * Bluetooth modes add AD Type names. "bluetooth-ad" validates container padding
     * and adds `padding: { offset, length }` when present; "bluetooth-ltv" stays strict.
     * `error` is `{ code, message, offset }` and comes with every element read
     * before the failure. Tags and values are uppercase hexadecimal strings.
     * An element spans `encodedSize` bytes starting at `offset`.
     * `source` contains absolute {offset, length} ranges for header, tag, length,
     * value and trailer; logical value length excludes the trailer.
     *
     * @param {Uint8Array} bytes
     * @param {{format?: string, module?: string, fixedTagSize?: number,
     *   fixedLengthSize?: number, fixedByteOrder?: "big"|"little",
     *   fixedElementOrder?: "tlv"|"ltv", fixedLengthScope?: "value"|"tag-and-value"}} [options] `format`
     *   defaults to "ber"; `module` ("none" or "emv") defaults to "none".
     *   `fixedTagSize`, `fixedLengthSize` (1-8) and `fixedByteOrder` configure
     *   `format: "fixed"`'s tag width, length width and length byte order
     *   (`tlv_fixed_format_t`). `fixedElementOrder` defaults to "tlv" and
     *   `fixedLengthScope` to "value". These options apply only to Fixed.
     */
    parse(bytes, { format = "ber", module = "none", fixedTagSize = 1, fixedLengthSize = 1,
                  fixedByteOrder = "big", fixedElementOrder = "tlv", fixedLengthScope = "value" } = {}) {
      if (!(bytes instanceof Uint8Array)) throw new TypeError("bytes must be a Uint8Array");
      if (format === "fixed" && (
        !Number.isSafeInteger(fixedTagSize) || fixedTagSize < 1 || fixedTagSize > 0xffffffff ||
        !Number.isInteger(fixedLengthSize) || fixedLengthSize < 1 || fixedLengthSize > 8 ||
        !["big", "little"].includes(fixedByteOrder) ||
        !["tlv", "ltv"].includes(fixedElementOrder) ||
        !["value", "tag-and-value"].includes(fixedLengthScope))) {
        throw new TypeError("Invalid Fixed configuration: positive tag width, length width 1-8, and valid byte order, field order and length scope required");
      }
      const formatSize = wasm.lengthBytesUTF8(format) + 1;
      const moduleSize = wasm.lengthBytesUTF8(module) + 1;
      const input = allocate(bytes.length);
      let name = 0;
      let moduleName = 0;
      let result = 0;
      try {
        name = allocate(formatSize);
        moduleName = allocate(moduleSize);
        // HEAPU8 is re-read on every use: it is replaced when memory grows.
        wasm.HEAPU8.set(bytes, input);
        wasm.stringToUTF8(format, name, formatSize);
        wasm.stringToUTF8(module, moduleName, moduleSize);
        result = wasm._opentlv_wasm_parse(input, bytes.length, name, moduleName, fixedTagSize,
                                            fixedLengthSize, fixedByteOrder === "big" ? 1 : 0,
                                            fixedElementOrder === "ltv" ? 1 : 0,
                                            fixedLengthScope === "tag-and-value" ? 1 : 0);
        if (!result) throw new Error("OpenTLV: out of memory");
        const json = wasm.UTF8ToString(
          wasm._opentlv_wasm_result_json(result),
          wasm._opentlv_wasm_result_json_size(result),
        );
        return JSON.parse(json);
      } finally {
        if (result) wasm._opentlv_wasm_result_free(result);
        if (moduleName) wasm._opentlv_wasm_free(moduleName);
        if (name) wasm._opentlv_wasm_free(name);
        wasm._opentlv_wasm_free(input);
      }
    },
  };
  api.formats = Object.freeze(FORMATS.filter(format => !api.parse(new Uint8Array(0), { format }).error));
  api.modules = Object.freeze(api.parse(new Uint8Array(0), { format: "ber", module: "emv" }).error
    ? ["none"] : ["none", "emv"]);
  Object.assign(api, queryFacade(wasm));
  return api;
}
