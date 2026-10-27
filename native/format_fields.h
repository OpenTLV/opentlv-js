// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel
/* Included once by opentlv_wasm.c. Owns configuration and marshals values;
 * all field and framing validation/processing remains in the public C Core. */
#include <inttypes.h>
#include <tlv/field/escaped.h>
#include <tlv/field/packed.h>
#include <tlv/field/variable.h>
#include <tlv/formats/escaped.h>
#include <tlv/formats/packed.h>
#include <tlv/formats/variable.h>

enum {
    FIELD_FIXED_TAG,
    FIELD_VARIABLE_TAG,
    FIELD_FIXED_LENGTH,
    FIELD_VARIABLE_LENGTH,
    FIELD_ESCAPED_LENGTH,
    FIELD_PACKED
};
typedef struct wasm_field {
    size_t references;
    int kind;
    tlv_fixed_identifier_t fixed_tag;
    tlv_variable_identifier_t variable_tag;
    tlv_fixed_length_t fixed_length;
    tlv_variable_length_t variable_length;
    tlv_escaped_length_t escaped;
    tlv_packed_field_t packed;
    tlv_identifier_policy_t identifier_policy;
    tlv_length_policy_t length_policy;
    uint8_t* forbidden;
} wasm_field_t;

static tlv_byte_order_t field_order(uint32_t big) {
    return big ? TLV_BYTE_ORDER_BIG_ENDIAN : TLV_BYTE_ORDER_LITTLE_ENDIAN;
}
static uint64_t field_u64(const uint32_t* p) { return ((uint64_t)p[1] << 32) | p[0]; }
static void field_number(builder_t* b, uint64_t value) {
    char text[32];
    (void)snprintf(text, sizeof text, "\"%" PRIu64 "\"", value);
    builder_text(b, text);
}
static char* field_reply(builder_t* b, tlv_result_t rc) {
    builder_text(b, ",\"code\":");
    builder_number(b, rc);
    builder_text(b, "}");
    if (b->failed) {
        free(b->data);
        return NULL;
    }
    return b->data; /* caller frees with opentlv_wasm_free */
}
static tlv_result_t field_read_tag(const wasm_field_t* f, const uint8_t* data, size_t size,
                                   tlv_tag_t* tag, size_t* consumed) {
    if (f->kind == FIELD_FIXED_TAG)
        return tlv_fixed_identifier_read(&f->fixed_tag, data, size, tag, consumed);
    if (f->kind == FIELD_VARIABLE_TAG)
        return tlv_variable_identifier_read(&f->variable_tag, data, size, tag, consumed);
    return TLV_ERR_INVALID_ARG;
}
static tlv_result_t field_write_tag(const wasm_field_t* f, const tlv_tag_t* tag, uint8_t* data,
                                    size_t size, size_t* written) {
    if (f->kind == FIELD_FIXED_TAG)
        return tlv_fixed_identifier_write(&f->fixed_tag, tag, data, size, written);
    if (f->kind == FIELD_VARIABLE_TAG)
        return tlv_variable_identifier_write(&f->variable_tag, tag, data, size, written);
    return TLV_ERR_INVALID_ARG;
}
static tlv_result_t field_read_length(const wasm_field_t* f, const uint8_t* data, size_t size,
                                      tlv_size_t* value, size_t* consumed) {
    switch (f->kind) {
    case FIELD_FIXED_LENGTH:
        return tlv_fixed_length_read(&f->fixed_length, data, size, value, consumed);
    case FIELD_VARIABLE_LENGTH:
        return tlv_variable_length_read(&f->variable_length, data, size, value, consumed);
    case FIELD_ESCAPED_LENGTH:
        return tlv_escaped_length_read(&f->escaped, data, size, value, consumed);
    default:
        return TLV_ERR_INVALID_ARG;
    }
}
static tlv_result_t field_write_length(const wasm_field_t* f, tlv_size_t value, uint8_t* data,
                                       size_t size, size_t* written) {
    switch (f->kind) {
    case FIELD_FIXED_LENGTH:
        return tlv_fixed_length_write(&f->fixed_length, value, data, size, written);
    case FIELD_VARIABLE_LENGTH:
        return tlv_variable_length_write(&f->variable_length, value, data, size, written);
    case FIELD_ESCAPED_LENGTH:
        return tlv_escaped_length_write(&f->escaped, value, data, size, written);
    default:
        return TLV_ERR_INVALID_ARG;
    }
}
OPENTLV_WASM_API void opentlv_wasm_field_free(wasm_field_t* f) {
    if (!f || --f->references)
        return;
    free(f->forbidden);
    free(f);
}
/* options is a boundary-owned uint32 vector, not a mirrored Core struct. */
OPENTLV_WASM_API wasm_field_t* opentlv_wasm_field_new(int kind, const uint32_t* p,
                                                      const uint8_t* forbidden, size_t count,
                                                      int* result) {
    wasm_field_t* f = calloc(1, sizeof *f);
    *result = TLV_ERR_OUT_OF_MEMORY;
    if (!f)
        return NULL;
    f->references = 1;
    f->kind = kind;
    if (count) {
        f->forbidden = malloc(count);
        if (!f->forbidden) {
            opentlv_wasm_field_free(f);
            return NULL;
        }
        memcpy(f->forbidden, forbidden, count);
    }
    f->identifier_policy = (tlv_identifier_policy_t){f->forbidden, count, p[6], p[7]};
    f->length_policy = (tlv_length_policy_t){p[4], p[5], p[6], p[7], field_u64(p + 8)};
    f->fixed_tag = (tlv_fixed_identifier_t){p[0]};
    f->variable_tag = (tlv_variable_identifier_t){
        (uint8_t)p[0], (uint8_t)p[1], (uint8_t)p[2],
        (uint8_t)p[3], p[4],          p[5] ? &f->identifier_policy : NULL};
    f->fixed_length = (tlv_fixed_length_t){p[0], field_order(p[1])};
    f->variable_length = (tlv_variable_length_t){(uint8_t)p[0], (uint8_t)p[1], field_order(p[2]),
                                                 p[3] ? &f->length_policy : NULL};
    f->escaped = (tlv_escaped_length_t){(uint8_t)p[0], p[1], field_order(p[2]), field_u64(p + 3),
                                        field_u64(p + 5)};
    f->packed = (tlv_packed_field_t){p[0], p[1], p[2], field_order(p[3])};
    size_t consumed = 0;
    tlv_tag_t tag;
    tlv_size_t value;
    uint64_t packed;
    const uint8_t empty = 0;
    tlv_result_t rc = kind <= FIELD_VARIABLE_TAG ? field_read_tag(f, NULL, 0, &tag, &consumed)
                      : kind == FIELD_PACKED ? tlv_packed_field_read(&f->packed, &empty, 0, &packed)
                                             : field_read_length(f, NULL, 0, &value, &consumed);
    *result = rc == TLV_ERR_TRUNCATED ? TLV_OK : rc;
    if (*result != TLV_OK) {
        opentlv_wasm_field_free(f);
        return NULL;
    }
    return f;
}
/* operation: 0 read; 1 encode/packed update. The input is never retained. */
OPENTLV_WASM_API char* opentlv_wasm_field_operation(wasm_field_t* f, int operation,
                                                    const uint8_t* input, size_t size, uint32_t low,
                                                    uint32_t high) {
    builder_t b = {0};
    builder_text(&b, "{\"value\":");
    size_t consumed = 0, written = 0;
    tlv_size_t value = ((uint64_t)high << 32) | low;
    tlv_tag_t tag = tlv_tag(input, size);
    tlv_result_t rc;
    uint8_t* output = NULL;
    if (!operation) {
        if (f->kind <= FIELD_VARIABLE_TAG) {
            rc = field_read_tag(f, input, size, &tag, &consumed);
            builder_text(&b, "\"");
            if (rc == TLV_OK)
                builder_hex(&b, tag.data, tag.size);
            builder_text(&b, "\"");
        } else {
            uint64_t packed = 0;
            rc = f->kind == FIELD_PACKED ? tlv_packed_field_read(&f->packed, input, size, &packed)
                                         : field_read_length(f, input, size, &value, &consumed);
            if (f->kind == FIELD_PACKED) {
                value = packed;
                consumed = rc == TLV_OK ? f->packed.storage_size : 0;
            }
            field_number(&b, rc == TLV_OK ? value : 0);
        }
    } else {
        if (f->kind == FIELD_PACKED) {
            written = size;
            output = malloc(size ? size : 1);
            if (output && size)
                memcpy(output, input, size);
            rc = output ? tlv_packed_field_write(&f->packed, output, size, value)
                        : TLV_ERR_OUT_OF_MEMORY;
        } else {
            rc = f->kind <= FIELD_VARIABLE_TAG ? field_write_tag(f, &tag, NULL, 0, &written)
                                               : field_write_length(f, value, NULL, 0, &written);
            if (rc == TLV_OK) {
                output = malloc(written ? written : 1);
                rc = output ? (f->kind <= FIELD_VARIABLE_TAG
                                   ? field_write_tag(f, &tag, output, written, &written)
                                   : field_write_length(f, value, output, written, &written))
                            : TLV_ERR_OUT_OF_MEMORY;
            }
        }
        builder_text(&b, "\"");
        if (rc == TLV_OK)
            builder_hex(&b, output, written);
        builder_text(&b, "\"");
    }
    free(output);
    builder_text(&b, ",\"consumed\":");
    builder_number(&b, consumed);
    return field_reply(&b, rc);
}

