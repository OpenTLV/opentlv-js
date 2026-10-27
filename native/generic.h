// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel
/* Call-scoped representation transfer; Core owns constraint and tag semantics. */
#include <tlv/schema/constraint.h>

/* values contains min, max, candidate and count allowed signed 64-bit values.
 * names contains count nullable NUL-terminated strings. Nothing is retained. */
OPENTLV_WASM_API char* opentlv_wasm_constraint(int kind, int operation,
    const int64_t* values, size_t count, const char* const* names) {
    tlv_value_constraint_t constraint = {0};
    constraint.kind = (tlv_value_constraint_kind_t)kind;
    constraint.min_value = values[0]; constraint.max_value = values[1];
    constraint.allowed_values = values + 3; constraint.allowed_values_count = count;
    constraint.allowed_value_names = names;
    tlv_result_t rc = tlv_value_constraint_check(&constraint);
    if (rc == TLV_OK && operation == 1)
        rc = tlv_value_constraint_validate(&constraint, values[2]);
    const char* name = rc == TLV_OK && operation == 2
        ? tlv_value_constraint_name(&constraint, values[2]) : NULL;
    builder_t b = {0}; builder_text(&b, "{\"name\":");
    if (name) builder_json_string(&b, name); else builder_text(&b, "null");
    return field_reply(&b, rc);
}

OPENTLV_WASM_API char* opentlv_wasm_tag_operation(int operation,
    const uint8_t* left, size_t left_size, const uint8_t* right, size_t right_size) {
    tlv_tag_t tag = tlv_tag(left, left_size);
    builder_t b = {0}; builder_text(&b, "{\"value\":");
    if (operation == 0) {
        int order = tlv_tag_compare(tag, tlv_tag(right, right_size));
        builder_text(&b, order < 0 ? "-1" : order > 0 ? "1" : "0");
    } else builder_number(&b, tlv_tag_hash(tag));
    return field_reply(&b, TLV_OK);
}
