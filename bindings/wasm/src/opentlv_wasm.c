// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel

#include "opentlv_wasm.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../../common/query_schema.h"
#include "../../common/path_query.h"

#include "tlv/tlv.h"
#include "tlv/query/adapters.h"
#include "tlv/document/document.h"
#include "tlv/writer/tree.h"
#if OPENTLV_EMV
#include "tlv/builtins/emv/query.h"
#endif
#if OPENTLV_DHCP
#include "tlv/builtins/dhcp/dhcpv4.h"
#endif
#if OPENTLV_FORMAT_BER
#include "tlv/builtins/asn1/query.h"
#endif

/* Bounded browser output storage; independent of core traversal limits. */
enum { WASM_TREE_CAPACITY = 64 };
#if OPENTLV_NFC
#include "tlv/builtins/nfc/type2.h"
#endif
#if OPENTLV_LLDP
#include "tlv/builtins/lldp/lldp.h"
#endif
#if OPENTLV_BLUETOOTH
#include "tlv/builtins/bluetooth/bluetooth_ltv.h"
#include "tlv/builtins/bluetooth/ad_data.h"
#include "tlv/builtins/bluetooth/ad_types.h"
#endif
#include "tlv/version.h"
#if OPENTLV_FORMAT_CER
#include "tlv/builtins/asn1/cer.h"
#endif

enum {
    /* Bounds the work one browser call can request. */
    WASM_MAX_ELEMENTS = 65536
};

struct opentlv_wasm_result {
    tlv_result_t   code;
    tlv_location_t location;
    char*          json;
    size_t         json_size;
};

typedef struct {
    char*  data;
    size_t size;
    size_t capacity;
    int    failed;
} builder_t;

typedef struct {
    builder_t out;
    /* Elements are visited in preorder; `open` counts the elements whose JSON
     * object is still unclosed, `has_children` records which of them opened a
     * "children" array and `count` how many siblings each level already has. */
    size_t open;
    size_t count[WASM_TREE_CAPACITY + 2];
    int    has_children[WASM_TREE_CAPACITY + 2];
    int    ber;
    int    bluetooth;
    /* Start of the parsed input; offsets of values are measured against it. */
    const uint8_t*      input;
    size_t              input_size;
    const tlv_format_t* reader;
#if OPENTLV_EMV
    /* Set when the EMV dictionary annotates elements; `emv_context[d]` is the
     * dictionary context of the elements at depth d. */
    int               emv;
    tlv_emv_context_t emv_context[WASM_TREE_CAPACITY + 2];
#endif
} writer_context_t;

static void builder_reserve(builder_t* b, size_t extra) {
    size_t needed;
    char*  grown;
    if (b->failed) return;
    if (extra > (size_t)-1 - b->size - 1) {
        b->failed = 1;
        return;
    }
    needed = b->size + extra + 1;
    if (needed <= b->capacity) return;
    needed = needed < 256 ? 256 : needed;
    if (needed < b->capacity * 2) needed = b->capacity * 2;
    grown = (char*)realloc(b->data, needed);
    if (!grown) {
        b->failed = 1;
        return;
    }
    b->data = grown;
    b->capacity = needed;
}

static void builder_append(builder_t* b, const char* text, size_t length) {
    builder_reserve(b, length);
    if (b->failed) return;
    memcpy(b->data + b->size, text, length);
    b->size += length;
    b->data[b->size] = '\0';
}

static void builder_text(builder_t* b, const char* text) {
    builder_append(b, text, strlen(text));
}

static void builder_number(builder_t* b, size_t value) {
    char text[32];
    (void)sprintf(text, "%lu", (unsigned long)value);
    builder_text(b, text);
}

static void builder_hex(builder_t* b, const uint8_t* bytes, size_t length) {
    static const char digits[] = "0123456789ABCDEF";
    size_t            i;
    builder_reserve(b, length * 2);
    if (b->failed) return;
    for (i = 0; i < length; ++i) {
        b->data[b->size++] = digits[bytes[i] >> 4];
        b->data[b->size++] = digits[bytes[i] & 0x0F];
    }
    b->data[b->size] = '\0';
}

static void builder_json_string(builder_t* b, const char* text) {
    builder_text(b, "\"");
    for (; *text; ++text) {
        if ((unsigned char)*text < 0x20) {
            /* The caller controls the format name; keep the document valid JSON. */
            char escape[8];
            (void)sprintf(escape, "\\u%04X", (unsigned)(unsigned char)*text);
            builder_text(b, escape);
            continue;
        }
        if (*text == '"' || *text == '\\') builder_append(b, "\\", 1);
        builder_append(b, text, 1);
    }
    builder_text(b, "\"");
}

static void close_elements(writer_context_t* w, size_t depth) {
    while (w->open > depth) {
        --w->open;
        builder_text(&w->out, w->has_children[w->open] ? "]}" : "}");
    }
}

#if OPENTLV_EMV
/* Appends the EMV dictionary entry of the element, if it has one, and derives
 * the dictionary context its children are read in. */
static void emit_emv(writer_context_t* w, const tlv_element_t* element, size_t depth,
                     size_t length) {
    tlv_emv_context_t           context = w->emv_context[depth];
    tlv_emv_context_t           child = tlv_emv_child_context(context, &element->tag);
    const tlv_emv_definition_t* definition = tlv_emv_find(context, &element->tag);

    w->emv_context[depth + 1] = child == TLV_EMV_CONTEXT_COUNT ? context : child;
    if (!definition) return;
    {
        const char* label = definition->definition->name;
        builder_text(&w->out, ",\"symbol\":");
        builder_json_string(&w->out, tlv_emv_symbol(definition));
        if (label) {
            builder_text(&w->out, ",\"name\":");
            builder_json_string(&w->out, label);
        }
        builder_text(&w->out, tlv_emv_validate_length(definition, length) == TLV_OK
                                  ? ",\"lengthValid\":true"
                                  : ",\"lengthValid\":false");
    }
}
#endif

static void emit_range(builder_t* out, const char* name, tlv_range_t range, size_t offset) {
    builder_text(out, name);
    builder_text(out, "{\"offset\":");
    builder_number(out, offset + range.offset);
    builder_text(out, ",\"length\":");
    builder_number(out, range.size);
    builder_text(out, "}");
}

static tlv_visit_result_t emit_element(const tlv_element_t* element, size_t depth, size_t offset,
                                       void* context) {
    writer_context_t* w = (writer_context_t*)context;
    int               constructed = 0;
    size_t            length, header_size;
    tlv_decoded_t     decoded;

    if (tlv_size_to_native(element->value.size, &length) != TLV_OK) return TLV_VISIT_ERROR;
    if (depth > WASM_TREE_CAPACITY) return TLV_VISIT_ERROR;
    /* Obtain authoritative source ranges, including trailers such as BER EOC. */
    if (offset > w->input_size ||
        tlv_format_decode(w->reader, w->input + offset, w->input_size - offset, &decoded, NULL) !=
            TLV_OK)
        return TLV_VISIT_ERROR;
    header_size = decoded.source.header.size;
    if (w->reader->is_constructed)
        constructed = w->reader->is_constructed(w->reader->context, &element->tag) != 0;
    close_elements(w, depth);
    if (w->count[depth]++) builder_text(&w->out, ",");
    w->count[depth + 1] = 0;

    builder_text(&w->out, "{\"offset\":");
    builder_number(&w->out, offset);
    builder_text(&w->out, ",\"depth\":");
    builder_number(&w->out, depth);
    builder_text(&w->out, ",\"tag\":\"");
    builder_hex(&w->out, element->tag.data, element->tag.size);
    builder_text(&w->out, "\",\"length\":");
    builder_number(&w->out, length);
    builder_text(&w->out, ",\"headerSize\":");
    builder_number(&w->out, header_size);
    builder_text(&w->out, ",\"encodedSize\":");
    builder_number(&w->out, decoded.source.size);
    builder_text(&w->out, ",\"source\":{");
    emit_range(&w->out, "\"header\":", decoded.source.header, offset);
    emit_range(&w->out, ",\"tag\":", decoded.source.tag, offset);
    emit_range(&w->out, ",\"length\":", decoded.source.length, offset);
    emit_range(&w->out, ",\"value\":", decoded.source.value, offset);
    emit_range(&w->out, ",\"trailer\":", decoded.source.trailer, offset);
    builder_text(&w->out, "}");
    builder_text(&w->out, constructed ? ",\"constructed\":true" : ",\"constructed\":false");
#if OPENTLV_EMV
    if (w->emv) emit_emv(w, element, depth, length);
#endif
#if OPENTLV_BLUETOOTH
    if (w->bluetooth) {
        const tlv_definition_t* definition =
            tlv_definition_find(&tlv_bluetooth_ad_types, &element->tag);
        if (definition) {
            builder_text(&w->out, ",\"name\":");
            builder_json_string(&w->out, definition->name);
        }
    }
#endif
    if (constructed && length) {
        /* The Tree Reader descends into it next; children close it later. */
        builder_text(&w->out, ",\"children\":[");
        w->has_children[w->open] = 1;
    } else {
        builder_text(&w->out, ",\"value\":\"");
        builder_hex(&w->out, element->value.data, length);
        builder_text(&w->out, "\"");
        w->has_children[w->open] = 0;
    }
    ++w->open;
    return w->out.failed ? TLV_VISIT_ERROR : TLV_VISIT_CONTINUE;
}

