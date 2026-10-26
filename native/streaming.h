// SPDX-License-Identifier: MIT
// Copyright (c) 2026 OpenTLV
/* Included once after format_fields.h. Core owns all cursor and tree semantics. */
#include <tlv/reader/visitor.h>

typedef struct wasm_stream {
    opentlv_wasm_format_t* owner;
    int kind; /* reader, tree reader, writer, tree writer */
    uint8_t *data, *scratch, *tags;
    tlv_tree_frame_t* read_frames;
    tlv_tree_writer_frame_t* write_frames;
    tlv_reader_t reader;
    tlv_tree_reader_t tree_reader;
    tlv_writer_t writer;
    tlv_tree_writer_t tree_writer;
} wasm_stream_t;

static uint8_t* stream_copy(const uint8_t* data, size_t size) {
    uint8_t* copy = malloc(size ? size : 1);
    if (copy && size) memcpy(copy, data, size);
    return copy;
}
OPENTLV_WASM_API void opentlv_wasm_stream_free(wasm_stream_t* s) {
    if (!s) return;
    opentlv_wasm_format_free(s->owner);
    free(s->data); free(s->scratch); free(s->tags);
    free(s->read_frames); free(s->write_frames); free(s);
}
/* options: incremental, frame capacity, max depth, max elements, scratch, tags. */
OPENTLV_WASM_API wasm_stream_t* opentlv_wasm_stream_new(opentlv_wasm_format_t* owner,
    int kind, const uint8_t* input, size_t size, const uint32_t* p, int* result) {
    wasm_stream_t* s = calloc(1, sizeof *s);
    *result = TLV_ERR_OUT_OF_MEMORY;
    if (!s) return NULL;
    s->owner = owner; ++owner->references; s->kind = kind;
    s->data = kind < 2 ? stream_copy(input, size) : malloc(size ? size : 1);
    if (!s->data) goto fail;
    tlv_result_t rc = TLV_ERR_INVALID_ARG;
    if (kind == 0) {
        rc = p[0] ? tlv_reader_init_incremental(&s->reader, s->data, size, &owner->format)
                  : tlv_reader_init(&s->reader, s->data, size, &owner->format);
    } else if (kind == 1) {
        s->read_frames = calloc(p[1] ? p[1] : 1, sizeof *s->read_frames);
        if (!s->read_frames) goto fail;
        rc = p[0] ? tlv_tree_reader_init_incremental(&s->tree_reader, s->data, size,
            &owner->format, s->read_frames, p[1], p[2], p[3])
            : tlv_tree_reader_init(&s->tree_reader, s->data, size, &owner->format,
                s->read_frames, p[1], p[2], p[3]);
    } else if (kind == 2) {
        rc = tlv_writer_init(&s->writer, s->data, size, &owner->format);
    } else if (kind == 3) {
        s->write_frames = calloc(p[1] ? p[1] : 1, sizeof *s->write_frames);
        s->scratch = malloc(p[4] ? p[4] : 1); s->tags = malloc(p[5] ? p[5] : 1);
        if (!s->write_frames || !s->scratch || !s->tags) goto fail;
        rc = tlv_tree_writer_init(&s->tree_writer, s->data, size, &owner->format,
            s->write_frames, p[1], s->scratch, p[4], p[2], p[3]);
        if (rc == TLV_OK) rc = tlv_tree_writer_set_tag_storage(&s->tree_writer, s->tags, p[5]);
    }
    *result = rc;
    if (rc == TLV_OK) return s;
fail:
    opentlv_wasm_stream_free(s);
    return NULL;
}
static void stream_element(builder_t* b, const tlv_element_t* e) {
    builder_text(b, "{\"tag\":");
    if (e->tag.data) {
        builder_text(b, "\""); builder_hex(b, e->tag.data, e->tag.size); builder_text(b, "\"");
    } else builder_text(b, "null");
    builder_text(b, ",\"value\":\"");
    if (e->value.size) builder_hex(b, e->value.data, (size_t)e->value.size);
    builder_text(b, "\"}");
}
static void stream_source(builder_t* b, const tlv_source_t* source) {
    builder_text(b, ",\"encoded\":\""); builder_hex(b, source->data, source->size);
    builder_text(b, "\",\"source\":{");
#define STREAM_RANGE(n) builder_text(b, "\"" #n "\":"); field_range(b, &source->n)
    STREAM_RANGE(header); builder_text(b, ","); STREAM_RANGE(tag); builder_text(b, ",");
    STREAM_RANGE(length); builder_text(b, ","); STREAM_RANGE(value); builder_text(b, ",");
    STREAM_RANGE(trailer);
#undef STREAM_RANGE
    builder_text(b, "}");
}
static void stream_reader_detail(builder_t* b, const tlv_reader_diagnostic_t* d) {
    builder_text(b, ",\"diagnostic\":{"); query_common_diagnostic(b, &d->diagnostic);
    write_location(b, &d->diagnostic.location);
    builder_text(b, "}"); query_reader_diagnostic(b, &d->detail);
}
static void stream_writer_detail(builder_t* b, const tlv_writer_diagnostic_t* d) {
    builder_text(b, ",\"diagnostic\":{"); query_common_diagnostic(b, &d->diagnostic);
    write_location(b, &d->diagnostic.location);
    builder_text(b, "},\"writer\":{\"operation\":");
    builder_json_string(b, tlv_writer_operation_string(d->operation));
    if (d->has_tag) {
        builder_text(b, ",\"tag\":\""); builder_hex(b, d->tag.data, d->tag.size); builder_text(b, "\"");
    }
#define STREAM_WRITER_FIELD(n) if (d->has_##n) { builder_text(b, ",\"" #n "\":"); builder_number(b, d->n); }
    STREAM_WRITER_FIELD(length); STREAM_WRITER_FIELD(required); STREAM_WRITER_FIELD(available);
#undef STREAM_WRITER_FIELD
    builder_text(b, "}");
}
/* operation: node pull, event pull, skip, state. */
OPENTLV_WASM_API char* opentlv_wasm_stream_read(wasm_stream_t* s, int operation) {
    builder_t b = {0}; tlv_result_t rc = TLV_OK;
    tlv_reader_diagnostic_t d; tlv_reader_diagnostic_init(&d);
    builder_text(&b, "{\"item\":null");
    if (operation == 2) rc = tlv_tree_reader_skip_subtree(&s->tree_reader);
    else if (operation < 2) {
        tlv_tree_event_t event = {0}; tlv_tree_item_t item = {0};
        tlv_element_t element; tlv_source_t source;
        size_t depth = 0, offset = 0; int constructed = 0;
        if (s->kind == 0) {
            offset = tlv_reader_offset(&s->reader);
            rc = tlv_reader_next_source_diag(&s->reader, &element, &source, &d);
        } else if (operation == 0) {
            rc = tlv_tree_reader_next_diag(&s->tree_reader, &item, &d);
            if (rc == TLV_OK) {
                element = item.element; source = item.source; depth = item.depth;
                offset = item.offset; constructed = item.constructed;
            }
        } else {
            rc = tlv_tree_reader_next_event_diag(&s->tree_reader, &event, &d);
            if (rc == TLV_OK) {
                element = event.element; source = event.source; depth = event.depth;
                offset = event.offset; constructed = event.kind == TLV_TREE_BEGIN;
            }
        }
        if (rc == TLV_OK) {
            /* Replace the initial null instead of emitting duplicate JSON keys. */
            b.size = 0; builder_text(&b, "{\"item\":{\"element\":");
            if (operation == 1 && event.kind == TLV_TREE_END) builder_text(&b, "null");
            else { stream_element(&b, &element); stream_source(&b, &source); }
            query_field(&b, "depth", depth); query_field(&b, "offset", offset);
            if (s->kind == 1)
                builder_text(&b, constructed ? ",\"constructed\":true" : ",\"constructed\":false");
            if (operation == 1) {
                builder_text(&b, ",\"kind\":");
                builder_json_string(&b, event.kind == TLV_TREE_BEGIN ? "begin" : event.kind == TLV_TREE_END ? "end" : "element");
                builder_text(&b, event.skipped ? ",\"skipped\":true" : ",\"skipped\":false");
            }
            builder_text(&b, "}");
        }
    }
    query_field(&b, "consumed", s->kind == 0 ? tlv_reader_consumed(&s->reader) : tlv_tree_reader_consumed(&s->tree_reader));
    query_field(&b, "offset", s->kind == 0 ? tlv_reader_offset(&s->reader) : tlv_tree_reader_offset(&s->tree_reader));
    int end = s->kind == 0 ? tlv_reader_at_end(&s->reader) : tlv_tree_reader_at_end(&s->tree_reader);
    builder_text(&b, end ? ",\"atEnd\":true" : ",\"atEnd\":false");
    if (rc != TLV_OK && rc != TLV_END) stream_reader_detail(&b, &d);
    return field_reply(&b, rc);
}
OPENTLV_WASM_API int opentlv_wasm_stream_input(wasm_stream_t* s, const uint8_t* data,
                                               size_t size, size_t discard, int final_input, int reset) {
    tlv_reader_t* r = s->kind == 0 ? &s->reader : &s->tree_reader.input;
    /* Core requires retained-prefix identity; enforce it at the owning boundary. */
    if (!reset && (discard > r->size || size < r->size - discard ||
        (r->size > discard && memcmp(data, s->data + discard, r->size - discard))))
        return TLV_ERR_INVALID_ARG;
    uint8_t* copy = stream_copy(data, size);
    if (!copy) return TLV_ERR_OUT_OF_MEMORY;
    tlv_result_t rc;
    if (reset && s->kind == 0) rc = final_input ? tlv_reader_init(r, copy, size, &s->owner->format)
        : tlv_reader_init_incremental(r, copy, size, &s->owner->format);
    else if (reset) {
        tlv_tree_reader_t* t = &s->tree_reader;
        rc = final_input ? tlv_tree_reader_init(t, copy, size, &s->owner->format,
            s->read_frames, t->capacity, t->max_depth, t->max_elements)
            : tlv_tree_reader_init_incremental(t, copy, size, &s->owner->format,
                s->read_frames, t->capacity, t->max_depth, t->max_elements);
    } else rc = s->kind == 0 ? tlv_reader_set_input(r, copy, size, discard, final_input)
        : tlv_tree_reader_set_input(&s->tree_reader, copy, size, discard, final_input);
    if (rc == TLV_OK) { free(s->data); s->data = copy; } else free(copy);
    return rc;
}
typedef int (*wasm_stream_visit_fn)(const char* json);
typedef struct { wasm_stream_visit_fn callback; int failed; } wasm_stream_visit_t;
static tlv_visit_result_t stream_visit_tree(const tlv_element_t* e, size_t depth,
                                            size_t offset, void* context) {
    wasm_stream_visit_t* v = context; builder_t b = {0};
    builder_text(&b, "{\"element\":"); stream_element(&b, e);
    query_field(&b, "depth", depth); query_field(&b, "offset", offset); builder_text(&b, "}");
    if (b.failed) { free(b.data); v->failed = 1; return TLV_VISIT_ERROR; }
    int result = v->callback(b.data); free(b.data);
    return (tlv_visit_result_t)result;
}
static tlv_visit_result_t stream_visit(const tlv_element_t* e, void* context) {
    return stream_visit_tree(e, 0, 0, context);
}
OPENTLV_WASM_API char* opentlv_wasm_stream_visit(wasm_stream_t* s, wasm_stream_visit_fn callback) {
    builder_t b = {0}; tlv_reader_diagnostic_t d; tlv_reader_diagnostic_init(&d);
    wasm_stream_visit_t v = {callback, 0};
    tlv_result_t rc = s->kind == 0 ? tlv_reader_visit_diag(&s->reader, stream_visit, &v, &d)
        : tlv_tree_reader_visit(&s->tree_reader, stream_visit_tree, &v, &d);
    if (v.failed) rc = TLV_ERR_OUT_OF_MEMORY;
    builder_text(&b, "{\"item\":null");
    if (rc != TLV_OK) stream_reader_detail(&b, &d);
    return field_reply(&b, rc);
}
/* write element, copy encoded, preserve, begin, end, finish, snapshot, event, measure element */
OPENTLV_WASM_API char* opentlv_wasm_stream_write(wasm_stream_t* s, int operation,
    const uint8_t* tag, size_t tag_size, const uint8_t* value, size_t value_size,
    const uint8_t* encoded, size_t encoded_size, int kind, size_t depth, int skipped) {
    builder_t b = {0}; tlv_writer_diagnostic_t d; tlv_writer_diagnostic_init(&d);
    tlv_result_t rc = TLV_OK; size_t measured = 0;
    tlv_element_t element = {tlv_tag(tag, tag_size), {value, value_size}};
    if (operation == 0) rc = s->kind == 2 ? tlv_writer_write_element_diag(&s->writer, &element, &d)
        : tlv_tree_writer_write_element_diag(&s->tree_writer, &element, &d);
    else if (operation == 1) rc = tlv_writer_copy_encoded_diag(&s->writer, encoded, encoded_size, &d);
    else if (operation == 2) {
        tlv_element_t original; tlv_source_t source; size_t consumed;
        tlv_reader_diagnostic_t reader_detail; tlv_reader_diagnostic_init(&reader_detail);
        rc = tlv_read_source_diag(encoded, encoded_size, &s->owner->format, &original, &consumed, &source, &reader_detail);
        if (rc == TLV_OK) rc = tlv_writer_preserve_diag(&s->writer, &source, &element, &d);
        else {
            if (rc == TLV_END) rc = TLV_ERR_INVALID_ARG;
            builder_text(&b, "{\"value\":null"); stream_reader_detail(&b, &reader_detail);
            return field_reply(&b, rc);
        }
    } else if (operation == 3) rc = tlv_tree_writer_begin_diag(&s->tree_writer, element.tag, &d);
    else if (operation == 4) rc = tlv_tree_writer_end_diag(&s->tree_writer, &d);
    else if (operation == 5) rc = tlv_tree_writer_finish(&s->tree_writer);
    else if (operation == 7) {
        tlv_tree_event_t event = {0}; event.kind = (tlv_tree_event_kind_t)kind;
        event.element = element; event.depth = depth; event.skipped = skipped;
        rc = tlv_tree_writer_write_event_diag(&s->tree_writer, &event, &d);
    } else if (operation == 8) rc = tlv_element_encoded_size_diag(&element, &s->owner->format, &measured, &d);
    size_t count = s->kind == 2 ? tlv_writer_size(&s->writer) : tlv_tree_writer_size(&s->tree_writer);
    builder_text(&b, "{\"value\":");
    if (operation == 6) { builder_text(&b, "\""); builder_hex(&b, s->data, count); builder_text(&b, "\""); }
    else builder_text(&b, "null");
    query_field(&b, "size", count); query_field(&b, "measured", measured);
    query_field(&b, "remaining", s->kind == 2 ? tlv_writer_remaining(&s->writer)
        : tlv_writer_remaining(&s->tree_writer.output));
    if (rc != TLV_OK) stream_writer_detail(&b, &d);
    return field_reply(&b, rc);
}
typedef struct { const uint32_t* records; size_t count, index; } wasm_stream_records_t;
static tlv_result_t stream_next_event(void* context, tlv_tree_event_t* event) {
    wasm_stream_records_t* p = context;
    if (p->index == p->count) return TLV_END;
    const uint32_t* r = p->records + 7 * p->index++;
    memset(event, 0, sizeof *event);
    event->kind = (tlv_tree_event_kind_t)r[0]; event->depth = r[1];
    event->element.tag = tlv_tag((const uint8_t*)(uintptr_t)r[2], r[3]);
    event->element.value = (tlv_value_t){(const uint8_t*)(uintptr_t)r[4], r[5]};
    event->skipped = (int)r[6]; return TLV_OK;
}
static tlv_result_t stream_next_node(void* context, tlv_element_t* element, size_t* depth, int* constructed) {
    tlv_tree_event_t event; tlv_result_t rc = stream_next_event(context, &event);
    if (rc == TLV_OK) {
        *element = event.element; *depth = event.depth; *constructed = event.kind == TLV_TREE_BEGIN;
    }
    return rc;
}
OPENTLV_WASM_API char* opentlv_wasm_stream_measure(wasm_stream_t* s, const uint32_t* records,
                                                   size_t count, int events) {
    builder_t b = {0}; size_t measured = 0;
    tlv_writer_diagnostic_t d; tlv_writer_diagnostic_init(&d);
    tlv_tree_writer_t* w = &s->tree_writer;
    tlv_tree_writer_workspace_t workspace = {s->write_frames, w->capacity, s->data,
        w->output.capacity, s->scratch, w->scratch_capacity, 0, 0};
    wasm_stream_records_t provider = {records, count, 0};
    tlv_result_t rc = events ? tlv_tree_writer_measure_events(&s->owner->format,
        stream_next_event, &provider, &workspace, w->max_depth, w->max_elements, &measured, &d)
        : tlv_tree_writer_measure(&s->owner->format, stream_next_node, &provider,
            &workspace, w->max_depth, w->max_elements, &measured, &d);
    builder_text(&b, "{\"value\":\"");
    if (rc == TLV_OK) builder_hex(&b, s->data, measured);
    builder_text(&b, "\""); query_field(&b, "size", measured);
    query_field(&b, "requiredData", workspace.required_data);
    query_field(&b, "requiredScratch", workspace.required_scratch);
    if (rc != TLV_OK) stream_writer_detail(&b, &d);
    return field_reply(&b, rc);
}