typedef struct {
    wasm_field_t *identifier, *length;
    tlv_format_t base;
    tlv_tagged_fields_composition_t tagged;
    tlv_variable_format_t variable;
    tlv_escaped_format_t escaped;
    tlv_packed_layout_t packed;
    tlv_constructed_bit_t constructed;
    tlv_tag_t* tags;
    uint8_t* storage;
    size_t count;
} wasm_composition_t;
static tlv_result_t composed_read_tag(const void* context, const uint8_t* data, size_t size,
                                      tlv_tag_t* tag, size_t* used) {
    return field_read_tag(((const wasm_composition_t*)context)->identifier, data, size, tag, used);
}
static tlv_result_t composed_write_tag(const void* context, const tlv_tag_t* tag, uint8_t* data,
                                       size_t size, size_t* used) {
    return field_write_tag(((const wasm_composition_t*)context)->identifier, tag, data, size, used);
}
static tlv_result_t composed_read_length(const void* context, const uint8_t* data, size_t size,
                                         tlv_size_t* value, size_t* used) {
    return field_read_length(((const wasm_composition_t*)context)->length, data, size, value, used);
}
static tlv_result_t composed_write_length(const void* context, tlv_size_t value, uint8_t* data,
                                          size_t size, size_t* used) {
    return field_write_length(((const wasm_composition_t*)context)->length, value, data, size,
                              used);
}
static tlv_result_t composed_decode(const void* context, const uint8_t* data, size_t size,
                                    tlv_decoded_t* result, tlv_format_error_t* error) {
    const wasm_composition_t* f = context;
    return f->base.decode(f->base.context, data, size, result, error);
}
static tlv_result_t composed_measure(const void* context, const tlv_element_t* element,
                                     tlv_encoding_t* result, tlv_format_error_t* error) {
    const wasm_composition_t* f = context;
    return f->base.measure(f->base.context, element, result, error);
}
static tlv_result_t composed_encode(const void* context, const tlv_element_t* element,
                                    uint8_t* data, size_t size, size_t* used,
                                    tlv_format_error_t* error) {
    const wasm_composition_t* f = context;
    return f->base.encode(f->base.context, element, data, size, used, error);
}
static int composed_constructed(const void* context, const tlv_tag_t* tag) {
    return tlv_constructed_bit_predicate(&((const wasm_composition_t*)context)->constructed, tag);
}
static void composed_free(void* context) {
    wasm_composition_t* f = context;
    if (!f)
        return;
    opentlv_wasm_field_free(f->identifier);
    opentlv_wasm_field_free(f->length);
    for (size_t i = 0; i < f->count; ++i)
        free((void*)f->tags[i].data);
    free(f->tags);
    free(f->storage);
    free(f);
}
/* kind: 0 mixed, 1 variable, 2 escaped, 3 packed. Options: order, scope,
 * predicate present/index/mask/value, packed header/tag-size. */