static const tlv_format_t* select_format(const char* name, int* ber, int* der,
                                         size_t fixed_tag_size, size_t fixed_length_size,
                                         int fixed_big_endian, int fixed_length_first,
                                         int fixed_counts_tag, tlv_fixed_format_t* fixed_config,
                                         tlv_format_t* fixed_format) {
    *ber = 0;
    *der = 0;
    if (!name) return NULL;
    // Configured by the caller's fixed_tag_size/fixed_length_size/fixed_big_endian.
    // fixed_config/fixed_format are storage owned by the caller (opentlv_wasm_parse),
    // which outlives this call, since a `static` here would make the module
    // non-reentrant (see docs/guides/memory.md#format-context-ownership-and-lifetime).
    if (!strcmp(name, "fixed")) {
        fixed_config->identifier.size = fixed_tag_size;
        fixed_config->length.size = fixed_length_size;
        fixed_config->length.byte_order =
            fixed_big_endian ? TLV_BYTE_ORDER_BIG_ENDIAN : TLV_BYTE_ORDER_LITTLE_ENDIAN;
        fixed_config->element_order =
            fixed_length_first ? TLV_ELEMENT_ORDER_LTV : TLV_ELEMENT_ORDER_TLV;
        fixed_config->length_scope =
            fixed_counts_tag ? TLV_LENGTH_SCOPE_TAG_AND_VALUE : TLV_LENGTH_SCOPE_VALUE;
        if (tlv_fixed_format_init(fixed_format, fixed_config) != TLV_OK) return NULL;
        return fixed_format;
    }
#if OPENTLV_EMV
    if (!strcmp(name, "emv")) return &tlv_format_emv;
#endif
#if OPENTLV_NFC
    if (!strcmp(name, "nfc-type2")) return &tlv_format_nfc_type2;
#endif
#if OPENTLV_LLDP
    if (!strcmp(name, "lldp")) return &tlv_format_lldp;
#endif
#if OPENTLV_BLUETOOTH
    if (!strcmp(name, "bluetooth-ltv") || !strcmp(name, "bluetooth-ad"))
        return &tlv_format_bluetooth_ltv;
#endif
#if OPENTLV_FORMAT_BER
    if (!strcmp(name, "ber")) {
        *ber = 1;
        return &tlv_format_ber;
    }
#endif
#if OPENTLV_FORMAT_DER
    if (!strcmp(name, "der")) {
        *ber = 1;
        *der = 1;
        return &tlv_format_der;
    }
#endif
#if OPENTLV_FORMAT_CER
    if (!strcmp(name, "cer")) {
        *ber = 1;
        return &tlv_format_cer;
    }
#endif
    return NULL;
}

static void write_named_location(builder_t* b, const char* name, const tlv_location_t* location) {
    tlv_location_t unknown = {0};
    if (!location) location = &unknown;
    builder_text(b, ",");
    builder_json_string(b, name);
    builder_text(b, ":{\"domain\":");
    builder_json_string(b, tlv_location_domain_string(location->domain));
    builder_text(b, ",\"kind\":");
    builder_json_string(b, tlv_location_kind_string(location->kind));
    if (location->kind != TLV_LOCATION_UNKNOWN) {
        builder_text(b, ",\"begin\":");
        builder_number(b, location->begin);
        builder_text(b, ",\"end\":");
        builder_number(b, location->end);
    }
    builder_text(b, "}");
}

static void write_location(builder_t* b, const tlv_location_t* location) {
    write_named_location(b, "location", location);
}

static void append_error(builder_t* b, tlv_result_t code, const tlv_location_t* location) {
    builder_text(b, ",\"error\":{\"code\":");
    builder_number(b, (size_t)code);
    builder_text(b, ",\"message\":");
    builder_json_string(b, tlv_result_string(code));
    write_location(b, location);
    if (location->kind != TLV_LOCATION_UNKNOWN) {
        builder_text(b, ",\"offset\":");
        builder_number(b, location->begin);
    }
    builder_text(b, "}");
}

opentlv_wasm_result_t* opentlv_wasm_parse(const uint8_t* data, size_t size, const char* format,
                                          const char* module, size_t fixed_tag_size,
                                          size_t fixed_length_size, int fixed_big_endian,
                                          int fixed_length_first, int fixed_counts_tag) {
    opentlv_wasm_result_t*  result = (opentlv_wasm_result_t*)calloc(1, sizeof *result);
    const tlv_format_t*     reader;
    writer_context_t*       w;
    int                     ber, der;
    tlv_reader_diagnostic_t failure = {0};
    size_t                  padding_offset = size;
    /* Storage for select_format()'s "fixed" case; must outlive its use below. */
    tlv_fixed_format_t fixed_config;
    tlv_format_t       fixed_format;

    if (!result) return NULL;
    w = (writer_context_t*)calloc(1, sizeof *w);
    if (!w) {
        free(result);
        return NULL;
    }
    reader = select_format(format, &ber, &der, fixed_tag_size, fixed_length_size, fixed_big_endian,
                           fixed_length_first, fixed_counts_tag, &fixed_config, &fixed_format);
    w->ber = ber;
    w->input = data;
    w->input_size = size;
    w->reader = reader;
    w->bluetooth = format && (!strcmp(format, "bluetooth-ltv") || !strcmp(format, "bluetooth-ad"));

    builder_text(&w->out, "{\"format\":");
    builder_json_string(&w->out, format ? format : "");

    if (module && *module && strcmp(module, "none")) {
        /* The EMV dictionary names BER-TLV tags; it does not apply to other formats. */
#if OPENTLV_EMV
        if (!strcmp(module, "emv") && format &&
            (!strcmp(format, "ber") || !strcmp(format, "emv")) && reader) {
            w->emv = 1;
            w->emv_context[0] = TLV_EMV_CONTEXT_BASE;
            builder_text(&w->out, ",\"module\":\"emv\"");
        } else
#endif
            reader = NULL;
    }
    builder_text(&w->out, ",\"elements\":[");

    if (!reader) {
        result->code = TLV_ERR_INVALID_ARG;
    } else if (!data && size) {
        result->code = TLV_ERR_NULL_ARG;
    } else {
#if OPENTLV_BLUETOOTH
        if (!strcmp(format, "bluetooth-ad")) {
            tlv_reader_t ad_reader;
            size_t       count = 0;
            result->code = tlv_reader_init(&ad_reader, data, size, reader);
            while (result->code == TLV_OK && !tlv_reader_at_end(&ad_reader)) {
                size_t                  offset = ad_reader.pos;
                tlv_element_t           element;
                tlv_reader_diagnostic_t diagnostic;
                if (data[offset] == 0) {
                    size_t                  significant_size;
                    tlv_reader_diagnostic_t relative_error = {0};
                    result->code = tlv_bluetooth_ad_data_validate(
                        data + offset, size - offset, &significant_size, &relative_error);
                    if (result->code == TLV_OK)
                        padding_offset = offset;
                    else {
                        failure = relative_error;
                        tlv_location_translate(&failure.diagnostic.location, offset);
                    }
                    break;
                }
                if (count++ == WASM_MAX_ELEMENTS) {
                    result->code = TLV_ERR_LIMIT;
                    tlv_diagnostic_set_location(&failure.diagnostic, TLV_LOCATION_INPUT,
                                                TLV_LOCATION_POINT, offset, offset);
                    break;
                }
                result->code = tlv_reader_next_diag(&ad_reader, &element, &diagnostic);
                if (result->code != TLV_OK) {
                    failure = diagnostic;
                    break;
                }
                if (emit_element(&element, 0, offset, w) != TLV_VISIT_CONTINUE) {
                    result->code = TLV_ERR_VISITOR;
                    tlv_diagnostic_set_location(&failure.diagnostic, TLV_LOCATION_INPUT,
                                                TLV_LOCATION_POINT, offset, offset);
                }
            }
        } else
#endif
#if OPENTLV_FORMAT_DER
            if (der) {
            result->code = tlv_der_visit(data, size, NULL, emit_element, w, &failure.diagnostic);
        } else
#endif
        {
            tlv_tree_reader_t cursor;
            tlv_tree_frame_t  frames[WASM_TREE_CAPACITY];
            result->code =
                tlv_tree_reader_init(&cursor, data, size, reader, frames, WASM_TREE_CAPACITY,
                                     WASM_TREE_CAPACITY, WASM_MAX_ELEMENTS);
            if (result->code == TLV_OK)
                result->code = tlv_tree_reader_visit(&cursor, emit_element, w, &failure);
        }
    }
    if (w->out.failed) result->code = TLV_ERR_OUT_OF_MEMORY;
    result->location = failure.diagnostic.location;

    close_elements(w, 0);
    builder_text(&w->out, "]");
    if (padding_offset < size) {
        builder_text(&w->out, ",\"padding\":{\"offset\":");
        builder_number(&w->out, padding_offset);
        builder_text(&w->out, ",\"length\":");
        builder_number(&w->out, size - padding_offset);
        builder_text(&w->out, "}");
    }
    if (result->code != TLV_OK) append_error(&w->out, result->code, &result->location);
    builder_text(&w->out, "}");

    if (w->out.failed) {
        free(w->out.data);
        free(w);
        free(result);
        return NULL;
    }
    result->json = w->out.data;
    result->json_size = w->out.size;
    free(w);
    return result;
}

int opentlv_wasm_result_code(const opentlv_wasm_result_t* result) {
    return result ? (int)result->code : (int)TLV_ERR_NULL_ARG;
}

const tlv_location_t* opentlv_wasm_result_location(const opentlv_wasm_result_t* result) {
    return result ? &result->location : NULL;
}

const char* opentlv_wasm_result_json(const opentlv_wasm_result_t* result) {
    return result ? result->json : NULL;
}

size_t opentlv_wasm_result_json_size(const opentlv_wasm_result_t* result) {
    return result ? result->json_size : 0;
}

void opentlv_wasm_result_free(opentlv_wasm_result_t* result) {
    if (!result) return;
    free(result->json);
    free(result);
}

uint8_t* opentlv_wasm_alloc(size_t size) {
    return (uint8_t*)malloc(size ? size : 1);
}

void opentlv_wasm_free(void* pointer) {
    free(pointer);
}

const char* opentlv_wasm_version(void) {
    return tlv_version_string();
}

