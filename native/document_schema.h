// SPDX-License-Identifier: MIT
// Copyright (c) 2026 OpenTLV
/* Owning wasm32 adaptation. Tree, Query and Schema semantics remain in Core. */
#include <tlv/schema/schema.h>

static void ds_node(builder_t* b, const tlv_node_t* node) {
    if (!node) { builder_text(b, "null"); return; }
    builder_text(b, "{\"node\":"); builder_number(b, (uintptr_t)node);
    builder_text(b, ",\"identity\":"); query_integer(b, (int64_t)tlv_node_identity(node));
    builder_text(b, "}");
}
static tlv_result_t ds_live(opentlv_wasm_document_t* doc, tlv_node_t* node, const char* id) {
    if (!node) return TLV_OK;
    uint64_t actual = tlv_document_node_identity(doc->document, node);
    return actual && id && actual == strtoull(id, NULL, 10) ? TLV_OK : TLV_ERR_INVALID_ARG;
}
OPENTLV_WASM_API opentlv_wasm_document_t* opentlv_wasm_document_create(
    opentlv_wasm_program_t* p, const uint8_t* input, size_t length, const uint32_t* config) {
    opentlv_wasm_document_t* doc = calloc(1, sizeof *doc);
    tlv_result_t rc = doc ? TLV_OK : TLV_ERR_OUT_OF_MEMORY;
    tlv_reader_diagnostic_t d; tlv_reader_diagnostic_init(&d);
    if (doc) {
        doc->references = 1; doc->program = p; ++p->references;
        tlv_document_options_t options;
        rc = tlv_document_options_init(&options, p->environment.format);
        options.max_depth = config[0]; options.max_elements = config[1];
        options.retain_source_locations = (int)config[2];
        if (rc == TLV_OK) rc = config[3] ? tlv_document_create(&options, &doc->document)
            : tlv_document_parse(input, length, &options, &doc->document, &d);
    }
    query_status(&p->reply, rc, NULL);
    if (rc != TLV_OK) stream_reader_detail(&p->reply, &d);
    query_reply(&p->reply);
    if (rc != TLV_OK) { opentlv_wasm_document_free(doc); return NULL; }
    return doc;
}
/* config: operation, node, other node; identities travel as decimal strings. */
OPENTLV_WASM_API char* opentlv_wasm_document_operation(opentlv_wasm_document_t* doc,
    const uint32_t* config, const char* id, const char* other_id, const uint8_t* tag,
    size_t tag_size, const uint8_t* value, size_t value_size, opentlv_wasm_program_t* format) {
    builder_t b = {0}; builder_text(&b, "{");
    tlv_node_t* node = (tlv_node_t*)(uintptr_t)config[1];
    tlv_node_t* other = (tlv_node_t*)(uintptr_t)config[2];
    tlv_result_t rc = ds_live(doc, node, id);
    if (rc == TLV_OK) rc = ds_live(doc, other, other_id);
    size_t length = 0; uint8_t* output = NULL;
    const tlv_format_t* f = format ? format->environment.format : doc->program->environment.format;
    if (rc == TLV_OK) switch (config[0]) {
        case 0:
            builder_text(&b, "\"count\":"); builder_number(&b, tlv_document_count(doc->document));
            builder_text(&b, ",\"revision\":"); query_integer(&b, (int64_t)tlv_document_revision(doc->document));
            builder_text(&b, ",\"retireEpoch\":"); query_integer(&b, (int64_t)tlv_document_retire_epoch(doc->document));
            break;
        case 1: rc = tlv_document_insert(doc->document, node, other, tlv_tag(tag, tag_size), value, value_size, &node); break;
        case 2: node = tlv_document_find(doc->document, node, tlv_tag(tag, tag_size)); break;
        case 3: node = tlv_node_next_same_tag(node); break;
        case 4: {
            tlv_query_t query;
            rc = tlv_query_parse_n((const char*)value, value_size, &query, NULL);
            if (rc == TLV_OK) rc = tlv_document_find_path(doc->document, &query, &node);
            if (rc == TLV_END) { rc = TLV_OK; node = NULL; }
            break;
        }
        case 5: {
            tlv_document_source_location_t loc = tlv_node_source_location(node);
            builder_text(&b, "\"location\":{");
            builder_text(&b, "\"offset\":");
            if (loc.has_offset) builder_number(&b, loc.offset); else builder_text(&b, "null");
            builder_text(&b, ",\"headerSize\":");
            if (loc.has_header_size) builder_number(&b, loc.header_size); else builder_text(&b, "null");
            builder_text(&b, "}"); break;
        }
        case 6: case 7:
            rc = node ? tlv_node_encoded_size_as(node, f, &length)
                      : tlv_document_encoded_size_as(doc->document, f, &length);
            if (rc == TLV_OK && config[0] == 7) {
                output = malloc(length ? length : 1);
                if (!output) rc = TLV_ERR_OUT_OF_MEMORY;
                else rc = node ? tlv_node_encode_as(node, f, output, length, &length)
                               : tlv_document_encode_as(doc->document, f, output, length, &length);
            }
            builder_text(&b, "\"size\":"); builder_number(&b, length);
            builder_text(&b, ",\"bytes\":\"");
            if (rc == TLV_OK && output) builder_hex(&b, output, length);
            builder_text(&b, "\""); break;
        default: rc = TLV_ERR_INVALID_ARG;
    }
    if (config[0] >= 1 && config[0] <= 4) { builder_text(&b, "\"node\":"); ds_node(&b, rc == TLV_OK ? node : NULL); }
    if (b.size == 1) builder_text(&b, "\"value\":null");
    free(output);
    return field_reply(&b, rc);
}
/* Discover the canonical encoded snapshot required for constructed Query values. */
OPENTLV_WASM_API char* opentlv_wasm_document_query_size(opentlv_wasm_document_t* doc, size_t depth) {
    builder_t b = {0}; builder_text(&b, "{\"size\":");
    tlv_tree_writer_workspace_t staging = {0}; size_t capacity = 0, bytes = 0;
    tlv_query_diagnostic_t d = {0};
    tlv_result_t rc = tlv_document_encoded_size(doc->document, &capacity);
    if (depth == SIZE_MAX || depth + 1 > SIZE_MAX / sizeof *staging.frames) rc = TLV_ERR_OVERFLOW;
    if (rc == TLV_OK) {
        staging.frames = calloc(depth + 1, sizeof *staging.frames); staging.frame_capacity = depth + 1;
        staging.data = malloc(capacity ? capacity : 1); staging.data_capacity = capacity;
        staging.scratch = malloc(capacity ? capacity : 1); staging.scratch_capacity = capacity;
        if (!staging.frames || !staging.data || !staging.scratch) rc = TLV_ERR_OUT_OF_MEMORY;
        else rc = tlv_document_query_value_size(doc->document, &staging, &bytes, &d);
    }
    builder_number(&b, bytes); free(staging.frames); free(staging.data); free(staging.scratch);
    return field_reply(&b, rc);
}

