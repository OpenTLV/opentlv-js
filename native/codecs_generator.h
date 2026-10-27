// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel
/* Representation transfer only: all conversions and wire generation are Core-owned. */
#include <tlv/codec/values.h>
#include <tlv/codec/ipv4.h>
#include <tlv/codec/number.h>
#include <tlv/codec/digits.h>
#include <tlv/codec/text.h>
#include <tlv/codec/structure.h>
#include <tlv/schema/number.h>
#include <tlv/generator.h>

static char* cg_reply(builder_t* b, tlv_result_t rc, const tlv_codec_diagnostic_t* d) {
    builder_text(b, ",\"diagnostic\":{"); query_common_diagnostic(b, &d->diagnostic);
    write_location(b, &d->diagnostic.location); builder_text(b, "}");
    query_codec_diagnostic(b, &d->codec);
    return field_reply(b, rc);
}
/* kind, representation, width, digits, padding, min/max length, flags, multiple.
 * operation: decode, encode, measure, IPv4 list lookup. No pointers survive a call. */
OPENTLV_WASM_API char* opentlv_wasm_codec(const uint32_t* p, int operation,
    const uint8_t* input, size_t length, size_t capacity, size_t index) {
    tlv_number_codec_config_t number = {(tlv_number_encoding_t)p[1], p[2], p[3]};
    tlv_digits_codec_config_t digits = {p[2]};
    tlv_text_codec_config_t text = {(tlv_text_alphabet_t)p[1], p[2], (int)p[4]};
    tlv_schema_entry_t entry = {0};
    entry.min_length = p[5]; entry.max_length = p[6]; entry.flags = p[7]; entry.length_multiple = p[8];
    tlv_schema_number_t schema_number = {&entry, number};
    const tlv_codec_t* builtin[] = {&tlv_codec_uint8, &tlv_codec_uint16_be, &tlv_codec_uint16_le,
        &tlv_codec_uint32_be, &tlv_codec_uint32_le, &tlv_codec_int64_minimal_be,
        &tlv_codec_bytes, &tlv_codec_ipv4, &tlv_codec_ipv4_list};
    tlv_codec_t codec = {0};
    if (p[0] < 9) codec = *builtin[p[0]];
    else if (p[0] == 9) codec = (tlv_codec_t){&number, tlv_number_decode, tlv_number_encode};
    else if (p[0] == 10) codec = (tlv_codec_t){&digits, tlv_digits_decode, tlv_digits_encode};
    else if (p[0] == 11) codec = (tlv_codec_t){&text, tlv_text_decode, tlv_text_encode};
    else if (p[0] == 12) codec = (tlv_codec_t){&schema_number, tlv_schema_number_decode, tlv_schema_number_encode};
    tlv_codec_diagnostic_t d;
    tlv_codec_diagnostic_init(&d, operation == 0 || operation == 3 ? TLV_CODEC_OP_DECODE
        : operation == 2 ? TLV_CODEC_OP_MEASURE : TLV_CODEC_OP_ENCODE);
    union { uint8_t u8; uint16_t u16; uint32_t u32; uint64_t u64; int64_t i64;
        tlv_value_t span; tlv_ipv4_t ip; tlv_ipv4_list_t list; } value = {0};
    void* object = &value; size_t object_size = sizeof value;
    uint8_t* storage = NULL; uint8_t* output = NULL; size_t written = 0;
    tlv_result_t rc = TLV_OK;
    builder_t b = {0}; builder_text(&b, "{\"value\":");
    if (operation == 0 || operation == 3) {
        if (p[0] == 10) {
            if (length > (SIZE_MAX - 1) / 2) rc = TLV_ERR_OVERFLOW;
            else { object_size = length * 2 + 1; storage = malloc(object_size); object = storage;
                if (!storage) rc = TLV_ERR_OUT_OF_MEMORY; }
        }
        if (rc == TLV_OK) rc = tlv_codec_decode(&codec, input, length, object, object_size, &d);
        if (rc == TLV_OK && operation == 3) {
            tlv_ipv4_t address;
            rc = p[0] == 8 ? tlv_ipv4_list_at(&value.list, index, &address) : TLV_ERR_INVALID_ARG;
            if (rc == TLV_OK) { builder_text(&b, "\""); builder_hex(&b, address.bytes, 4); builder_text(&b, "\""); }
        } else if (rc == TLV_OK) {
            if (p[0] == 0) builder_number(&b, value.u8);
            else if (p[0] <= 2) builder_number(&b, value.u16);
            else if (p[0] <= 4) builder_number(&b, value.u32);
            else if (p[0] == 5) query_integer(&b, value.i64);
            else if (p[0] == 9 || p[0] == 12) query_unsigned(&b, value.u64);
            else if (p[0] == 10) builder_json_string(&b, (const char*)storage);
            else {
                const uint8_t* data = p[0] == 7 ? value.ip.bytes : p[0] == 8 ? value.list.raw.data : value.span.data;
                size_t size = p[0] == 7 ? 4 : (size_t)(p[0] == 8 ? value.list.raw.size : value.span.size);
                builder_text(&b, "\""); builder_hex(&b, data, size); builder_text(&b, "\"");
            }
        }
        if (rc != TLV_OK) builder_text(&b, "null");
    } else {
        if (p[0] <= 5 || p[0] == 9 || p[0] == 12) {
            object_size = p[0] == 0 ? 1 : p[0] <= 2 ? 2 : p[0] <= 4 ? 4 : 8;
            if (length != object_size) rc = TLV_ERR_INVALID_VALUE;
            else memcpy(&value, input, object_size);
        } else if (p[0] == 7) {
            object_size = sizeof value.ip;
            if (length != 4) rc = TLV_ERR_INVALID_VALUE;
            else memcpy(value.ip.bytes, input, 4);
        } else if (p[0] == 10) { object = (void*)input; object_size = length; }
        else if (p[0] == 8) { value.list.raw = (tlv_value_t){input, length}; object_size = sizeof value.list; }
        else { value.span = (tlv_value_t){input, length}; object_size = sizeof value.span; }
        if (rc == TLV_OK) rc = tlv_codec_encode(&codec, object, object_size, NULL, 0, &written, &d);
        if (rc == TLV_OK && operation == 1) {
            size_t available = capacity == SIZE_MAX ? written : capacity;
            /* Allocate only what may be written, while preserving Core capacity errors. */
            size_t allocation = available < written ? available : written;
            output = malloc(allocation ? allocation : 1);
            if (!output) rc = TLV_ERR_OUT_OF_MEMORY;
            else rc = tlv_codec_encode(&codec, object, object_size, output, available, &written, &d);
        }
        builder_text(&b, "\"");
        if (rc == TLV_OK && output) builder_hex(&b, output, written);
        builder_text(&b, "\",\"size\":"); builder_number(&b, rc == TLV_OK ? written : 0);
    }
    if (d.diagnostic.code != rc) tlv_codec_diagnostic_result(&d, rc);
    char* reply = cg_reply(&b, rc, &d); free(storage); free(output); return reply;
}