/* Owning boundary storage is deliberately outside the allocation-free core. */
enum { QUERY_DECLARATIONS = 64 };
typedef struct {
    char*    name;
    uint8_t* bytes;
    size_t   size;
} wasm_name_t;
typedef struct wasm_pin {
    struct wasm_pin* next;
    size_t           size;
    uint8_t          data[1];
} wasm_pin_t;
struct opentlv_wasm_format {
    size_t             references;
    tlv_format_t       format;
    tlv_fixed_format_t fixed;
    int                asn1;
    wasm_pin_t*        tags;
};
opentlv_wasm_format_t* opentlv_wasm_format_new(const char* name, size_t tag_size,
                                               size_t length_size, int big, int ltv,
                                               int counts_tag) {
    if (!name) return NULL;
    opentlv_wasm_format_t* owner = calloc(1, sizeof *owner);
    if (!owner) return NULL;
    owner->references = 1;
    if (!strcmp(name, "custom")) return owner;
    int                 der;
    const tlv_format_t* format = select_format(name, &owner->asn1, &der, tag_size, length_size, big,
                                               ltv, counts_tag, &owner->fixed, &owner->format);
#if OPENTLV_DHCP
    if (!strcmp(name, "dhcpv4")) format = &tlv_format_dhcpv4;
#endif
#if OPENTLV_FORMAT_BER
    if (!strcmp(name, "ber-indefinite")) {
        format = &tlv_format_ber_indefinite;
        owner->asn1 = 1;
    }
#endif
    if (!format) {
        free(owner);
        return NULL;
    }
    owner->format = *format;
    return owner;
}
int opentlv_wasm_format_callbacks(opentlv_wasm_format_t* owner, tlv_decode_fn decode,
                                  tlv_measure_fn measure, tlv_encode_fn encode,
                                  tlv_is_constructed_fn constructed) {
    if (!owner || owner->references != 1) return TLV_ERR_INVALID_ARG;
    if (decode) {
        tlv_result_t rc = tlv_format_init(&owner->format, owner, decode, measure, encode);
        if (rc != TLV_OK) return rc;
    }
    owner->format.is_constructed = constructed;
    return TLV_OK;
}
void opentlv_wasm_format_free(opentlv_wasm_format_t* owner) {
    if (!owner || --owner->references) return;
    while (owner->tags) {
        wasm_pin_t* next = owner->tags->next;
        free(owner->tags);
        owner->tags = next;
    }
    free(owner);
}
int opentlv_wasm_format_decoded(opentlv_wasm_format_t* owner, tlv_decoded_t* result,
                                const uint8_t* input, size_t available, const uint8_t* tag,
                                size_t tag_size, const uint32_t* ranges) {
    tlv_range_t fields[5];
    for (size_t i = 0; i < 5; ++i) {
        fields[i] = (tlv_range_t){ranges[2 * i], ranges[2 * i + 1], ranges[2 * i] != UINT32_MAX};
        if (fields[i].present &&
            (fields[i].offset > available || fields[i].size > available - fields[i].offset))
            return TLV_ERR_INVALID_ARG;
    }
    if (!fields[0].present || !fields[3].present || !fields[4].present ||
        fields[0].size > SIZE_MAX - fields[3].size ||
        fields[4].size > SIZE_MAX - fields[0].size - fields[3].size)
        return TLV_ERR_INVALID_ARG;
    size_t extent = fields[0].size + fields[3].size + fields[4].size;
    if (extent > available) return TLV_ERR_BUFFER_TOO_SHORT;
    if (tag_size > SIZE_MAX - sizeof(wasm_pin_t)) return TLV_ERR_OVERFLOW;
    wasm_pin_t* pin = owner->tags;
    while (pin && (pin->size != tag_size || (tag_size && memcmp(pin->data, tag, tag_size))))
        pin = pin->next;
    if (!pin) {
        pin = malloc(sizeof *pin + tag_size);
        if (!pin) return TLV_ERR_OUT_OF_MEMORY;
        if (tag_size) memcpy(pin->data, tag, tag_size);
        pin->size = tag_size;
        pin->next = owner->tags;
        owner->tags = pin;
    }
    memset(result, 0, sizeof *result);
    result->element.tag = tlv_tag(pin->data, tag_size);
    result->element.value.data = input + fields[3].offset;
    result->element.value.size = fields[3].size;
    result->source = (tlv_source_t){
        input,     extent,    fields[0],       fields[1],      fields[2],
        fields[3], fields[4], result->element, &owner->format, TLV_TAG_BINDING_FORMAT};
    return TLV_OK;
}
size_t opentlv_wasm_element_field(const tlv_element_t* e, int field) {
    switch (field) {
        case 0: return (size_t)(uintptr_t)e->tag.data;
        case 1: return e->tag.size;
        case 2: return (size_t)(uintptr_t)e->value.data;
        case 3: return e->value.size;
        default: return 0;
    }
}
size_t opentlv_wasm_tag_field(const tlv_tag_t* tag, int field) {
    return field ? tag->size : (size_t)(uintptr_t)tag->data;
}
void opentlv_wasm_integer_write(int64_t* result, uint32_t low, uint32_t high) {
    uint64_t bits = ((uint64_t)high << 32) | low;
    memcpy(result, &bits, sizeof bits);
}
int opentlv_wasm_encoding_write(tlv_encoding_t* e, size_t header, size_t value, size_t trailer) {
    e->header = header;
    e->value = value;
    e->trailer = trailer;
    e->total = (tlv_size_t)header + value + trailer;
    return TLV_OK;
}
void opentlv_wasm_size_write(size_t* target, size_t value) {
    *target = value;
}
struct opentlv_wasm_program {
    size_t                      references;
    tlv_query_compile_options_t options;
    tlv_query_variable_t        variables[QUERY_DECLARATIONS];
    wasm_name_t                 names[QUERY_DECLARATIONS];
    size_t                      name_count;
    tlv_query_environment_t     environment;
    tlv_query_hook_t            hooks[4];
    tlv_query_tag_adapter_t     tags;
    opentlv_wasm_format_t*      format_owner;
    uint8_t*                    resolved;
    size_t                      resolved_capacity;
    const tlv_query_program_t*  program;
    void*                       image;
    tlv_query_program_info_t    info;
    builder_t                   reply;
};
struct opentlv_wasm_document {
    size_t                  references;
    opentlv_wasm_program_t* program;
    tlv_document_t*         document;
};
struct opentlv_wasm_execution {
    opentlv_wasm_program_t*  program;
    opentlv_wasm_document_t* document;
    tlv_query_exec_t*        exec;
    void*                    allocation;
    void*                    storage;
    void*                    values;
    size_t                   capacity, depth, nodes, work;
    int                      retained, has_reader, fed;
    tlv_tree_reader_t        reader;
    tlv_tree_frame_t*        frames;
    wasm_pin_t*              pins;
    builder_t                reply;
};
static char* query_copy_name(const char* name) {
    if (!name) return NULL;
    size_t n = strlen(name);
    char*  copy = malloc(n + 1);
    if (copy) memcpy(copy, name, n + 1);
    return copy;
}
static tlv_result_t wasm_resolve(const void* context, const char* scope, size_t scope_size,
                                 const char* name, size_t name_size, tlv_tag_t* tag) {
    const opentlv_wasm_program_t* p = context;
    for (size_t i = 0; i < p->name_count; ++i) {
        const wasm_name_t* n = p->names + i;
        size_t             prefix = scope_size ? scope_size + 1 : 0;
        if (strlen(n->name) != prefix + name_size) continue;
        if (scope_size && (memcmp(n->name, scope, scope_size) || n->name[scope_size] != ':'))
            continue;
        if (!memcmp(n->name + prefix, name, name_size)) {
            *tag = tlv_tag(n->bytes, n->size);
            return TLV_OK;
        }
    }
    return TLV_ERR_INVALID_TAG;
}
static void query_integer(builder_t* b, int64_t value) {
    char text[32];
    (void)snprintf(text, sizeof text, "%lld", (long long)value);
    builder_json_string(b, text);
}
static void query_unsigned(builder_t* b, uint64_t value) {
    char text[32];
    (void)snprintf(text, sizeof text, "%llu", (unsigned long long)value);
    builder_json_string(b, text);
}
static void query_common_diagnostic(builder_t* b, const tlv_diagnostic_t* common) {
    builder_text(b, "\"severity\":");
    builder_number(b, common->severity);
    builder_text(b, ",\"severity_name\":");
    builder_json_string(b, tlv_diagnostic_severity_string(common->severity));
    if (common->expected) {
        builder_text(b, ",\"expected\":");
        builder_json_string(b, common->expected);
    }
    if (common->actual) {
        builder_text(b, ",\"actual\":");
        builder_json_string(b, common->actual);
    }

    builder_text(b, ",\"has_path\":");
    builder_text(b, common->has_path ? "true" : "false");
    builder_text(b, ",\"path\":[");
    if (common->has_path)
        for (size_t i = 0; i < common->path.length; ++i) {
            const tlv_tag_t* tag = common->path.tags + i;
            if (i) builder_text(b, ",");
            builder_text(b, "\"");
            builder_hex(b, tag->data, tag->size);
            builder_text(b, "\"");
        }
    builder_text(b, "],\"path_omitted\":");
    builder_number(b, common->has_path ? common->path.omitted : 0);
    builder_text(b, ",\"contexts\":[");
    int first = 1;
    for (const tlv_diagnostic_context_t* c = common->contexts; c; c = c->next) {
        if (!first) builder_text(b, ",");
        first = 0;
        builder_text(b, "{\"layer\":");
        builder_json_string(b, c->layer ? c->layer : "");
        builder_text(b, ",\"key\":");
        builder_json_string(b, c->key ? c->key : "");
        builder_text(b, ",\"value\":");
        builder_json_string(b, c->value ? c->value : "");
        builder_text(b, "}");
    }
    builder_text(b, "]");
}
/* Reader and Codec causes carry only their own detail; the common result,
 * location, path and contexts are emitted once under query.diagnostic. */
