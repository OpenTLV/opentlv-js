// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel

#ifndef OPENTLV_WASM_H
#define OPENTLV_WASM_H
#include <tlv/query/program.h>

/*
 * Browser-facing boundary of the experimental OpenTLV WebAssembly build.
 *
 * A thin wrapper over the OpenTLV C API: it parses nothing itself. Callers copy
 * the input into memory obtained from opentlv_wasm_alloc(), call
 * opentlv_wasm_parse(), read the JSON document from the result and release
 * everything again. bindings/wasm/js/opentlv.mjs does this for JavaScript callers.
 *
 * The JSON document has the shape
 *
 *   {"format": "ber", "module": "emv",
 *    "elements": [{"offset": 0, "depth": 0, "tag": "6F", "length": 10,
 *                  "headerSize": 2, "constructed": true,
 *                  "symbol": "fci_template", "name": "FCI Template",
 *                  "lengthValid": true, "children": [ ... ]},
 *                 {"offset": 2, "depth": 1, "tag": "84", "length": 3,
 *                  "headerSize": 2, "constructed": false, "value": "414243"}],
 *    "error": {"code": 3, "message": "...", "offset": 12}}
 *
 * "error" is present only on failure; "elements" then holds every element
 * that was read before the error. Only BER, DER and CER elements can be
 * constructed. Tags and values are uppercase hexadecimal. An element occupies
 * "encodedSize" bytes starting at "offset", including its trailer. "source"
 * gives absolute {offset, length} ranges for header, tag, length, value and
 * trailer. "headerSize" and logical value "length" exclude the trailer.
 * "tag" holds the identifier bytes.
 * Bluetooth modes also add known AD Type names. "bluetooth-ad" validates
 * trailing zero padding and reports "padding": {"offset", "length"} when present.
 * "bluetooth-ltv" retains strict framing. Values remain opaque in both modes.
 * "module", "symbol" and "lengthValid" appear only
 * when a module was requested (and "symbol", "name" only for tags it knows).
 */

#include <stddef.h>
#include <stdint.h>

#ifdef __EMSCRIPTEN__
#include <emscripten/emscripten.h>
#define OPENTLV_WASM_API EMSCRIPTEN_KEEPALIVE
#else
#define OPENTLV_WASM_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* Canonical program-lifetime descriptions for native and facade-originated failures. */
OPENTLV_WASM_API const char* opentlv_wasm_strerror(int code);
OPENTLV_WASM_API const char* opentlv_wasm_query_error_kind_string(int kind);
/* Program-lifetime JSON {"result":{NAME:code},"query_error":{NAME:kind}} taken from the C
 * enums, so JavaScript never hard-codes result values; NULL on allocation failure. */
OPENTLV_WASM_API const char* opentlv_wasm_constants(void);

/* Opaque parse result; release it with opentlv_wasm_result_free(). */
typedef struct opentlv_wasm_result opentlv_wasm_result_t;

/* Owning Query facade handles. Programs and executions have independent
 * reference-counted lifetimes; all processing delegates to the C Query engine.
 * Returned JSON strings borrow the handle until its next operation. */
typedef struct opentlv_wasm_program   opentlv_wasm_program_t;
typedef struct opentlv_wasm_execution opentlv_wasm_execution_t;
typedef struct opentlv_wasm_document  opentlv_wasm_document_t;
typedef struct opentlv_wasm_format    opentlv_wasm_format_t;
typedef struct opentlv_wasm_v1        opentlv_wasm_v1_t;
OPENTLV_WASM_API opentlv_wasm_v1_t*   opentlv_wasm_v1_new(const char*, size_t);
OPENTLV_WASM_API const char* opentlv_wasm_v1_operation(opentlv_wasm_v1_t*, int, const uint8_t*,
                                                       size_t, size_t);
OPENTLV_WASM_API void        opentlv_wasm_v1_free(opentlv_wasm_v1_t*);
OPENTLV_WASM_API opentlv_wasm_format_t* opentlv_wasm_format_new(const char*, size_t, size_t, int,
                                                                int, int);
OPENTLV_WASM_API int    opentlv_wasm_format_callbacks(opentlv_wasm_format_t*, tlv_decode_fn,
                                                      tlv_measure_fn, tlv_encode_fn,
                                                      tlv_is_constructed_fn);
OPENTLV_WASM_API void   opentlv_wasm_format_free(opentlv_wasm_format_t*);
OPENTLV_WASM_API int    opentlv_wasm_format_decoded(opentlv_wasm_format_t*, tlv_decoded_t*,
                                                    const uint8_t*, size_t, const uint8_t*, size_t,
                                                    const uint32_t*);