OPENTLV_WASM_API opentlv_wasm_format_t*
opentlv_wasm_composed_new(int kind, wasm_field_t* identifier, wasm_field_t* length,
                          const uint32_t* options, const uint8_t* storage, size_t storage_size,
                          const uint32_t* tags, const uint32_t* sizes, size_t count, int* result) {
    *result = TLV_ERR_INVALID_ARG;
    if (!identifier || !length || kind < 0 || kind > 3)
        return NULL;
    if ((kind == 0 && (identifier->kind > FIELD_VARIABLE_TAG || length->kind < FIELD_FIXED_LENGTH ||
                       length->kind > FIELD_ESCAPED_LENGTH)) ||
        (kind == 1 &&
         (identifier->kind != FIELD_VARIABLE_TAG || length->kind != FIELD_VARIABLE_LENGTH)) ||
        (kind == 2 &&
         (identifier->kind != FIELD_FIXED_TAG || length->kind != FIELD_ESCAPED_LENGTH)) ||
        (kind == 3 && (identifier->kind != FIELD_PACKED || length->kind != FIELD_PACKED)))
        return NULL;
    *result = TLV_ERR_OUT_OF_MEMORY;
    opentlv_wasm_format_t* owner = opentlv_wasm_format_new("custom", 0, 0, 0, 0, 0);
    if (!owner)
        return NULL;
    wasm_composition_t* f = calloc(1, sizeof *f);
    if (!f) {
        opentlv_wasm_format_free(owner);
        return NULL;
    }
    owner->extension = f;
    owner->extension_free = composed_free;
    f->identifier = identifier;
    ++identifier->references;
    f->length = length;
    ++length->references;
    f->constructed = (tlv_constructed_bit_t){options[3], (uint8_t)options[4], (uint8_t)options[5]};
    if (count > SIZE_MAX / sizeof *f->tags)
        goto fail;
    if (count) {
        f->tags = calloc(count, sizeof *f->tags);
        if (!f->tags)
            goto fail;
        f->count = count;
        for (size_t i = 0; i < count; ++i) {
            uint8_t* copy = malloc(sizes[i] ? sizes[i] : 1);
            if (!copy)
                goto fail;
            if (sizes[i])
                memcpy(copy, (const void*)(uintptr_t)tags[i], sizes[i]);
            f->tags[i] = tlv_tag(copy, sizes[i]);
        }
    }
    f->tagged.fields = (tlv_field_composition_t){f,
                                                 composed_read_tag,
                                                 composed_read_length,
                                                 NULL,
                                                 composed_write_tag,
                                                 composed_write_length,
                                                 (tlv_element_order_t)options[0],
                                                 (tlv_length_scope_t)options[1]};
    f->tagged.tag_only = f->tags;
    f->tagged.count = count;
    tlv_result_t rc;
    if (kind == 1) {
        f->variable = (tlv_variable_format_t){
            identifier->variable_tag, length->variable_length, f->tagged.fields.element_order,
            f->tagged.fields.length_scope, options[2] ? &f->constructed : NULL};
        rc = count ? TLV_ERR_INVALID_ARG : tlv_variable_format_init(&f->base, &f->variable);
    } else if (kind == 2) {
        f->escaped = (tlv_escaped_format_t){
            identifier->fixed_tag,         length->escaped, f->tagged.fields.element_order,
            f->tagged.fields.length_scope, f->tags,         count};
        rc = tlv_escaped_format_init(&f->base, &f->escaped);
    } else if (kind == 3) {
        f->storage = malloc(storage_size ? storage_size : 1);
        if (!f->storage)
            goto fail;
        if (storage_size)
            memcpy(f->storage, storage, storage_size);
        f->packed = (tlv_packed_layout_t){
            options[6], identifier->packed, length->packed, f->tagged.fields.length_scope,
            f->storage, options[7],         storage_size};
        rc = count || options[0] ? TLV_ERR_INVALID_ARG : tlv_packed_layout_validate(&f->packed);
        if (rc == TLV_OK)
            rc = tlv_format_init(&f->base, &f->packed, tlv_packed_decode, tlv_packed_measure,
                                 tlv_packed_encode);
    } else
        rc = count ? tlv_tagged_fields_format_init(&f->base, &f->tagged)
                   : tlv_fields_format_init(&f->base, &f->tagged.fields);
    if (rc == TLV_OK && options[2]) {
        /* Let Core validate the bit predicate even for non-variable layouts. */
        tlv_variable_format_t probe = {{0x1f, 0x1f, 0x80, 0x7f, 8, NULL},
                                       {0x80, 0x7f, TLV_BYTE_ORDER_BIG_ENDIAN, NULL},
                                       TLV_ELEMENT_ORDER_TLV,
                                       TLV_LENGTH_SCOPE_VALUE,
                                       &f->constructed};
        tlv_field_composition_t fields;
        rc = tlv_variable_fields_init(&fields, &probe);
    }
    if (rc == TLV_OK)
        rc = tlv_format_init(&owner->format, f, composed_decode, composed_measure, composed_encode);
    if (rc == TLV_OK && options[2])
        owner->format.is_constructed = composed_constructed;
    *result = rc;
    if (rc == TLV_OK)
        return owner;
fail:
    opentlv_wasm_format_free(owner);
    return NULL;
}