static void query_reader_diagnostic(builder_t* b, const tlv_reader_detail_t* r) {
    builder_text(b, ",\"reader\":{\"operation\":");
    builder_number(b, r->operation);
    builder_text(b, ",\"operation_name\":");
    builder_json_string(b, tlv_reader_operation_string(r->operation));
    if (r->has_tag) {
        builder_text(b, ",\"tag\":\"");
        builder_hex(b, r->tag.data, r->tag.size);
        builder_text(b, "\"");
    }
    if (r->has_raw_length) {
        builder_text(b, ",\"raw_length\":\"");
        builder_hex(b, r->raw_length.data, r->raw_length.size);
        builder_text(b, "\"");
    }
#define READER_FIELD(n)                                                                            \
    do {                                                                                           \
        if (r->has_##n) {                                                                          \
            builder_text(b, ",\"" #n "\":");                                                       \
            builder_number(b, r->n);                                                               \
        }                                                                                          \
    } while (0)
    READER_FIELD(tag_offset);
    READER_FIELD(length_offset);
    READER_FIELD(value_offset);
    READER_FIELD(available);
    READER_FIELD(enclosing_end);
#undef READER_FIELD
    if (r->has_declared_length) {
        builder_text(b, ",\"declared_length\":");
        query_unsigned(b, r->declared_length);
    }
    if (r->has_required) {
        builder_text(b, ",\"required\":");
        query_unsigned(b, r->required);
    }
    builder_text(b, "}");
}
static void query_codec_diagnostic(builder_t* b, const tlv_codec_detail_t* d) {
    builder_text(b, ",\"codec_detail\":{\"operation\":");
    builder_number(b, d->operation);
    builder_text(b, ",\"operation_name\":");
    builder_json_string(b, tlv_codec_operation_string(d->operation));
    builder_text(b, ",\"reported\":");
    builder_number(b, d->reported);
    builder_text(b, ",\"violation\":");
    builder_number(b, d->violation);
    builder_text(b, ",\"violation_name\":");
    builder_json_string(b, tlv_codec_violation_string(d->violation));
    builder_text(b, ",\"reason\":");
    builder_number(b, d->reason);
    builder_text(b, ",\"reason_name\":");
    builder_json_string(b, tlv_codec_reason_string(d->reason));
    builder_text(b, ",\"cause\":");
    builder_number(b, d->cause);
    builder_text(b, ",\"cause_name\":");
    builder_json_string(b, tlv_codec_cause_string(d->cause));
    if (d->representation) {
        builder_text(b, ",\"representation\":");
        builder_json_string(b, d->representation);
    }
    if (d->cause == TLV_CODEC_CAUSE_READER) query_reader_diagnostic(b, &d->detail.reader);
    if (d->cause == TLV_CODEC_CAUSE_SCHEMA) {
        const tlv_schema_detail_t* v = &d->detail.schema;
        builder_text(b, ",\"schema\":{\"kind\":");
        builder_number(b, v->kind);
        builder_text(b, ",\"kind_name\":");
        builder_json_string(b, tlv_schema_issue_kind_string(v->kind));
        builder_text(b, ",\"tag\":\"");
        builder_hex(b, v->tag.data, v->tag.size);
        builder_text(b, "\"");
        if (v->field) {
            builder_text(b, ",\"field\":");
            builder_json_string(b, v->field);
        }
        builder_text(b, ",\"definition_kind\":");
        builder_number(b, v->definition.kind);
        builder_text(b, ",\"definition_kind_name\":");
        builder_json_string(b, tlv_schema_definition_kind_string(v->definition.kind));
        builder_text(b, ",\"definition_index\":");
        builder_number(b, v->definition.index);
        builder_text(b, ",\"is_group\":");
        builder_number(b, v->is_group);
        builder_text(b, ",\"has_occurs\":");
        builder_number(b, v->has_occurs);
        builder_text(b, ",\"min_occurs\":");
        builder_number(b, v->min_occurs);
        builder_text(b, ",\"max_occurs\":");
        builder_number(b, v->max_occurs);
        builder_text(b, ",\"occurs\":");
        builder_number(b, v->occurs);
        builder_text(b, ",\"has_length\":");
        builder_number(b, v->has_length);
        builder_text(b, ",\"min_length\":");
        builder_number(b, v->min_length);
        builder_text(b, ",\"max_length\":");
        builder_number(b, v->max_length);
        builder_text(b, ",\"actual_length\":");
        builder_number(b, v->actual_length);
        builder_text(b, ",\"has_form\":");
        builder_number(b, v->has_form);
        builder_text(b, ",\"expected_form\":");
        builder_number(b, v->expected_form);
        builder_text(b, ",\"actual_constructed\":");
        builder_number(b, v->actual_constructed);
        builder_text(b, ",\"length_multiple\":");
        builder_number(b, v->length_multiple);
        builder_text(b, ",\"length_flags\":");
        builder_number(b, v->length_flags);
        builder_text(b, "}");
    }
    builder_text(b, "}");
}
const char* opentlv_wasm_strerror(int code) {
    return tlv_result_string((tlv_result_t)code);
}
const char* opentlv_wasm_query_error_kind_string(int kind) {
    return tlv_query_error_kind_string((tlv_query_error_kind_t)kind);
}

typedef struct {
    const char* name;
    int         value;
} wasm_constant_t;

static void constants_object(builder_t* b, const char* key, const wasm_constant_t* items,
                             size_t count) {
    size_t i;
    builder_json_string(b, key);
    builder_text(b, ":{");
    for (i = 0; i < count; ++i) {
        if (i) builder_text(b, ",");
        builder_json_string(b, items[i].name);
        builder_text(b, ":");
        builder_number(b, (size_t)items[i].value);
    }
    builder_text(b, "}");
}

const char* opentlv_wasm_constants(void) {
    static const wasm_constant_t results[] = {
        {"OK", TLV_OK},
        {"END", TLV_END},
        {"NEED_MORE_DATA", TLV_NEED_MORE_DATA},
        {"TRUNCATED", TLV_ERR_TRUNCATED},
        {"INVALID_TAG", TLV_ERR_INVALID_TAG},
        {"INVALID_TAG_SIZE", TLV_ERR_INVALID_TAG_SIZE},
        {"INVALID_LENGTH", TLV_ERR_INVALID_LENGTH},
        {"INVALID_VALUE", TLV_ERR_INVALID_VALUE},
        {"SYNTAX", TLV_ERR_SYNTAX},
        {"SCHEMA", TLV_ERR_SCHEMA},
        {"NULL_ARG", TLV_ERR_NULL_ARG},
        {"INVALID_ARG", TLV_ERR_INVALID_ARG},
        {"INVALID_STATE", TLV_ERR_INVALID_STATE},
        {"INVALID_SCHEMA", TLV_ERR_INVALID_SCHEMA},
        {"BUFFER_TOO_SHORT", TLV_ERR_BUFFER_TOO_SHORT},
        {"LIMIT", TLV_ERR_LIMIT},
        {"OVERFLOW", TLV_ERR_OVERFLOW},
        {"NATIVE_SIZE", TLV_ERR_NATIVE_SIZE},
        {"OUT_OF_MEMORY", TLV_ERR_OUT_OF_MEMORY},
        {"UNSUPPORTED", TLV_ERR_UNSUPPORTED},
        {"VISITOR", TLV_ERR_VISITOR},
        {"CALLBACK", TLV_ERR_CALLBACK},
    };
    static const wasm_constant_t query_errors[] = {
        {"STATE", TLV_QUERY_ERROR_STATE},
    };
    static builder_t b;
    if (b.size == 0 && !b.failed) {
        builder_text(&b, "{");
        constants_object(&b, "result", results, sizeof results / sizeof results[0]);
        builder_text(&b, ",");
        constants_object(&b, "query_error", query_errors,
                         sizeof query_errors / sizeof query_errors[0]);
        builder_text(&b, "}");
    }
    return b.failed ? NULL : b.data;
}
static void query_status(builder_t* b, tlv_result_t code, const tlv_query_diagnostic_t* d) {
    b->size = 0;
    b->failed = 0;
    builder_text(b, "{\"code\":");
    builder_number(b, code);
    builder_text(b, ",\"message\":");
    builder_json_string(b, tlv_result_string(code));
    write_location(b, d ? &d->diagnostic.location : NULL);
    builder_text(b, ",\"query\":{\"kind\":");
    builder_number(b, code == TLV_ERR_INVALID_STATE ? TLV_QUERY_ERROR_STATE
                      : d                           ? d->kind
                                                    : TLV_QUERY_ERROR_NONE);
    builder_text(b, ",\"kind_name\":");
    builder_json_string(b, tlv_query_error_kind_string(code == TLV_ERR_INVALID_STATE
                                                           ? TLV_QUERY_ERROR_STATE
                                                       : d ? d->kind
                                                           : TLV_QUERY_ERROR_NONE));
    /* Related span only: an expression span that is primary is already "location". */
    write_named_location(b, "expression", d ? &d->expression : NULL);
    if (d) {
        builder_text(b, ",\"configured\":");
        builder_number(b, d->configured);
        if (d->limit) {
            builder_text(b, ",\"limit\":");
            builder_json_string(b, d->limit);
        }
        /* The result code and primary location are the error's own "code" and "location". */
        builder_text(b, ",\"diagnostic\":{");
        query_common_diagnostic(b, &d->diagnostic);
        builder_text(b, "}");
        if (d->cause == TLV_QUERY_CAUSE_CODEC) query_codec_diagnostic(b, &d->detail.codec);
        if (d->cause == TLV_QUERY_CAUSE_READER) query_reader_diagnostic(b, &d->detail.reader);
    }
    builder_text(b, "}");
}
static const char* query_reply(builder_t* b) {
    builder_text(b, "}");
    return b->failed ? "{\"code\":4}" : b->data;
}
static void query_field(builder_t* b, const char* name, size_t value) {
    builder_text(b, ",");
    builder_json_string(b, name);
    builder_text(b, ":");
    builder_number(b, value);
}
struct opentlv_wasm_v1 {
    tlv_query_t            query;
    tlv_query_matcher_t    matcher;
    tlv_result_t           code;
    tlv_query_diagnostic_t failure;
    builder_t              reply;
};
opentlv_wasm_v1_t* opentlv_wasm_v1_new(const char* text, size_t size) {
    opentlv_wasm_v1_t* q = calloc(1, sizeof *q);
    if (!q) return NULL;
    tlv_diagnostic_t parse = {0};
    q->code = tlv_query_parse_n(text, size, &q->query, &parse);
    if (q->code == TLV_OK) q->code = tlv_query_matcher_init(&q->matcher, &q->query);
    /* The text is not retained, so the Query diagnostic is built now. */
    if (q->code != TLV_OK) q->failure = opentlv_binding_path_failure(q->code, &parse, text, size);
    return q;
}
const char* opentlv_wasm_v1_operation(opentlv_wasm_v1_t* q, int operation, const uint8_t* data,
                                      size_t size, size_t depth) {
    tlv_query_diagnostic_t diagnostic = {0};
    /* The V1 expression span is the primary location; it is not stored twice. */
    if (q->code != TLV_OK) diagnostic = q->failure;
    tlv_result_t rc = q->code;
    if (rc == TLV_OK && operation == 1) rc = tlv_query_matcher_init(&q->matcher, &q->query);
    if (operation < 0 || operation > 2) rc = TLV_ERR_INVALID_ARG;
    query_status(&q->reply, rc, &diagnostic);
    if (rc == TLV_OK && operation == 0) {
        char   text[2 * TLV_QUERY_MAX_BYTES + TLV_QUERY_MAX_STEPS];
        size_t required;
        rc = tlv_query_format(&q->query, text, sizeof text, &required);
        if (rc != TLV_OK)
            query_status(&q->reply, rc, NULL);
        else {
            builder_text(&q->reply, ",\"text\":");
            builder_json_string(&q->reply, text);
            builder_text(&q->reply, ",\"steps\":[");
            for (size_t i = 0; i < tlv_query_count(&q->query); ++i) {
                tlv_tag_t tag = tlv_query_step(&q->query, i);
                if (i) builder_text(&q->reply, ",");
                builder_text(&q->reply, "\"");
                builder_hex(&q->reply, tag.data, tag.size);
                builder_text(&q->reply, "\"");
            }
            builder_text(&q->reply, "]");
        }
    } else if (rc == TLV_OK && operation == 2) {
        tlv_tag_t tag = tlv_tag(data, size);
        builder_text(&q->reply, tlv_query_matcher_visit(&q->matcher, &tag, depth)
                                    ? ",\"value\":true"
                                    : ",\"value\":false");
    }
    return query_reply(&q->reply);
}
void opentlv_wasm_v1_free(opentlv_wasm_v1_t* q) {
    if (q) {
        free(q->reply.data);
        free(q);
    }
}
opentlv_wasm_program_t* opentlv_wasm_program_with_format(opentlv_wasm_format_t* owner) {
    if (!owner || !tlv_format_can_read(&owner->format)) return NULL;
    opentlv_wasm_program_t* p = calloc(1, sizeof *p);
    if (!p) return NULL;
    p->references = 1;
    tlv_query_compile_options_init(&p->options);
    p->options.variables = p->variables;
    p->options.resolve = wasm_resolve;
    p->options.resolve_context = p;
    p->options.environment = &p->environment;
    p->format_owner = owner;
    ++owner->references;
    p->environment.format = &owner->format;
    size_t                  count;
    const tlv_query_hook_t* hooks = tlv_query_builtin_hooks(&count);
    memcpy(p->hooks, hooks, count * sizeof *hooks);
#if OPENTLV_FORMAT_BER
    if (owner->asn1) {
        p->environment.tags = &tlv_asn1_query_tags;
        p->hooks[count++] = tlv_asn1_query_date;
    }
#endif
    p->environment.hooks = p->hooks;
    p->environment.hook_count = count;
    return p;
}
opentlv_wasm_program_t* opentlv_wasm_program_new(const char* name) {
    opentlv_wasm_format_t*  format = opentlv_wasm_format_new(name, 1, 1, 1, 0, 0);
    opentlv_wasm_program_t* p = opentlv_wasm_program_with_format(format);
    opentlv_wasm_format_free(format);
    return p;
}
void opentlv_wasm_program_free(opentlv_wasm_program_t* p) {
    if (!p || --p->references) return;
    for (size_t i = 0; i < p->options.variable_count; ++i) free((void*)p->variables[i].name);
    for (size_t i = 0; i < p->name_count; ++i) {
        free(p->names[i].name);
        free(p->names[i].bytes);
    }
    free(p->image);
    free(p->resolved);
    opentlv_wasm_format_free(p->format_owner);
    free(p->reply.data);
    free(p);
}
int opentlv_wasm_program_tags(opentlv_wasm_program_t* p, uint32_t id,
                              tlv_result_t (*class_of)(const void*, const tlv_tag_t*, int64_t*),
                              tlv_result_t (*number_of)(const void*, const tlv_tag_t*, int64_t*)) {
    if (!p || p->program || !id || (!class_of && !number_of)) return TLV_ERR_INVALID_ARG;
    p->tags = (tlv_query_tag_adapter_t){id, NULL, class_of, number_of};
    p->environment.tags = &p->tags;
    return TLV_OK;
}
int opentlv_wasm_program_resolver(opentlv_wasm_program_t* p, tlv_query_resolve_t resolve) {
    if (!p || p->program || !resolve) return TLV_ERR_INVALID_ARG;
    p->options.resolve = resolve;
    p->options.resolve_context = p;
    return TLV_OK;
}
int opentlv_wasm_program_emv_resolver(opentlv_wasm_program_t* p) {
    if (!p || p->program) return TLV_ERR_INVALID_ARG;
#if OPENTLV_EMV
    p->options.resolve = tlv_emv_query_resolve;
    p->options.resolve_context = NULL;
    return TLV_OK;
#else
    return TLV_ERR_UNSUPPORTED;
#endif
}
int opentlv_wasm_resolved_tag(opentlv_wasm_program_t* p, tlv_tag_t* result, const uint8_t* tag,
                              size_t size) {
    if (!size || size > p->options.max_resolved_tag) return TLV_ERR_INVALID_TAG;
    if (p->resolved_capacity < size) {
        uint8_t* resized = realloc(p->resolved, size);
        if (!resized) return TLV_ERR_OUT_OF_MEMORY;
        p->resolved = resized;
        p->resolved_capacity = size;
    }
    memcpy(p->resolved, tag, size);
    *result = tlv_tag(p->resolved, size);
    return TLV_OK;
}
void opentlv_wasm_program_retain(opentlv_wasm_program_t* p) {
    ++p->references;
}
const char* opentlv_wasm_schema_validate(opentlv_wasm_program_t* owner, const uint32_t* programs,
                                         const uint32_t* names, size_t count,
                                         opentlv_wasm_document_t* document, const uint8_t* data,
                                         size_t size, size_t depth, size_t nodes, size_t work,
                                         size_t contexts, size_t value_capacity,
                                         int measure_values) {
    tlv_result_t rc =
        count > SIZE_MAX / sizeof(tlv_schema_query_rule_t) ? TLV_ERR_OVERFLOW : TLV_OK;
    tlv_schema_query_rule_t* rules = rc == TLV_OK && count ? calloc(count, sizeof *rules) : NULL;
    if (rc == TLV_OK && count && !rules) rc = TLV_ERR_OUT_OF_MEMORY;
    tlv_schema_query_diagnostic_t diagnostic = {0};
    if (rc == TLV_OK) {
        for (size_t i = 0; i < count; ++i) {
            opentlv_wasm_program_t* context = (opentlv_wasm_program_t*)(uintptr_t)programs[2 * i];
            opentlv_wasm_program_t* assertion =
                (opentlv_wasm_program_t*)(uintptr_t)programs[2 * i + 1];
            rules[i] = (tlv_schema_query_rule_t){context->program, assertion->program,
                                                 &assertion->environment,
                                                 (const char*)(uintptr_t)names[i]};
        }
        rc = opentlv_binding_schema_run(data, size, document ? document->document : NULL,
                                        owner->environment.format, rules, count, depth, nodes, work,
                                        contexts, value_capacity, measure_values, &diagnostic);
    }
    free(rules);
    query_status(&owner->reply, rc, &diagnostic.query);
    query_field(&owner->reply, "rule", diagnostic.rule);
    /* Only a failed assertion has Schema detail; other failures omit "schema". Its
     * common evidence (location, path, expected text) is the error's own. */
    if (diagnostic.query.cause != TLV_QUERY_CAUSE_SCHEMA) return query_reply(&owner->reply);
    const tlv_schema_detail_t* schema = &diagnostic.query.detail.schema;
    builder_text(&owner->reply, ",\"schema\":{\"tag\":\"");
    builder_hex(&owner->reply, schema->tag.data, schema->tag.size);
    builder_text(&owner->reply, "\",\"field\":");
    builder_json_string(&owner->reply, schema->field ? schema->field : "");
    query_field(&owner->reply, "kind", schema->kind);
    builder_text(&owner->reply, ",\"kind_name\":");
    builder_json_string(&owner->reply, tlv_schema_issue_kind_string(schema->kind));
    builder_text(&owner->reply, "}");
    return query_reply(&owner->reply);
}
int opentlv_wasm_program_variable(opentlv_wasm_program_t* p, const char* name, int type) {
    if (!p || p->program || !name) return TLV_ERR_INVALID_ARG;
    if (p->options.variable_count == QUERY_DECLARATIONS) return TLV_ERR_LIMIT;
    char* copy = query_copy_name(name);
    if (!copy) return TLV_ERR_OUT_OF_MEMORY;
    tlv_query_variable_t* v = p->variables + p->options.variable_count++;
    v->name = copy;
    v->type = (tlv_query_result_kind_t)type;
    return TLV_OK;
}
int opentlv_wasm_program_name(opentlv_wasm_program_t* p, const char* name, const uint8_t* data,
                              size_t size) {
    if (!p || p->program || !name || (!data && size)) return TLV_ERR_INVALID_ARG;
    if (p->name_count == QUERY_DECLARATIONS) return TLV_ERR_LIMIT;
    wasm_name_t n = {query_copy_name(name), malloc(size ? size : 1), size};
    if (!n.name || !n.bytes) {
        free(n.name);
        free(n.bytes);
        return TLV_ERR_OUT_OF_MEMORY;
    }
    if (size) memcpy(n.bytes, data, size);
    p->names[p->name_count++] = n;
    return TLV_OK;
}
int opentlv_wasm_program_option(opentlv_wasm_program_t* p, int key, size_t value) {
    if (!p || p->program) return TLV_ERR_INVALID_ARG;
    switch (key) {
        case 0: p->options.optimize = value != 0; break;
        case 1: p->options.max_text = value; break;
        case 2: p->options.max_tokens = value; break;
        case 3: p->options.max_nesting = value; break;
        case 4: p->options.max_states = value; break;
        case 5: p->options.max_pattern = value; break;
        case 6: p->options.max_resolved_tag = value; break;
        default: return TLV_ERR_INVALID_ARG;
    }
    return TLV_OK;
}
int opentlv_wasm_program_provider(opentlv_wasm_program_t* p, int function, uint32_t id,
                                  size_t capacity, tlv_query_decode_t decode) {
    if (!p || p->program || function < 0 || function > TLV_QUERY_DATE || !id || !decode)
        return TLV_ERR_INVALID_ARG;
    size_t slot = 0;
    while (slot < p->environment.hook_count &&
           p->hooks[slot].function != (tlv_query_conversion_t)function)
        ++slot;
    if (slot == p->environment.hook_count) ++p->environment.hook_count;
    p->hooks[slot] =
        (tlv_query_hook_t){id, (tlv_query_conversion_t)function, capacity, 1, NULL, decode};
    return TLV_OK;
}
void opentlv_wasm_provider_integer(tlv_query_result_t* result, uint32_t low, uint32_t high) {
    memset(result, 0, sizeof *result);
    result->kind = TLV_QUERY_RESULT_INTEGER;
    uint64_t bits = ((uint64_t)high << 32) | low;
    memcpy(&result->integer, &bits, sizeof bits);
}
void opentlv_wasm_provider_text(tlv_query_result_t* result, const uint8_t* data, size_t size) {
    memset(result, 0, sizeof *result);
    result->kind = TLV_QUERY_RESULT_STRING;
    result->data = data;
    result->size = size;
}
size_t opentlv_wasm_provider_event(const tlv_tree_event_t* event, int field) {
    if (!event) return 0;
    switch (field) {
        case 0: return (size_t)event->kind;
        case 1: return event->depth;
        case 2: return event->offset;
        case 3: return (size_t)(uintptr_t)event->element.tag.data;
        case 4: return event->element.tag.size;
        case 5: return (size_t)(uintptr_t)event->element.value.data;
        case 6: return event->element.value.size;
        default: return 0;
    }
}
const char* opentlv_wasm_program_compile(opentlv_wasm_program_t* p, const uint8_t* text,
                                         size_t size, int image) {
    if (p->program) {
        query_status(&p->reply, TLV_ERR_INVALID_ARG, NULL);
        return query_reply(&p->reply);
    }
    tlv_query_diagnostic_t d = {0};
    size_t                 bytes = 0, alignment;
    tlv_result_t           rc =
        image ? tlv_query_program_load_scratch(text, size, &p->options, &bytes, &alignment, &d)
              : tlv_query_compile_prepare_size((const char*)text, size, &p->options, &bytes,
                                               &alignment, &d);
    void* scratch = rc == TLV_OK ? malloc(bytes ? bytes : 1) : NULL;
    if (rc == TLV_OK && !scratch) rc = TLV_ERR_OUT_OF_MEMORY;
    p->info.struct_size = sizeof p->info;
    const tlv_query_program_t* prepared = NULL;
    if (rc == TLV_OK && !image)
        rc = tlv_query_compile_prepare((const char*)text, size, &p->options, scratch, bytes,
                                       &prepared, &p->info, &d);
    if (rc == TLV_OK) {
        p->image = malloc(image ? (size ? size : 1) : p->info.program_size);
        if (!p->image) rc = TLV_ERR_OUT_OF_MEMORY;
    }
    if (rc == TLV_OK && image) {
        memcpy(p->image, text, size);
        rc = tlv_query_program_load(p->image, size, &p->options, scratch, bytes, &p->program,
                                    &p->info, &d);
    } else if (rc == TLV_OK) {
        size_t validation_size;
        rc = tlv_query_program_load_scratch(prepared, p->info.program_size, &p->options,
                                            &validation_size, &alignment, &d);
        void* validation = rc == TLV_OK ? malloc(validation_size ? validation_size : 1) : NULL;
        if (rc == TLV_OK && !validation) rc = TLV_ERR_OUT_OF_MEMORY;
        if (rc == TLV_OK)
            rc = tlv_query_compile_commit(prepared, p->info.program_size, &p->options, validation,
                                          validation_size, p->image, p->info.program_size, &p->info,
                                          &d);
        free(validation);
        if (rc == TLV_OK) p->program = p->image;
    }
    free(scratch);
    if (rc != TLV_OK) {
        free(p->image);
        p->image = NULL;
    }
    query_status(&p->reply, rc, &d);
    if (rc == TLV_OK) {
        builder_text(&p->reply, ",\"info\":{\"language_version\":1");
#define FIELD(n) query_field(&p->reply, #n, p->info.n)
        FIELD(program_size);
        FIELD(program_alignment);
        FIELD(scratch_size);
        FIELD(scratch_alignment);
        FIELD(states);
        FIELD(level);
        FIELD(result_kind);
        FIELD(expression_values);
        FIELD(instructions);
        FIELD(variable_slots);
        FIELD(codec_scratch);
        FIELD(pattern_bytes);
        FIELD(optimized_states);
        FIELD(expression_stack);
        FIELD(candidate_size);
        FIELD(candidate_alignment);
        FIELD(frame_states);
        FIELD(decision_timing);
        FIELD(stable_input_required);
        FIELD(constructed_values_required);
#undef FIELD
        builder_text(&p->reply, "}");
        builder_text(&p->reply, ",\"variables\":{");
        for (size_t i = 0; i < tlv_query_program_variable_count(p->program); ++i) {
            tlv_query_variable_info_t variable;
            if (tlv_query_program_variable(p->program, i, &variable) != TLV_OK) break;
            if (i) builder_text(&p->reply, ",");
            builder_text(&p->reply, "\"");
            /* Variable identifiers use the compiler's restricted ASCII grammar. */
            builder_append(&p->reply, variable.name, variable.name_size);
            builder_text(&p->reply, "\":");
            builder_json_string(&p->reply, variable.type == TLV_QUERY_RESULT_INTEGER ? "integer"
                                           : variable.type == TLV_QUERY_RESULT_BYTES ? "bytes"
                                                                                     : "string");
        }
        builder_text(&p->reply, "}");
    }
    return query_reply(&p->reply);
}
const uint8_t* opentlv_wasm_program_image(opentlv_wasm_program_t* p) {
    return p->image;
}
size_t opentlv_wasm_program_image_size(opentlv_wasm_program_t* p) {
    return p->info.program_size;
}
const char* opentlv_wasm_program_render(opentlv_wasm_program_t* p, int explain) {
    if (explain == -1) return p->reply.data;
    size_t       size;
    tlv_result_t rc = explain ? tlv_query_program_explain(p->program, NULL, 0, &size)
                              : tlv_query_program_format(p->program, NULL, 0, &size);
    char*        text = rc == TLV_OK ? malloc(size) : NULL;
    if (rc == TLV_OK && !text) rc = TLV_ERR_OUT_OF_MEMORY;
    if (rc == TLV_OK)
        rc = explain ? tlv_query_program_explain(p->program, text, size, &size)
                     : tlv_query_program_format(p->program, text, size, &size);
    query_status(&p->reply, rc, NULL);
    if (rc == TLV_OK) {
        builder_text(&p->reply, ",\"value\":");
        builder_json_string(&p->reply, text);
    }
    free(text);
    return query_reply(&p->reply);
}
static void wasm_unpin(opentlv_wasm_execution_t* q) {
    while (q->pins) {
        wasm_pin_t* pin = q->pins;
        q->pins = pin->next;
        free(pin);
    }
}
static wasm_pin_t* wasm_pin(opentlv_wasm_execution_t* q, const uint8_t* data, size_t size) {
    if ((!data && size) || size > SIZE_MAX - sizeof(wasm_pin_t)) return NULL;
    wasm_pin_t* pin = malloc(sizeof *pin + size);
    if (!pin) return NULL;
    if (size) memcpy(pin->data, data, size);
    pin->size = size;
    pin->next = q->pins;
    q->pins = pin;
    return pin;
}
static tlv_result_t wasm_execution_reset(opentlv_wasm_execution_t* q) {
    tlv_result_t rc =
        q->retained ? tlv_query_eval_init(q->program->program, &q->program->environment, q->storage,
                                          q->capacity, q->depth, q->nodes, q->work, &q->exec)
                    : tlv_query_exec_init(q->program->program, q->storage, q->capacity, q->depth,
                                          q->nodes, q->work, &q->exec);
    if (rc == TLV_OK) {
        wasm_unpin(q);
        free(q->values);
        q->values = NULL;
        opentlv_wasm_document_free(q->document);
        q->document = NULL;
        q->has_reader = 0;
        q->fed = 0;
    }
    return rc;
}
opentlv_wasm_execution_t* opentlv_wasm_execution_new(opentlv_wasm_program_t* p, size_t depth,
                                                     size_t nodes, size_t work, int retained) {
    size_t       bytes = 0, alignment = 0;
    tlv_result_t rc = retained ? tlv_query_eval_size(p->program, depth, nodes, &bytes, &alignment)
                               : tlv_query_exec_size(p->program, depth, &bytes, &alignment);
    opentlv_wasm_execution_t* q = NULL;
    if (rc == TLV_OK &&
        (bytes > SIZE_MAX - alignment + 1 || depth > SIZE_MAX / sizeof(tlv_tree_frame_t)))
        rc = TLV_ERR_OVERFLOW;
    if (rc == TLV_OK) {
        q = calloc(1, sizeof *q);
        if (!q) rc = TLV_ERR_OUT_OF_MEMORY;
    }
    if (rc == TLV_OK) {
        q->program = p;
        ++p->references;
        q->depth = depth;
        q->nodes = nodes;
        q->work = work;
        q->retained = retained;
        q->capacity = bytes;
        q->allocation = malloc(bytes + alignment - 1);
        q->frames = calloc(depth ? depth : 1, sizeof *q->frames);
        if (!q->allocation || !q->frames)
            rc = TLV_ERR_OUT_OF_MEMORY;
        else {
            q->storage =
                (void*)(((uintptr_t)q->allocation + alignment - 1) & ~(uintptr_t)(alignment - 1));
            rc = wasm_execution_reset(q);
        }
    }
    query_status(&p->reply, rc, NULL);
    query_reply(&p->reply);
    if (rc != TLV_OK) {
        opentlv_wasm_execution_free(q);
        return NULL;
    }
    return q;
}
void opentlv_wasm_execution_free(opentlv_wasm_execution_t* q) {
    if (!q) return;
    wasm_unpin(q);
    free(q->allocation);
    free(q->frames);
    free(q->values);
    free(q->reply.data);
    opentlv_wasm_document_free(q->document);
    opentlv_wasm_program_free(q->program);
    free(q);
}
const char* opentlv_wasm_execution_input(opentlv_wasm_execution_t* q, const uint8_t* data,
                                         size_t size, size_t discard, int final) {
    tlv_result_t rc = q->document || q->fed         ? TLV_ERR_INVALID_STATE
                      : (!q->has_reader && discard) ? TLV_ERR_INVALID_ARG
                                                    : TLV_OK;
    wasm_pin_t*  pin = rc == TLV_OK ? wasm_pin(q, data, size) : NULL;
    if (rc == TLV_OK && !pin) rc = TLV_ERR_OUT_OF_MEMORY;
    if (rc == TLV_OK)
        rc = q->has_reader ? tlv_tree_reader_set_input(&q->reader, pin->data, size, discard, final)
             : final
                 ? tlv_tree_reader_init(&q->reader, pin->data, size, q->program->environment.format,
                                        q->frames, q->depth, q->depth, q->nodes)
                 : tlv_tree_reader_init_incremental(&q->reader, pin->data, size,
                                                    q->program->environment.format, q->frames,
                                                    q->depth, q->depth, q->nodes);
    if (rc == TLV_OK) q->has_reader = 1;
    query_status(&q->reply, rc, NULL);
    return query_reply(&q->reply);
}
const char* opentlv_wasm_execution_bind(opentlv_wasm_execution_t* q, const char* name, int type,
                                        const char* integer, const uint8_t* data, size_t size) {
    tlv_query_diagnostic_t d = {0};
    wasm_pin_t*            pin = wasm_pin(q, data, size);
    int64_t                value = 0;
    tlv_result_t           rc = pin ? TLV_OK : TLV_ERR_OUT_OF_MEMORY;
    if (rc == TLV_OK && type == TLV_QUERY_RESULT_INTEGER) {
        char* end;
        value = strtoll(integer, &end, 10);
        if (*end) rc = TLV_ERR_INVALID_ARG;
    }
    if (rc == TLV_OK)
        rc = tlv_query_exec_bind(q->exec, name, (tlv_query_result_kind_t)type, value, pin->data,
                                 size, &d);
    query_status(&q->reply, rc, &d);
    return query_reply(&q->reply);
}
static tlv_visit_result_t wasm_pull(const tlv_tree_event_t* event, void* context) {
    *(tlv_tree_event_t*)context = *event;
    return TLV_VISIT_STOP;
}
static tlv_visit_result_t wasm_drain(const tlv_tree_event_t* event, void* context) {
    (void)event;
    (void)context;
    return TLV_VISIT_CONTINUE;
}
static void wasm_event(builder_t* b, const tlv_tree_event_t* event) {
    builder_text(b, ",\"value\":{\"offset\":");
    builder_number(b, event->offset);
    query_field(b, "depth", event->depth);
    query_field(b, "kind", event->kind);
    builder_text(b, ",\"tag\":\"");
    builder_hex(b, event->element.tag.data, event->element.tag.size);
    builder_text(b, "\",\"bytes\":\"");
    builder_hex(b, event->element.value.data, event->element.value.size);
    builder_text(b, "\"}");
}
const char* opentlv_wasm_execution_feed(opentlv_wasm_execution_t* q, int kind, const uint8_t* tag,
                                        size_t tag_size, const uint8_t* value, size_t value_size,
                                        size_t depth, size_t offset, int skipped) {
    tlv_query_diagnostic_t diagnostic = {0};
    tlv_result_t           rc = q->has_reader || q->document ? TLV_ERR_INVALID_STATE : TLV_OK;
    tlv_tree_event_t       event = {0};
    int                    matched = 0;
    if (rc == TLV_OK) {
        wasm_pin_t* tag_pin = wasm_pin(q, tag, tag_size);
        wasm_pin_t* value_pin = wasm_pin(q, value, value_size);
        if (!tag_pin || !value_pin)
            rc = TLV_ERR_OUT_OF_MEMORY;
        else {
            event.kind = (tlv_tree_event_kind_t)kind;
            event.element.tag = tlv_tag(tag_pin->data, tag_size);
            event.element.value.data = value_pin->data;
            event.element.value.size = value_size;
            event.depth = depth;
            event.offset = offset;
            event.skipped = skipped;
            q->fed = 1;
            rc = tlv_query_exec_feed(q->exec, &event, &matched, &diagnostic);
            if (rc == TLV_OK && matched && q->program->info.level == TLV_QUERY_S1)
                rc = tlv_query_exec_selected(q->exec, &event);
        }
    }
    query_status(&q->reply, rc, &diagnostic);
    if (rc == TLV_OK && matched)
        wasm_event(&q->reply, &event);
    else if (rc == TLV_OK)
        builder_text(&q->reply, ",\"value\":null");
    return query_reply(&q->reply);
}
const char* opentlv_wasm_execution_feed_source(opentlv_wasm_execution_t* q, int kind,
                                               const uint8_t* source, size_t size, size_t depth,
                                               size_t offset, int skipped) {
    tlv_result_t           rc = q->has_reader || q->document ? TLV_ERR_INVALID_STATE
                                : kind == TLV_TREE_END       ? TLV_ERR_INVALID_ARG
                                                             : TLV_OK;
    tlv_query_diagnostic_t diagnostic = {0};
    tlv_tree_event_t       event = {0};
    int                    matched = 0;
    wasm_pin_t*            pin = rc == TLV_OK ? wasm_pin(q, source, size) : NULL;
    if (rc == TLV_OK && !pin) rc = TLV_ERR_OUT_OF_MEMORY;
    tlv_decoded_t decoded;
    if (rc == TLV_OK)
        rc = tlv_format_decode(q->program->environment.format, pin->data, size, &decoded, NULL);
    if (rc == TLV_OK && decoded.source.size != size) rc = TLV_ERR_INVALID_ARG;
    if (rc == TLV_OK) {
        event.kind = (tlv_tree_event_kind_t)kind;
        event.depth = depth;
        event.offset = offset;
        event.skipped = skipped;
        event.element = decoded.element;
        event.source = decoded.source;
        q->fed = 1;
        rc = tlv_query_exec_feed(q->exec, &event, &matched, &diagnostic);
        if (rc == TLV_OK && matched && q->program->info.level == TLV_QUERY_S1)
            rc = tlv_query_exec_selected(q->exec, &event);
    }
    query_status(&q->reply, rc, &diagnostic);
    if (rc == TLV_OK && matched)
        wasm_event(&q->reply, &event);
    else if (rc == TLV_OK)
        builder_text(&q->reply, ",\"value\":null");
    return query_reply(&q->reply);
}
const char* opentlv_wasm_execution_operation(opentlv_wasm_execution_t* q, int operation,
                                             size_t argument) {
    tlv_query_diagnostic_t d = {0};
    tlv_result_t           rc = TLV_OK;
    tlv_tree_event_t       event = {0};
    tlv_query_result_t     result = {0};
    tlv_query_exec_info_t  info = {0};
    info.struct_size = sizeof info;
    int         found = 0;
    size_t      ordinal = 0;
    tlv_node_t* node = NULL;
    switch (operation) {
        case 0: rc = wasm_execution_reset(q); break;
        case 1:
            if (q->document) {
#if OPENTLV_DOCUMENT
                rc = tlv_document_query_next(q->exec, &node, &d);
#else
                rc = TLV_ERR_UNSUPPORTED;
#endif
            } else if (q->fed && q->retained)
                rc = tlv_query_result_next(q->exec, &event);
            else if (!q->has_reader || q->program->info.result_kind != TLV_QUERY_RESULT_NODES)
                rc = TLV_ERR_INVALID_ARG;
            else {
                event.kind = (tlv_tree_event_kind_t)-1;
                rc = tlv_query_program_visit(&q->reader, q->exec, wasm_pull, &event, &d);
                if (rc == TLV_OK && (int)event.kind == -1) rc = TLV_END;
            }
            break;
        case 2: rc = tlv_query_exec_result(q->exec, &result); break;
        case 3: rc = tlv_query_exec_info(q->exec, &info); break;
        case 4:
            rc = q->has_reader
                     ? tlv_query_program_exists(&q->reader, q->exec, argument != 0, &found, &d)
                     : TLV_ERR_INVALID_ARG;
            break;
        case 5: rc = tlv_query_exec_context(q->exec, argument); break;
        case 6: rc = tlv_query_exec_pruning(q->exec, argument != 0); break;
        case 7:
            rc = q->has_reader ? tlv_query_program_visit(&q->reader, q->exec, wasm_drain, NULL, &d)
                               : tlv_query_exec_finish(q->exec, &d);
            break;
        case 8: rc = tlv_query_result_next_ordinal(q->exec, &event, &ordinal); break;
        default: rc = TLV_ERR_INVALID_ARG; break;
    }
    query_status(&q->reply, rc, &d);
    if (rc == TLV_OK && operation == 8) {
        wasm_event(&q->reply, &event);
        query_field(&q->reply, "ordinal", ordinal);
    } else if (rc == TLV_OK && operation == 1) {
        if (!q->document) wasm_event(&q->reply, &event);
#if OPENTLV_DOCUMENT
        else {
            builder_text(&q->reply, ",\"value\":{\"node\":");
            builder_number(&q->reply, (size_t)(uintptr_t)node);
            builder_text(&q->reply, ",\"identity\":");
            query_integer(&q->reply, (int64_t)tlv_node_identity(node));
            builder_text(&q->reply, "}");
        }
#endif
    } else if (rc == TLV_OK && operation == 2) {
        query_field(&q->reply, "kind", result.kind);
        builder_text(&q->reply, ",\"value\":");
        if (result.kind == TLV_QUERY_RESULT_BOOL)
            builder_text(&q->reply, result.boolean ? "true" : "false");
        else if (result.kind == TLV_QUERY_RESULT_INTEGER)
            query_integer(&q->reply, result.integer);
        else if (result.kind == TLV_QUERY_RESULT_BYTES || result.kind == TLV_QUERY_RESULT_STRING) {
            builder_text(&q->reply, "\"");
            builder_hex(&q->reply, result.data, result.size);
            builder_text(&q->reply, "\"");
        } else
            builder_text(&q->reply, "null");
    } else if (rc == TLV_OK && operation == 3) {
        builder_text(&q->reply, ",\"value\":{\"elements\":");
        builder_number(&q->reply, info.elements);
        query_field(&q->reply, "work", info.work);
        query_field(&q->reply, "finished", info.finished);
        query_field(&q->reply, "full_validation", info.full_validation);
        query_field(&q->reply, "invalid", info.invalid);
        query_field(&q->reply, "skipped_subtrees", info.skipped_subtrees);
        builder_text(&q->reply, "}");
    } else if (rc == TLV_OK && operation == 4)
        builder_text(&q->reply, found ? ",\"value\":true" : ",\"value\":false");
    return query_reply(&q->reply);
}
opentlv_wasm_document_t* opentlv_wasm_document_new(opentlv_wasm_program_t* p, const uint8_t* data,
                                                   size_t size, int retain_source_locations) {
    tlv_result_t             rc = TLV_ERR_UNSUPPORTED;
    opentlv_wasm_document_t* doc = NULL;
#if OPENTLV_DOCUMENT
    doc = calloc(1, sizeof *doc);
    rc = doc ? TLV_OK : TLV_ERR_OUT_OF_MEMORY;
    if (doc) {
        doc->references = 1;
        doc->program = p;
        ++p->references;
        tlv_document_options_t options;
        rc = tlv_document_options_init(&options, p->environment.format);
        options.retain_source_locations = retain_source_locations;
        if (rc == TLV_OK) rc = tlv_document_parse(data, size, &options, &doc->document, NULL);
    }
#else
    (void)data;
    (void)size;
    (void)retain_source_locations;
#endif
    query_status(&p->reply, rc, NULL);
    query_reply(&p->reply);
    if (rc != TLV_OK) {
        opentlv_wasm_document_free(doc);
        return NULL;
    }
    return doc;
}
void opentlv_wasm_document_free(opentlv_wasm_document_t* doc) {
    if (!doc || --doc->references) return;
#if OPENTLV_DOCUMENT
    tlv_document_free(doc->document);
#endif
    opentlv_wasm_program_free(doc->program);
    free(doc);
}
const char* opentlv_wasm_document_encode(opentlv_wasm_document_t* doc) {
    builder_t*   b = &doc->program->reply;
    tlv_result_t rc = TLV_ERR_UNSUPPORTED;
    uint8_t*     data = NULL;
    size_t       length = 0;
#if OPENTLV_DOCUMENT
    rc = tlv_document_encoded_size(doc->document, &length);
    if (rc == TLV_OK) {
        data = malloc(length ? length : 1);
        if (!data) rc = TLV_ERR_OUT_OF_MEMORY;
    }
    if (rc == TLV_OK) rc = tlv_document_encode(doc->document, data, length, &length);
#endif
    query_status(b, rc, NULL);
    if (rc == TLV_OK) {
        builder_text(b, ",\"value\":\"");
        builder_hex(b, data, length);
        builder_text(b, "\"");
    }
    free(data);
    return query_reply(b);
}
const char* opentlv_wasm_execution_document(opentlv_wasm_execution_t* q,
                                            opentlv_wasm_document_t* doc, size_t capacity) {
    tlv_query_diagnostic_t d = {0};
    tlv_result_t           rc = TLV_ERR_UNSUPPORTED;
#if OPENTLV_DOCUMENT
    rc = q->has_reader || q->document ? TLV_ERR_INVALID_STATE
         : !q->retained               ? TLV_ERR_INVALID_ARG
                                      : TLV_OK;
    tlv_tree_writer_workspace_t staging = {0};
    if (rc == TLV_OK && q->program->info.constructed_values_required) {
        if (q->depth == SIZE_MAX || q->depth + 1 > SIZE_MAX / sizeof *staging.frames)
            rc = TLV_ERR_OVERFLOW;
        else {
            staging.frames = calloc(q->depth + 1, sizeof *staging.frames);
            staging.frame_capacity = q->depth + 1;
            staging.data = malloc(capacity ? capacity : 1);
            staging.data_capacity = capacity;
            staging.scratch = malloc(capacity ? capacity : 1);
            staging.scratch_capacity = capacity;
            q->values = malloc(capacity ? capacity : 1);
            if (!staging.frames || !staging.data || !staging.scratch || !q->values)
                rc = TLV_ERR_OUT_OF_MEMORY;
        }
    }
    if (rc == TLV_OK) {
        q->document = doc;
        ++doc->references;
        rc = tlv_document_query_evaluate(
            doc->document, q->exec, NULL, q->values,
            q->program->info.constructed_values_required ? capacity : 0,
            q->program->info.constructed_values_required ? &staging : NULL, &d);
    }
    free(staging.frames);
    free(staging.data);
    free(staging.scratch);
#else
    (void)doc;
    (void)capacity;
#endif
    query_status(&q->reply, rc, &d);
    return query_reply(&q->reply);
}
const char* opentlv_wasm_execution_edit(opentlv_wasm_execution_t* q, int kind, const uint8_t* tag,
                                        size_t tag_size, const uint8_t* value, size_t value_size,
                                        size_t capacity) {
    tlv_result_t           rc = TLV_ERR_UNSUPPORTED;
    size_t                 applied = 0;
    tlv_query_diagnostic_t d = {0};
#if OPENTLV_DOCUMENT
    rc = q->document ? TLV_OK : TLV_ERR_INVALID_ARG;
    if (rc == TLV_OK && capacity > SIZE_MAX / sizeof(tlv_node_t*)) rc = TLV_ERR_OVERFLOW;
    tlv_node_t** targets = rc == TLV_OK && capacity ? calloc(capacity, sizeof *targets) : NULL;
    if (rc == TLV_OK && capacity && !targets) rc = TLV_ERR_OUT_OF_MEMORY;
    if (rc == TLV_OK)
        rc = tlv_document_query_edit(q->document->document, q->exec,
                                     (tlv_document_query_edit_kind_t)kind, tlv_tag(tag, tag_size),
                                     value, value_size, targets, capacity, &applied, &d);
    free(targets);
#else
    (void)q;
    (void)kind;
    (void)tag;
    (void)tag_size;
    (void)value;
    (void)value_size;
    (void)capacity;
#endif
    query_status(&q->reply, rc, &d);
    query_field(&q->reply, "applied", applied);
    return query_reply(&q->reply);
}
const char* opentlv_wasm_document_node(opentlv_wasm_document_t* doc, size_t address,
                                       const char* identity, int operation, const uint8_t* data,
                                       size_t size) {
    builder_t*   b = &doc->program->reply;
    tlv_result_t rc = TLV_ERR_UNSUPPORTED;
#if OPENTLV_DOCUMENT
    tlv_node_t* node = (tlv_node_t*)(uintptr_t)address;
    rc = TLV_OK;
    if (node && (!identity ||
                 tlv_document_node_identity(doc->document, node) != strtoull(identity, NULL, 10)))
        rc = TLV_ERR_INVALID_ARG;
    if (rc == TLV_OK) {
        switch (operation) {
            case 0: node = tlv_document_first(doc->document); break;
            case 1: node = tlv_node_first_child(node); break;
            case 2: node = tlv_node_next(node); break;
            case 3: node = tlv_node_parent(node); break;
            case 4: rc = node ? tlv_node_set_value(node, data, size) : TLV_ERR_INVALID_ARG; break;
            case 5:
                if (node)
                    tlv_node_erase(node);
                else
                    rc = TLV_ERR_INVALID_ARG;
                node = NULL;
                break;
            case 6: break;
            default: rc = TLV_ERR_INVALID_ARG;
        }
    }
    query_status(b, rc, NULL);
    if (rc == TLV_OK) {
        builder_text(b, ",\"value\":");
        if (!node)
            builder_text(b, "null");
        else {
            builder_text(b, "{\"node\":");
            builder_number(b, (size_t)(uintptr_t)node);
            builder_text(b, ",\"identity\":");
            query_integer(b, (int64_t)tlv_node_identity(node));
            tlv_tag_t tag = tlv_node_tag(node);
            builder_text(b, ",\"tag\":\"");
            builder_hex(b, tag.data, tag.size);
            builder_text(b, "\",\"bytes\":\"");
            if (!tlv_node_is_constructed(node))
                builder_hex(b, tlv_node_value_data(node), tlv_node_value_size(node));
            builder_text(b, "\"");
            query_field(b, "constructed", tlv_node_is_constructed(node));
            builder_text(b, "}");
        }
    }
#else
    (void)address;
    (void)identity;
    (void)operation;
    (void)data;
    (void)size;
    query_status(b, rc, NULL);
#endif
    return query_reply(b);
}