OPENTLV_WASM_API size_t opentlv_wasm_element_field(const tlv_element_t*, int);
OPENTLV_WASM_API size_t opentlv_wasm_tag_field(const tlv_tag_t*, int);
OPENTLV_WASM_API void   opentlv_wasm_integer_write(int64_t*, uint32_t, uint32_t);
OPENTLV_WASM_API int    opentlv_wasm_encoding_write(tlv_encoding_t*, size_t, size_t, size_t);
OPENTLV_WASM_API void   opentlv_wasm_size_write(size_t*, size_t);
OPENTLV_WASM_API opentlv_wasm_program_t* opentlv_wasm_program_with_format(opentlv_wasm_format_t*);
OPENTLV_WASM_API int
opentlv_wasm_program_tags(opentlv_wasm_program_t*, uint32_t,
                          tlv_result_t (*)(const void*, const tlv_tag_t*, int64_t*),
                          tlv_result_t (*)(const void*, const tlv_tag_t*, int64_t*));
OPENTLV_WASM_API int opentlv_wasm_program_resolver(opentlv_wasm_program_t*, tlv_query_resolve_t);
/* Use the native EMV registry resolver; unsupported when EMV is compiled out. */
OPENTLV_WASM_API int opentlv_wasm_program_emv_resolver(opentlv_wasm_program_t*);
OPENTLV_WASM_API int opentlv_wasm_resolved_tag(opentlv_wasm_program_t*, tlv_tag_t*, const uint8_t*,
                                               size_t);
OPENTLV_WASM_API opentlv_wasm_program_t* opentlv_wasm_program_new(const char* format);
OPENTLV_WASM_API int opentlv_wasm_program_variable(opentlv_wasm_program_t*, const char*, int);
OPENTLV_WASM_API int opentlv_wasm_program_name(opentlv_wasm_program_t*, const char*, const uint8_t*,
                                               size_t);
OPENTLV_WASM_API int opentlv_wasm_program_option(opentlv_wasm_program_t*, int, size_t);
/* Install one closed conversion callback before compilation. Integer/string
 * result helpers avoid exposing private native struct layout to JavaScript. */
OPENTLV_WASM_API int  opentlv_wasm_program_provider(opentlv_wasm_program_t*, int, uint32_t, size_t,
                                                    tlv_query_decode_t);
OPENTLV_WASM_API void opentlv_wasm_provider_integer(tlv_query_result_t*, uint32_t, uint32_t);
OPENTLV_WASM_API void opentlv_wasm_provider_text(tlv_query_result_t*, const uint8_t*, size_t);
OPENTLV_WASM_API size_t      opentlv_wasm_provider_event(const tlv_tree_event_t*, int);
OPENTLV_WASM_API const char* opentlv_wasm_program_compile(opentlv_wasm_program_t*, const uint8_t*,
                                                          size_t, int);
OPENTLV_WASM_API const char* opentlv_wasm_program_render(opentlv_wasm_program_t*, int);
OPENTLV_WASM_API const uint8_t* opentlv_wasm_program_image(opentlv_wasm_program_t*);
OPENTLV_WASM_API size_t         opentlv_wasm_program_image_size(opentlv_wasm_program_t*);
OPENTLV_WASM_API void           opentlv_wasm_program_free(opentlv_wasm_program_t*);
OPENTLV_WASM_API void           opentlv_wasm_program_retain(opentlv_wasm_program_t*);
OPENTLV_WASM_API const char* opentlv_wasm_schema_validate(opentlv_wasm_program_t*, const uint32_t*,
                                                          const uint32_t*, size_t,
                                                          opentlv_wasm_document_t*, const uint8_t*,
                                                          size_t, size_t, size_t, size_t, size_t,
                                                          size_t, int);
OPENTLV_WASM_API opentlv_wasm_execution_t* opentlv_wasm_execution_new(opentlv_wasm_program_t*,
                                                                      size_t, size_t, size_t, int);
OPENTLV_WASM_API const char* opentlv_wasm_execution_input(opentlv_wasm_execution_t*, const uint8_t*,
                                                          size_t, size_t, int);
OPENTLV_WASM_API const char* opentlv_wasm_execution_bind(opentlv_wasm_execution_t*, const char*,
                                                         int, const char*, const uint8_t*, size_t);
/* Feed complete source-less canonical events. END carries no Tag/Value.
 * Reader input and raw feeds cannot be mixed before reset. */