static void field_range(builder_t* b, const tlv_range_t* r) {
    if (!r->present) {
        builder_text(b, "null");
        return;
    }
    builder_text(b, "{\"offset\":");
    builder_number(b, r->offset);
    builder_text(b, ",\"size\":");
    builder_number(b, r->size);
    builder_text(b, "}");
}
/* operation: capabilities, decode, measure, encode, preserve. Values crossing
 * wasm32 remain uint64 low/high pairs; logical sizes in JSON are decimal strings. */
OPENTLV_WASM_API char* opentlv_wasm_format_operation(opentlv_wasm_format_t* owner, int operation,
                                                     const uint8_t* input, size_t input_size,
                                                     const uint8_t* tag, size_t tag_size,
                                                     const uint8_t* value, uint32_t low,
                                                     uint32_t high) {
    builder_t b = {0};
    builder_text(&b, "{\"value\":");
    tlv_result_t rc = TLV_OK;
    tlv_format_error_t error = {0};
    tlv_decoded_t decoded;
    tlv_encoding_t encoding;
    tlv_element_t element = {tlv_tag(tag, tag_size), {value, ((uint64_t)high << 32) | low}};
    uint8_t* output = NULL;
    size_t written = 0;
    if (operation == 0) {
        builder_text(&b, tlv_format_can_read(&owner->format) ? "{\"canRead\":true"
                                                             : "{\"canRead\":false");
        builder_text(&b, tlv_format_can_write(&owner->format) ? ",\"canWrite\":true}"
                                                              : ",\"canWrite\":false}");
    } else if (operation == 1) {
        rc = tlv_format_decode(&owner->format, input, input_size, &decoded, &error);
        if (rc == TLV_OK) {
            builder_text(&b, "{\"tag\":");
            if (decoded.element.tag.data) {
                builder_text(&b, "\"");
                builder_hex(&b, decoded.element.tag.data, decoded.element.tag.size);
                builder_text(&b, "\"");
            } else
                builder_text(&b, "null");
            builder_text(&b, ",\"value\":\"");
            builder_hex(&b, decoded.element.value.data, (size_t)decoded.element.value.size);
            builder_text(&b, "\",\"encodedSize\":");
            builder_number(&b, decoded.source.size);
            builder_text(&b, ",\"constructed\":");
            builder_text(&b, owner->format.is_constructed &&
                                     owner->format.is_constructed(owner->format.context,
                                                                  &decoded.element.tag)
                                 ? "true"
                                 : "false");
            builder_text(&b, ",\"source\":{\"header\":");
            field_range(&b, &decoded.source.header);
            builder_text(&b, ",\"tag\":");
            field_range(&b, &decoded.source.tag);
            builder_text(&b, ",\"length\":");
            field_range(&b, &decoded.source.length);
            builder_text(&b, ",\"value\":");
            field_range(&b, &decoded.source.value);
            builder_text(&b, ",\"trailer\":");
            field_range(&b, &decoded.source.trailer);
            builder_text(&b, "}}");
        } else
            builder_text(&b, "null");
    } else if (operation == 2) {
        rc = tlv_format_measure(&owner->format, &element, &encoding, &error);
        if (rc == TLV_OK) {
            builder_text(&b, "{\"header\":");
            field_number(&b, encoding.header);
            builder_text(&b, ",\"value\":");
            field_number(&b, encoding.value);
            builder_text(&b, ",\"trailer\":");
            field_number(&b, encoding.trailer);
            builder_text(&b, ",\"total\":");
            field_number(&b, encoding.total);
            builder_text(&b, "}");
        } else
            builder_text(&b, "null");
    } else {
        if (operation == 4) {
            rc = tlv_format_decode(&owner->format, input, input_size, &decoded, &error);
            if (rc == TLV_OK)
                rc = tlv_source_preserve(&decoded.source, &element, NULL, 0, &written);
        } else {
            rc = tlv_format_measure(&owner->format, &element, &encoding, &error);
            if (rc == TLV_OK)
                rc = tlv_size_to_native(encoding.total, &written);
        }
        if (rc == TLV_OK) {
            output = malloc(written ? written : 1);
            rc = output ? (operation == 4 ? tlv_source_preserve(&decoded.source, &element, output,
                                                                written, &written)
                                          : tlv_format_encode(&owner->format, &element, output,
                                                              written, &written, &error))
                        : TLV_ERR_OUT_OF_MEMORY;
        }
        builder_text(&b, "\"");
        if (rc == TLV_OK)
            builder_hex(&b, output, written);
        builder_text(&b, "\"");
    }
    free(output);
    if (rc != TLV_OK) {
        builder_text(&b, ",\"format\":{\"region\":");
        builder_number(&b, error.region);
        builder_text(&b, ",\"offset\":");
        if (error.has_offset)
            builder_number(&b, error.offset);
        else
            builder_text(&b, "null");
        builder_text(&b, ",\"required\":");
        if (error.has_required)
            field_number(&b, error.required);
        else
            builder_text(&b, "null");
        builder_text(&b, ",\"tag\":");
        field_range(&b, &error.tag);
        builder_text(&b, ",\"length\":");
        field_range(&b, &error.length);
        builder_text(&b, ",\"value\":");
        field_range(&b, &error.value);
        builder_text(&b, "}");
    }
    return field_reply(&b, rc);
}