typedef struct wasm_document_builder {
    tlv_document_builder_t* builder;
    opentlv_wasm_program_t* program;
} wasm_document_builder_t;
OPENTLV_WASM_API wasm_document_builder_t* opentlv_wasm_document_builder_new(
    opentlv_wasm_program_t* program, wasm_stream_t* stream, const uint32_t* config, int* result) {
    wasm_document_builder_t* b = calloc(1, sizeof *b);
    *result = TLV_ERR_OUT_OF_MEMORY;
    if (!b) return NULL;
    tlv_document_options_t options;
    *result = tlv_document_options_init(&options, program->environment.format);
    options.max_depth = config[0]; options.max_elements = config[1]; options.retain_source_locations = (int)config[2];
    if (*result == TLV_OK) *result = tlv_document_builder_create(&options, &stream->tree_reader, NULL, &b->builder);
    if (*result != TLV_OK) { free(b); return NULL; }
    b->program = program; ++program->references; return b;
}
OPENTLV_WASM_API void opentlv_wasm_document_builder_free(wasm_document_builder_t* b) {
    if (!b) return;
    tlv_document_builder_free(b->builder); opentlv_wasm_program_free(b->program); free(b);
}
OPENTLV_WASM_API char* opentlv_wasm_document_builder_consume(wasm_document_builder_t* b) {
    builder_t reply = {0}; builder_text(&reply, "{\"document\":");
    /* Allocate the wrapper before transferring the tree, so OOM cannot lose it. */
    opentlv_wasm_document_t* doc = calloc(1, sizeof *doc);
    tlv_reader_diagnostic_t d; tlv_reader_diagnostic_init(&d);
    tlv_result_t rc = doc ? tlv_document_builder_consume(b->builder, &doc->document, &d) : TLV_ERR_OUT_OF_MEMORY;
    if (rc == TLV_OK) { doc->program = b->program; ++b->program->references; doc->references = 1; }
    else { free(doc); doc = NULL; }
    builder_number(&reply, (uintptr_t)doc);
    if (rc != TLV_OK) stream_reader_detail(&reply, &d);
    char* result = field_reply(&reply, rc);
    if (!result) opentlv_wasm_document_free(doc);
    return result;
}