OPENTLV_WASM_API const char* opentlv_wasm_execution_feed(opentlv_wasm_execution_t*, int,
                                                         const uint8_t*, size_t, const uint8_t*,
                                                         size_t, size_t, size_t, int);
OPENTLV_WASM_API const char* opentlv_wasm_execution_feed_source(opentlv_wasm_execution_t*, int,
                                                                const uint8_t*, size_t, size_t,
                                                                size_t, int);
/* Operations: 0 reset, 1 pull, 2 scalar, 3 status, 4 exists, 5 context,
 * 6 pruning, 7 finish, 8 retained result with ordinal. */
OPENTLV_WASM_API const char* opentlv_wasm_execution_operation(opentlv_wasm_execution_t*, int,
                                                              size_t);
OPENTLV_WASM_API void        opentlv_wasm_execution_free(opentlv_wasm_execution_t*);
OPENTLV_WASM_API opentlv_wasm_document_t* opentlv_wasm_document_new(opentlv_wasm_program_t*,
                                                                    const uint8_t*, size_t, int);
OPENTLV_WASM_API void                     opentlv_wasm_document_free(opentlv_wasm_document_t*);
OPENTLV_WASM_API const char*              opentlv_wasm_document_encode(opentlv_wasm_document_t*);
OPENTLV_WASM_API const char* opentlv_wasm_execution_document(opentlv_wasm_execution_t*,
                                                             opentlv_wasm_document_t*, size_t);
OPENTLV_WASM_API const char* opentlv_wasm_execution_edit(opentlv_wasm_execution_t*, int,
                                                         const uint8_t*, size_t, const uint8_t*,
                                                         size_t, size_t);
/* Native node address is an internal token, checked against an immutable
 * identity before navigation or mutation. JS never dereferences it. */
OPENTLV_WASM_API const char* opentlv_wasm_document_node(opentlv_wasm_document_t*, size_t,
                                                        const char*, int, const uint8_t*, size_t);

/*
 * Parses `size` bytes as `format` ("fixed", "bluetooth-ltv", "bluetooth-ad", "lldp", "nfc-type2",
 * "ber", "der" or "cer"). `module` annotates elements with dictionary metadata: NULL, "" or "none"
 * for none, or "emv" (EMV Contact Book 3 tags) with the "ber" format. `fixed_tag_size`,
 * `fixed_length_size` and `fixed_big_endian` (nonzero for big-endian) configure `format ==
 * "fixed"`'s tag width, length width (1-8 bytes) and length byte order (tlv_fixed_format_t);
 * ignored for every other format. Nonzero `fixed_length_first` selects LTV; nonzero
 * `fixed_counts_tag` makes the length count Tag + Value. Both default to zero for conventional TLV.
 * Returns NULL only when memory runs out. An unknown format or module, invalid fixed-format widths,
 * or invalid input, is reported through the result, never by returning NULL.
 */
OPENTLV_WASM_API opentlv_wasm_result_t*
opentlv_wasm_parse(const uint8_t* data, size_t size, const char* format, const char* module,
                   size_t fixed_tag_size, size_t fixed_length_size, int fixed_big_endian,
                   int fixed_length_first, int fixed_counts_tag);

/* tlv_result_t of the parse; 0 (TLV_OK) on success. */
OPENTLV_WASM_API int opentlv_wasm_result_code(const opentlv_wasm_result_t* result);

/* Primary location, borrowed from result; NULL for NULL result. Inspect only on failure. */
OPENTLV_WASM_API const tlv_location_t*
opentlv_wasm_result_location(const opentlv_wasm_result_t* result);

/* NUL-terminated JSON document, owned by the result. */
OPENTLV_WASM_API const char* opentlv_wasm_result_json(const opentlv_wasm_result_t* result);

/* Length of the JSON document in bytes, without the terminating NUL. */
OPENTLV_WASM_API size_t opentlv_wasm_result_json_size(const opentlv_wasm_result_t* result);

OPENTLV_WASM_API void opentlv_wasm_result_free(opentlv_wasm_result_t* result);

/* Allocates input or format-name memory for the caller; release with opentlv_wasm_free(). */
OPENTLV_WASM_API uint8_t* opentlv_wasm_alloc(size_t size);

OPENTLV_WASM_API void opentlv_wasm_free(void* pointer);

/* OpenTLV version this module was built from. */
OPENTLV_WASM_API const char* opentlv_wasm_version(void);

#ifdef __cplusplus
}
#endif

#endif /* OPENTLV_WASM_H */