/* JS object adapters marshal to an owned byte span. Core validates framing,
 * nesting, Schema and limits around these byte-copy callbacks. */
static tlv_result_t cg_decode(const void* context, const tlv_format_t* format,
    const uint8_t* data, size_t length, void* value, size_t capacity, tlv_codec_diagnostic_t* d) {
    (void)context; (void)format;
    return tlv_codec_decode(&tlv_codec_bytes, data, length, value, capacity, d);
}
static tlv_result_t cg_encode(const void* context, const tlv_format_t* format,
    const void* value, size_t length, uint8_t* data, size_t capacity, size_t* written, tlv_codec_diagnostic_t* d) {
    (void)context; (void)format;
    return tlv_codec_encode(&tlv_codec_bytes, value, length, data, capacity, written, d);
}
OPENTLV_WASM_API char* opentlv_wasm_structure_codec(opentlv_wasm_program_t* owner,
    wasm_schema_t* schema, const uint32_t* p, const uint8_t* input, size_t length) {
    tlv_structure_codec_t codec = {NULL, owner->environment.format, schema ? schema->tables : NULL,
        p[1], p[2], cg_decode, cg_encode};
    tlv_codec_diagnostic_t d; tlv_codec_diagnostic_init(&d, p[0] ? TLV_CODEC_OP_ENCODE : TLV_CODEC_OP_DECODE);
    tlv_value_t value = {input, length}; size_t written = 0;
    uint8_t* output = NULL; tlv_result_t rc;
    if (!p[0]) rc = tlv_structure_decode(&codec, input, length, &value, sizeof value, &d);
    else {
        rc = tlv_structure_encode(&codec, &value, sizeof value, NULL, 0, &written, &d);
        if (rc == TLV_OK) {
            size_t capacity = p[3] == UINT32_MAX ? written : p[3];
            size_t allocation = capacity < written ? capacity : written;
            output = malloc(allocation ? allocation : 1);
            if (!output) rc = TLV_ERR_OUT_OF_MEMORY;
            else rc = tlv_structure_encode(&codec, &value, sizeof value, output, capacity, &written, &d);
        }
    }
    builder_t b = {0}; builder_text(&b, "{\"value\":\"");
    if (rc == TLV_OK) builder_hex(&b, p[0] ? output : value.data, p[0] ? written : (size_t)value.size);
    builder_text(&b, "\"");
    if (d.diagnostic.code != rc) tlv_codec_diagnostic_result(&d, rc);
    char* reply = cg_reply(&b, rc, &d); free(output); return reply;
}