typedef struct wasm_schema {
    tlv_structure_schema_t* tables;
    tlv_structure_rule_t* rules;
    tlv_schema_entry_t* entries;
    tlv_structure_group_t* groups;
    size_t rule_count, group_count;
    tlv_schema_checked_t checked;
} wasm_schema_t;
OPENTLV_WASM_API void opentlv_wasm_structure_free(wasm_schema_t* s) {
    if (!s) return;
    for (size_t i = 0; s->entries && i < s->rule_count; ++i) {
        free((void*)s->entries[i].tag.data); free((void*)s->entries[i].name);
    }
    for (size_t i = 0; s->groups && i < s->group_count; ++i) free((void*)s->groups[i].name);
    free(s->tables); free(s->rules); free(s->entries); free(s->groups); free(s);
}
static void ds_schema_detail(builder_t* b, const tlv_schema_diagnostic_t* d) {
    builder_text(b, "{\"code\":"); builder_number(b, d->diagnostic.code);
    builder_text(b, ",\"cause\":"); builder_json_string(b, tlv_schema_cause_string(d->cause));
    builder_text(b, ",\"diagnostic\":{"); query_common_diagnostic(b, &d->diagnostic);
    write_location(b, &d->diagnostic.location); builder_text(b, "}");
    if (d->cause == TLV_SCHEMA_CAUSE_READER) query_reader_diagnostic(b, &d->detail.reader);
    if (d->cause == TLV_SCHEMA_CAUSE_SCHEMA) {
        const tlv_schema_detail_t* detail = &d->detail.schema;
        builder_text(b, ",\"schema\":{\"kind_name\":");
        builder_json_string(b, tlv_schema_issue_kind_string(detail->kind));
        builder_text(b, ",\"tag\":\""); builder_hex(b, detail->tag.data, detail->tag.size);
        builder_text(b, "\",\"field\":"); builder_json_string(b, detail->field ? detail->field : "");
        builder_text(b, ",\"definition_kind\":");
        builder_json_string(b, tlv_schema_definition_kind_string(detail->definition.kind));
        query_field(b, "definition_index", detail->definition.index);
#define DS_DETAIL(name) query_field(b, #name, detail->name)
        DS_DETAIL(kind); DS_DETAIL(is_group); DS_DETAIL(has_occurs); DS_DETAIL(min_occurs);
        DS_DETAIL(max_occurs); DS_DETAIL(occurs); DS_DETAIL(has_length); DS_DETAIL(min_length);
        DS_DETAIL(max_length); DS_DETAIL(actual_length); DS_DETAIL(has_form); DS_DETAIL(expected_form);
        DS_DETAIL(actual_constructed); DS_DETAIL(length_multiple); DS_DETAIL(length_flags);
#undef DS_DETAIL
        builder_text(b, "}");
    }
    builder_text(b, "}");
}
/* Tables: first rule/count, first group/count, allow_unknown, order.
 * Rules: tag pointer/length, name pointer, min/max length, flags, multiple,
 * min/max occurs, kind, children table index + 1, group id. Groups: id,min,max,name. */
OPENTLV_WASM_API char* opentlv_wasm_structure_new(const uint32_t* tables, size_t count,
    const uint32_t* rules, size_t rule_count, const uint32_t* groups, size_t group_count) {
    builder_t b = {0}; builder_text(&b, "{\"schema\":");
    wasm_schema_t* s = calloc(1, sizeof *s);
    tlv_result_t rc = s ? TLV_OK : TLV_ERR_OUT_OF_MEMORY;
    tlv_schema_diagnostic_t d; tlv_schema_diagnostic_init(&d);
    if (s) {
        s->rule_count = rule_count; s->group_count = group_count;
        s->tables = calloc(count ? count : 1, sizeof *s->tables);
        s->rules = calloc(rule_count ? rule_count : 1, sizeof *s->rules);
        s->entries = calloc(rule_count ? rule_count : 1, sizeof *s->entries);
        s->groups = calloc(group_count ? group_count : 1, sizeof *s->groups);
        if (!s->tables || !s->rules || !s->entries || !s->groups) rc = TLV_ERR_OUT_OF_MEMORY;
    }
    for (size_t i = 0; rc == TLV_OK && i < count; ++i) {
        const uint32_t* p = tables + 6 * i;
        if (p[0] > rule_count || p[1] > rule_count - p[0] || p[2] > group_count || p[3] > group_count - p[2]) { rc = TLV_ERR_INVALID_ARG; break; }
        s->tables[i] = (tlv_structure_schema_t){s->rules + p[0], p[1], (int)p[4], s->groups + p[2], p[3], (tlv_schema_order_t)p[5]};
    }
    for (size_t i = 0; rc == TLV_OK && i < rule_count; ++i) {
        const uint32_t* p = rules + 12 * i;
        if (p[10] > count) { rc = TLV_ERR_INVALID_ARG; break; }
        uint8_t* tag = stream_copy((const uint8_t*)(uintptr_t)p[0], p[1]);
        char* name = query_copy_name((const char*)(uintptr_t)p[2]);
        s->entries[i] = (tlv_schema_entry_t){tlv_tag(tag, p[1]), p[3], p[4], p[5], name, p[6]};
        s->rules[i] = (tlv_structure_rule_t){s->entries + i, p[7], p[8], (tlv_schema_kind_t)p[9], p[10] ? s->tables + p[10] - 1 : NULL, p[11]};
        if (!tag || !name) rc = TLV_ERR_OUT_OF_MEMORY;
    }
    for (size_t i = 0; rc == TLV_OK && i < group_count; ++i) {
        const uint32_t* p = groups + 4 * i;
        s->groups[i] = (tlv_structure_group_t){p[0], p[1], p[2], query_copy_name((const char*)(uintptr_t)p[3])};
        if (!s->groups[i].name) rc = TLV_ERR_OUT_OF_MEMORY;
    }
    if (rc == TLV_OK) rc = count ? tlv_schema_prepare(&s->checked, s->tables, &d) : TLV_ERR_INVALID_ARG;
    if (rc != TLV_OK) { opentlv_wasm_structure_free(s); s = NULL; }
    builder_number(&b, (uintptr_t)s); builder_text(&b, ",\"detail\":"); ds_schema_detail(&b, &d);
    char* result = field_reply(&b, rc);
    if (!result) opentlv_wasm_structure_free(s);
    return result;
}
OPENTLV_WASM_API char* opentlv_wasm_structure_validate(wasm_schema_t* s,
    opentlv_wasm_program_t* owner, const uint8_t* data, size_t length, const uint32_t* p) {
    builder_t b = {0}; builder_text(&b, "{\"diagnostics\":[");
    tlv_schema_diagnostic_t d; tlv_schema_diagnostic_init(&d);
    tlv_schema_diagnostic_report_t report = {0};
    tlv_result_t rc = TLV_OK;
    if (p[2]) {
        report.diagnostics = calloc(p[3] ? p[3] : 1, sizeof *report.diagnostics); report.capacity = p[3];
        if (!report.diagnostics) rc = TLV_ERR_OUT_OF_MEMORY;
        else rc = tlv_schema_validate_all_checked(&s->checked, data, length, owner->environment.format,
            p[0], p[1], (tlv_schema_unknown_policy_t)p[4], &report, &d);
    } else rc = tlv_schema_validate_checked(&s->checked, data, length, owner->environment.format, p[0], p[1], &d);
    for (size_t i = 0; i < report.count; ++i) { if (i) builder_text(&b, ","); ds_schema_detail(&b, report.diagnostics + i); }
    builder_text(&b, "],\"detail\":"); ds_schema_detail(&b, &d); free(report.diagnostics);
    return field_reply(&b, rc);
}
OPENTLV_WASM_API char* opentlv_wasm_structure_find(wasm_schema_t* s, size_t table,
    const uint8_t* tag, size_t length, size_t value_length, int validate) {
    builder_t b = {0}; builder_text(&b, "{\"index\":");
    tlv_tag_t key = tlv_tag(tag, length);
    tlv_schema_t schema = {NULL, 0};
    /* Entries for each table are contiguous in the owned flat entry storage. */
    const tlv_structure_schema_t* t = s->tables + table;
    if (t->count) { schema.entries = t->rules[0].entry; schema.count = t->count; }
    const tlv_schema_entry_t* entry = tlv_schema_find(&schema, &key);
    if (entry) builder_number(&b, (size_t)(entry - s->entries)); else builder_text(&b, "null");
    return field_reply(&b, validate ? (entry ? tlv_schema_validate_length(entry, value_length) : TLV_ERR_INVALID_TAG) : TLV_OK);
}

OPENTLV_WASM_API const char* opentlv_wasm_execution_document_context(opentlv_wasm_execution_t* q,
    opentlv_wasm_document_t* doc, size_t capacity, tlv_node_t* context, const char* identity) {
    tlv_result_t rc = ds_live(doc, context, identity);
    if (rc != TLV_OK) { query_status(&q->reply, rc, NULL); return query_reply(&q->reply); }
    return wasm_execution_document_context(q, doc, capacity, context);
}