OPENTLV_WASM_API char* opentlv_wasm_generate(opentlv_wasm_program_t* owner,
    const uint32_t* p, const uint32_t* entries, size_t count, int measure) {
    tlv_generator_candidate_t* candidates = calloc(count ? count : 1, sizeof *candidates);
    tlv_result_t rc = candidates ? TLV_OK : TLV_ERR_OUT_OF_MEMORY;
    for (size_t i = 0; candidates && i < count; ++i) {
        const uint32_t* c = entries + 4 * i;
        candidates[i] = (tlv_generator_candidate_t){tlv_tag((const uint8_t*)(uintptr_t)c[0], c[1]), c[2], c[3]};
    }
    tlv_generator_options_t options = {(uint64_t)p[0] | ((uint64_t)p[1] << 32),
        (uint64_t)p[2] | ((uint64_t)p[3] << 32), p[4], p[5], p[6], p[7], candidates, count};
    size_t workspace_size = 0, written = 0; uint8_t *workspace = NULL, *output = NULL;
    if (rc == TLV_OK) rc = tlv_generator_workspace_size(&options, &workspace_size);
    if (rc == TLV_OK && !measure) {
        workspace = malloc(workspace_size ? workspace_size : 1); output = malloc(options.max_case_size);
        if (!workspace || !output) rc = TLV_ERR_OUT_OF_MEMORY;
        else rc = tlv_generate(owner->environment.format, &options, output, options.max_case_size,
            workspace, workspace_size, &written);
    }
    builder_t b = {0}; builder_text(&b, "{\"version\":"); builder_number(&b, TLV_GENERATOR_VERSION);
    builder_text(&b, ",\"workspaceSize\":"); builder_number(&b, workspace_size);
    builder_text(&b, ",\"value\":\""); if (rc == TLV_OK && output) builder_hex(&b, output, written);
    builder_text(&b, "\"");
    char* reply = field_reply(&b, rc); free(candidates); free(workspace); free(output); return reply;
}
