// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel
// Ownership and transfer only. The C engine owns all Query semantics.
export function queryFacade(wasm) {
  const encoder = new TextEncoder();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  const types = Object.freeze({ integer: 2, bytes: 3, string: 4 });
  // Result and Query error values come from the C enums, never hard-coded
  // numbers. TLV_ERR_INVALID_STATE always reports the Query STATE category.
  const constantsPointer = wasm._opentlv_wasm_constants();
  if (!constantsPointer) throw new Error("out of memory");
  const constants = JSON.parse(wasm.UTF8ToString(constantsPointer));
  const { END, INVALID_TAG, INVALID_ARG, INVALID_STATE, BUFFER_TOO_SHORT, OUT_OF_MEMORY, UNSUPPORTED,
    CALLBACK } = constants.result;
  const QUERY_ERROR_STATE = constants.query_error.STATE;
  class QueryError extends Error {
    constructor(code, query = {}, applied = 0, rule = null, schema = null, location = { domain: "unknown", kind: "unknown" }, message = null) {
      super(message ?? wasm.UTF8ToString(wasm._opentlv_wasm_strerror(code)));
      this.code = code;
      this.location = Object.freeze(location);
      // Native replies already name their category; only facade STATE checks need one.
      this.query = Object.freeze(code === INVALID_STATE ? { ...query, kind: QUERY_ERROR_STATE,
        kind_name: wasm.UTF8ToString(wasm._opentlv_wasm_query_error_kind_string(QUERY_ERROR_STATE)) }
        : query);
      this.applied = applied;
      this.rule = rule;
      this.schema = schema;
    }
  }
  function check(code) { if (code) throw new QueryError(code); }
  function response(pointer, allowEnd = false) {
    if (!pointer) throw new QueryError(OUT_OF_MEMORY);
    const reply = JSON.parse(wasm.UTF8ToString(pointer));
    for (const reader of [reply.query?.reader, reply.query?.codec_detail?.reader]) {
      if (!reader) continue;
      for (const field of ["declared_length", "required"]) {
        if (Object.hasOwn(reader, field)) {
          const value = BigInt(reader[field]);
          reader[field] = value <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(value) : value;
        }
      }
    }
    if (reply.code && !(allowEnd && reply.code === END)) {
      const error = new QueryError(reply.code, reply.query, reply.applied, reply.rule, reply.schema, reply.location, reply.message);
      if (reply.diagnostic) error.diagnostic = reply.diagnostic;
      if (reply.reader) error.reader = reply.reader;
      throw error;
    }
    return reply;
  }
  function bytes(value) {
    if (!(value instanceof Uint8Array)) throw new TypeError("Uint8Array required");
    return value;
  }
  function unhex(value) {
    return Uint8Array.from(value.match(/../g) || [], pair => parseInt(pair, 16));
  }
  function size(value) {
    if (!Number.isInteger(value) || value < 0 || value > 0xffffffff) {
      throw new RangeError("nonnegative wasm32 size required");
    }
    return value;
  }
  function string(value) {
    if (typeof value !== "string" || value.includes("\0")) throw new TypeError("NUL-free string required");
    return encoder.encode(value + "\0");
  }
  function temporary(data, run) {
    const pointer = wasm._opentlv_wasm_alloc(data.length);
    if (!pointer) throw new QueryError(OUT_OF_MEMORY);
    try { wasm.HEAPU8.set(data, pointer); return run(pointer); }
    finally { wasm._opentlv_wasm_free(pointer); }
  }
  function scalar(reply) {
    if (reply.kind === 1) return reply.value;
    if (reply.kind === 2) {
      const value = BigInt(reply.value);
      return value >= BigInt(Number.MIN_SAFE_INTEGER) && value <= BigInt(Number.MAX_SAFE_INTEGER)
        ? Number(value) : value;
    }
    if (reply.kind === 3) return unhex(reply.value);
    if (reply.kind === 4) return decoder.decode(unhex(reply.value));
    throw new TypeError("scalar Query required");
  }
  function pointers(values) {
    const data = new Uint8Array(values.length * 4);
    const view = new DataView(data.buffer);
    values.forEach((value, index) => view.setUint32(index * 4, value, true));
    return data;
  }
  function temporaries(data, run) {
    const allocated = [];
    try {
      for (const item of data) {
        const pointer = wasm._opentlv_wasm_alloc(item.length);
        if (!pointer) throw new QueryError(OUT_OF_MEMORY);
        allocated.push(pointer);
        wasm.HEAPU8.set(item, pointer);
      }
      return run(allocated);
    } finally { for (const pointer of allocated) wasm._opentlv_wasm_free(pointer); }
  }
  function int64(value, write) {
    if (typeof value !== "bigint" && !Number.isSafeInteger(value)) throw new TypeError("safe integer or bigint required");
    const integer = BigInt(value);
    if (integer < -(1n << 63n) || integer >= (1n << 63n)) throw new RangeError("int64 required");
    write(Number(BigInt.asUintN(32, integer)), Number(BigInt.asUintN(32, integer >> 32n)));
  }
  function tagBytes(tag) {
    const start = wasm._opentlv_wasm_tag_field(tag, 0);
    return wasm.HEAPU8.slice(start, start + wasm._opentlv_wasm_tag_field(tag, 1));
  }
  /** Snapshot explicit scoped identifiers. Unknown names return null; conflicting definitions fail. */
  function definitionResolver(scopes) {
    const table = new Map();
    for (const [scope, definitions] of Object.entries(scopes)) {
      for (const { name, tag } of definitions) {
        if (typeof name !== "string" || typeof scope !== "string") throw new TypeError("string scope/name required");
        const key = JSON.stringify([scope, name]);
        if (table.has(key)) throw new TypeError(`ambiguous definition: ${scope}:${name}`);
        table.set(key, bytes(tag).slice());
      }
    }
    return (scope, name) => {
      if (scope) return table.get(JSON.stringify([scope, name]))?.slice() ?? null;
      const matches = [...table].filter(([key]) => JSON.parse(key)[1] === name);
      if (matches.length > 1) throw new QueryError(INVALID_ARG);
      return matches[0]?.[1].slice() ?? null;
    };
  }
  function nameResolver(names) {
    const scopes = Object.create(null);
    for (const [qualified, tag] of Object.entries(names)) {
      const colon = qualified.indexOf(":");
      const scope = colon < 0 ? "" : qualified.slice(0, colon);
      const name = colon < 0 ? qualified : qualified.slice(colon + 1);
      (scopes[scope] ??= []).push({ name, tag });
    }
    return definitionResolver(scopes);
  }
  /** Owning native Format configuration. Callbacks receive copies; native Reader/Writer validate framing. */
  // BEGIN generic-fields #3
  // Generic fields retain immutable native configuration. No wire parsing in JS.
  const fieldToken = Symbol("field"), composedToken = Symbol("composed format");
  const fieldState = new WeakMap();
  const customFormats = new WeakSet();
  class FormatError extends Error {
    constructor(code, detail = null, consumed = 0) {
      super(wasm.UTF8ToString(wasm._opentlv_wasm_strerror(code)));
      this.code = code; this.format = detail; this.consumed = consumed;
      if (detail?.required != null) detail.required = unsignedResult(detail.required);
    }
  }
  function unsigned(value) {
    if (typeof value !== "bigint" && !Number.isSafeInteger(value)) throw new TypeError("safe integer or bigint required");
    const n = BigInt(value);
    if (n < 0n || n > 0xffffffffffffffffn) throw new RangeError("uint64 required");
    return [Number(n & 0xffffffffn), Number(n >> 32n)];
  }
  function unsignedResult(value) {
    const n = BigInt(value);
    return n <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(n) : n;
  }
  function octet(value) { size(value); if (value > 255) throw new RangeError("byte required"); return value; }
  function flag(value) { if (typeof value !== "boolean") throw new TypeError("boolean required"); return Number(value); }
  function byteOrder(value = "big") {
    if (!["big", "little"].includes(value)) throw new TypeError("big or little byte order required");
    return value === "big" ? 1 : 0;
  }
  function fieldResponse(pointer) {
    if (!pointer) throw new FormatError(OUT_OF_MEMORY);
    try {
      const result = JSON.parse(wasm.UTF8ToString(pointer));
      if (result.code) throw new FormatError(result.code, result.format, result.consumed);
      return result;
    } finally { wasm._opentlv_wasm_free(pointer); }
  }
  function created(run) {
    return temporary(new Uint8Array(4), error => {
      const result = run(error);
      const code = new DataView(wasm.HEAPU8.buffer).getUint32(error, true);
      if (code) throw new FormatError(code);
      if (!result) throw new FormatError(OUT_OF_MEMORY);
      return result;
    });
  }
  function fieldInfo(field) {
    const state = fieldState.get(field);
    if (!state) throw new TypeError("Field from this module required");
    if (!state.pointer) throw new FormatError(INVALID_STATE);
    return state;
  }
  class Field {
    constructor(token, kind, config, forbidden = new Uint8Array()) {
      if (token !== fieldToken) throw new TypeError("Use a Field factory");
      const words = new Array(10).fill(0); config.forEach((v, i) => { words[i] = v; });
      const pointer = temporaries([pointers(words), bytes(forbidden)], ([p, f]) =>
        created(error => wasm._opentlv_wasm_field_new(kind, p, f, forbidden.length, error)));
      fieldState.set(this, { pointer, kind });
    }
    static fixedIdentifier(width = 1) { return new Field(fieldToken, 0, [size(width)]); }
    static variableIdentifier({ inline_mask = 31, escape = 31, continuation_bit = 128,
      payload_mask = 127, max_size = 16, policy = null } = {}) {
      return new Field(fieldToken, 1, [octet(inline_mask), octet(escape), octet(continuation_bit),
        octet(payload_mask), size(max_size), Number(policy != null),
        flag(policy?.reject_zero_first_payload ?? false), flag(policy?.require_minimal ?? false)],
        policy?.forbidden_leading ?? new Uint8Array());
    }
    static fixedLength(width = 1, byte_order = "big") {
      return new Field(fieldToken, 2, [size(width), byteOrder(byte_order)]);
    }
    static variableLength({ long_form_bit = 128, payload_mask = 127, byte_order = "big", policy = null } = {}) {
      return new Field(fieldToken, 3, [octet(long_form_bit), octet(payload_mask), byteOrder(byte_order),
        Number(policy != null), flag(policy?.allow_short ?? true), flag(policy?.allow_long ?? true),
        flag(policy?.require_minimal ?? false), size(policy?.max_long_octets ?? 8),
        ...unsigned(policy?.max_value ?? 0xffffffffffffffffn)]);
    }
    static escapedLength({ escape = 255, extended_size = 2, byte_order = "big",
      min_extended = 255, max_length = 65535 } = {}) {
      return new Field(fieldToken, 4, [octet(escape), size(extended_size), byteOrder(byte_order),
        ...unsigned(min_extended), ...unsigned(max_length)]);
    }
    static packed({ storage_size = 1, bit_offset = 0, bit_width = 8, byte_order = "big" } = {}) {
      return new Field(fieldToken, 5, [size(storage_size), size(bit_offset), size(bit_width), byteOrder(byte_order)]);
    }
    close() {
      const state = fieldState.get(this);
      if (state.pointer) wasm._opentlv_wasm_field_free(state.pointer);
      state.pointer = 0;
    }
    read(input) {
      const { kind } = fieldInfo(this); bytes(input);
      const count = input.length;
      const reply = temporary(input, data => fieldResponse(wasm._opentlv_wasm_field_operation(fieldInfo(this).pointer, 0, data, count, 0, 0)));
      return kind < 2 ? { tag: unhex(reply.value), consumed: reply.consumed }
        : { value: unsignedResult(reply.value), consumed: reply.consumed };
    }
    encode(value, storage = undefined) {
      const { kind } = fieldInfo(this);
      const input = kind < 2 ? bytes(value) : kind === 5 ? bytes(storage) : new Uint8Array();
      const [low, high] = kind < 2 ? [0, 0] : unsigned(value);
      const count = input.length;
      return temporary(input, data => unhex(fieldResponse(
        wasm._opentlv_wasm_field_operation(fieldInfo(this).pointer, 1, data, count, low, high)).value));
    }
  }
  function createComposed({ kind, identifier, length, element_order = "tlv", length_scope = "value",
    constructed = null, header_size = 0, tag_size = 0, tag_storage = new Uint8Array(), tag_only = [] }) {
    const id = fieldInfo(identifier), len = fieldInfo(length);
    if (!["tlv", "ltv"].includes(element_order) || !["value", "tag-and-value"].includes(length_scope))
      throw new TypeError("invalid field order or length scope");
    if (!Array.isArray(tag_only)) throw new TypeError("tag_only array required");
    const tags = tag_only.map(bytes);
    const storageSize = bytes(tag_storage).length;
    const options = pointers([Number(element_order === "ltv"), Number(length_scope === "tag-and-value"),
      Number(constructed != null), size(constructed?.byte_index ?? 0), octet(constructed?.mask ?? 0),
      octet(constructed?.value ?? 0), size(header_size), size(tag_size)]);
    return temporaries([options, bytes(tag_storage), pointers(tags.map(t => size(t.length))), ...tags],
      ([p, storage, sizes, ...tagPointers]) => temporary(pointers(tagPointers), table => created(error =>
        wasm._opentlv_wasm_composed_new(kind, id.pointer, len.pointer, p, storage, storageSize,
          table, sizes, tags.length, error))));
  }
  function composedWithFields(kind, options, identifier, makeLength) {
    let length;
    try { length = makeLength(); return new Format(composedToken, { ...options, kind, identifier, length }); }
    finally { identifier.close(); length?.close(); }
  }
  // END generic-fields #3
  class Format {
    constructor(name = "ber", options = {}) {
      const { tag_size = 1, length_size = 1, byte_order = "big", element_order = "tlv", length_scope = "value" } = options;
      if (!["big", "little"].includes(byte_order) || !["tlv", "ltv"].includes(element_order) ||
          !["value", "tag-and-value"].includes(length_scope)) throw new TypeError("invalid Fixed configuration");
      this._pointer = name === composedToken ? createComposed(options) : temporary(string(name), pointer => wasm._opentlv_wasm_format_new(pointer,
        size(tag_size), size(length_size), Number(byte_order === "big"), Number(element_order === "ltv"), Number(length_scope === "tag-and-value")));
      if (!this._pointer) throw new QueryError(UNSUPPORTED);
      this._callbacks = []; this._references = 1; this._active = false; this._failed = false; this._error = null;
      const owner = this._pointer;
      const callback = (fn, signature) => {
        const pointer = wasm.addFunction((...args) => {
          this._active = true;
          try { return fn(...args); }
          catch (error) { this._error = error; this._failed = true; return INVALID_ARG; }
          finally { this._active = false; }
        }, signature);
        this._callbacks.push(pointer); return pointer;
      };
      const element = pointer => {
        const tag = wasm._opentlv_wasm_element_field(pointer, 0), tagSize = wasm._opentlv_wasm_element_field(pointer, 1);
        const value = wasm._opentlv_wasm_element_field(pointer, 2), valueSize = wasm._opentlv_wasm_element_field(pointer, 3);
        return Object.freeze({ tag: tag ? wasm.HEAPU8.slice(tag, tag + tagSize) : null, value: value ? wasm.HEAPU8.slice(value, value + valueSize) : null, valueSize });
      };
      try {
        const classify = options.isConstructed;
        if (classify !== undefined && typeof classify !== "function") throw new TypeError("isConstructed callback required");
        const constructed = classify ? callback((context, tag) => Number(Boolean(classify(tagBytes(tag)))), "iii") : 0;
        if (name === "custom") {
          customFormats.add(this);
          const { decode, measure, encode } = options;
          if (typeof decode !== "function" || Boolean(measure) !== Boolean(encode) ||
              (measure && (typeof measure !== "function" || typeof encode !== "function"))) throw new TypeError("decode and optional measure/encode pair required");
          const read = callback((context, data, length, result) => {
            const decoded = decode(wasm.HEAPU8.slice(data, data + length));
            if (decoded?.code) return size(decoded.code);
            const { tag, header, value, trailer = { offset: value.offset + value.size, size: 0 }, tagRange = null, lengthRange = null } = decoded;
            const ranges = [header, tagRange, lengthRange, value, trailer].flatMap(range => range ? [size(range.offset), size(range.size)] : [0xffffffff, 0]);
            return temporary(tag === null ? new Uint8Array() : bytes(tag), tagPointer => temporary(pointers(ranges), rangePointer =>
              wasm._opentlv_wasm_format_decoded(owner, result, data, length, tag === null ? 0 : tagPointer, tag?.length ?? 0, rangePointer)));
          }, "iiiiii");
          const measurePointer = measure ? callback((context, input, result) => {
            const e = element(input), layout = measure(e);
            if (layout?.code) return size(layout.code);
            return wasm._opentlv_wasm_encoding_write(result, size(layout.header), size(layout.value ?? e.valueSize), size(layout.trailer ?? 0));
          }, "iiiii") : 0;
          const write = encode ? callback((context, input, data, capacity, written) => {
            const output = encode(element(input));
            if (output?.code) return size(output.code);
            bytes(output);
            if (output.length > capacity) return BUFFER_TOO_SHORT;
            wasm.HEAPU8.set(output, data); wasm._opentlv_wasm_size_write(written, output.length); return 0;
          }, "iiiiiii") : 0;
          check(wasm._opentlv_wasm_format_callbacks(owner, read, measurePointer, write, constructed));
        } else if (classify) check(wasm._opentlv_wasm_format_callbacks(owner, 0, 0, 0, constructed));
      } catch (error) { this.close(); throw error; }
    }
    // BEGIN generic-format-operations #3
    static compose(identifier, length, options = {}) {
      return new Format(composedToken, { ...options, kind: 0, identifier, length });
    }
    static variable(options = {}) {
      return composedWithFields(1, options, Field.variableIdentifier(options.identifier), () => Field.variableLength(options.length));
    }
    static escaped(options = {}) {
      return composedWithFields(2, options, Field.fixedIdentifier(options.tag_size ?? 1), () => Field.escapedLength(options.length));
    }
    static packed(options = {}) {
      return composedWithFields(3, options, Field.packed(options.tag), () => Field.packed(options.length));
    }
    _operation(operation, input = new Uint8Array(), element = {}) {
      if (!this._pointer || this._active) throw new FormatError(INVALID_STATE);
      const suppliedTag = element.tag, suppliedValue = element.value;
      const tag = suppliedTag == null ? new Uint8Array() : bytes(suppliedTag);
      const value = suppliedValue == null ? new Uint8Array() : bytes(suppliedValue);
      if ((operation === 3 || operation === 4) && suppliedValue == null) throw new TypeError("value bytes required");
      const logicalSize = element.valueSize ?? value.length;
      if (suppliedValue != null && BigInt(logicalSize) !== BigInt(value.length)) throw new RangeError("valueSize differs from value bytes");
      const [low, high] = unsigned(logicalSize);
      if (high && customFormats.has(this)) throw new RangeError("custom callback valueSize must fit wasm32");
      const inputSize = bytes(input).length, tagSize = tag.length;
      return this._native(() => temporaries([input, tag, value], ([source, tagPointer, valuePointer]) => {
        // User getters may close a handle while arguments are being copied.
        if (!this._pointer || this._active) throw new FormatError(INVALID_STATE);
        return fieldResponse(wasm._opentlv_wasm_format_operation(this._pointer, operation, source, inputSize,
          suppliedTag == null ? 0 : tagPointer, tagSize, suppliedValue == null ? 0 : valuePointer, low, high)).value;
      }));
    }
    get canRead() { return this._operation(0).canRead; }
    get canWrite() { return this._operation(0).canWrite; }
    decode(input) {
      const result = this._operation(1, input);
      return { ...result, tag: result.tag === null ? null : unhex(result.tag), value: unhex(result.value) };
    }
    measure(element) { return Object.fromEntries(Object.entries(this._operation(2, undefined, element)).map(([k, v]) => [k, unsignedResult(v)])); }
    encode(element) { return unhex(this._operation(3, undefined, element)); }
    preserve(input, element) { return unhex(this._operation(4, input, element)); }
    // END generic-format-operations #3
    static fixed(options = {}) { return new Format("fixed", options); }
    static custom(options) { return new Format("custom", options); }
    _retain() { if (!this._pointer || this._active) throw new QueryError(INVALID_STATE); ++this._references; }
    _release() { if (--this._references === 0) { for (const callback of this._callbacks) wasm.removeFunction(callback); this._callbacks = []; } }
    _throw() { if (this._failed) { const error = this._error; this._failed = false; this._error = null; throw error; } }
    _native(run) { try { return run(); } finally { this._throw(); } }
    close() {
      if (this._active) throw new QueryError(INVALID_STATE);
      if (this._pointer) { wasm._opentlv_wasm_format_free(this._pointer); this._pointer = 0; this._release(); }
    }
  }
  // BEGIN streaming #4
  const streamState = new WeakMap();
  const StreamResult = Object.freeze({ ...constants.result });
  const Visit = Object.freeze({ CONTINUE: 0, STOP: 1, ERROR: 2 });
  class StreamError extends Error {
    constructor(code, reply = {}) {
      super(wasm.UTF8ToString(wasm._opentlv_wasm_strerror(code)));
      this.code = code;
      for (const key of ["diagnostic", "reader", "writer", "requiredData", "requiredScratch"])
        if (reply[key] !== undefined) this[key] = reply[key];
    }
  }
  function streamCheck(code) { if (code) throw new StreamError(code); }
  function streamReply(pointer) {
    if (!pointer) throw new StreamError(OUT_OF_MEMORY);
    try {
      const reply = JSON.parse(wasm.UTF8ToString(pointer));
      for (const key of ["declared_length", "required"])
        if (reply.reader?.[key] !== undefined) reply.reader[key] = unsignedResult(reply.reader[key]);
      if (reply.code && reply.code !== END && reply.code !== constants.result.NEED_MORE_DATA)
        throw new StreamError(reply.code, reply);
      reply.status = reply.code === END ? "end" : reply.code === constants.result.NEED_MORE_DATA ? "need-more-data" : "ok";
      return reply;
    } finally { wasm._opentlv_wasm_free(pointer); }
  }
  function streamItem(item) {
    if (item === null) return null;
    if (item.element) {
      item.tag = item.element.tag === null ? null : unhex(item.element.tag);
      item.value = unhex(item.element.value);
    }
    delete item.element;
    if (item.encoded !== undefined) item.encoded = unhex(item.encoded);
    return item;
  }
  function liveStream(object) {
    const state = streamState.get(object);
    if (!state) throw new TypeError("Reader/Writer from this module required");
    if (!state.pointer || state.active || state.format._active) throw new StreamError(INVALID_STATE);
    return state;
  }
  function streamRun(object, run) {
    const state = liveStream(object); state.active = true;
    try { return state.format._native(() => run(state.pointer, state)); }
    finally { state.active = false; }
  }
  class Stream {
    constructor(kind, input, options) {
      const { format = "ber", incremental = false, frame_capacity = 64, max_depth = 64,
        max_elements = 65536, scratch_capacity = 65536, tag_capacity = 4096 } = options;
      const inputSize = kind < 2 ? bytes(input).length : size(input);
      const config = pointers([flag(incremental), size(frame_capacity), size(max_depth),
        size(max_elements), size(scratch_capacity), size(tag_capacity)]);
      const own = !(format instanceof Format), owner = own ? new Format(format) : format;
      owner._retain();
      let pointer = 0;
      try {
        pointer = temporaries([kind < 2 ? input : new Uint8Array(), config], ([data, p]) =>
          temporary(new Uint8Array(4), error => {
            const result = wasm._opentlv_wasm_stream_new(owner._pointer, kind, data, inputSize, p, error);
            streamCheck(new DataView(wasm.HEAPU8.buffer).getUint32(error, true));
            if (!result) throw new StreamError(OUT_OF_MEMORY);
            return result;
          }));
        streamState.set(this, { pointer, format: owner, kind, active: false, projection: null });
      } finally {
        if (!pointer) owner._release();
        if (own) owner.close();
      }
    }
    close() {
      const state = streamState.get(this);
      if (!state) throw new TypeError("Reader/Writer from this module required");
      if (state.active || state.format._active) throw new StreamError(INVALID_STATE);
      if (state.pointer) {
        wasm._opentlv_wasm_stream_free(state.pointer); state.pointer = 0; state.format._release();
      }
    }
  }
  class InputStream extends Stream {
    _pull(event) {
      return streamRun(this, (pointer, state) => {
        const projection = event ? "events" : "nodes";
        if (state.kind === 1 && state.projection && state.projection !== projection)
          throw new StreamError(INVALID_STATE);
        state.projection = projection;
        const reply = streamReply(wasm._opentlv_wasm_stream_read(pointer, Number(event)));
        return { ...reply, item: streamItem(reply.item) };
      });
    }
    next() { return this._pull(false); }
    get state() {
      return streamRun(this, pointer => {
        const { consumed, offset, atEnd } = streamReply(wasm._opentlv_wasm_stream_read(pointer, 3));
        return { consumed, offset, atEnd };
      });
    }
    setInput(input, { discard = 0, final = false } = {}) {
      bytes(input); size(discard); flag(final);
      return streamRun(this, pointer => temporary(input, data =>
        streamCheck(wasm._opentlv_wasm_stream_input(pointer, data, input.length, discard, Number(final), 0))));
    }
    reset(input = new Uint8Array(), { incremental = false } = {}) {
      bytes(input); flag(incremental);
      return streamRun(this, (pointer, state) => temporary(input, data => {
        streamCheck(wasm._opentlv_wasm_stream_input(pointer, data, input.length, 0, Number(!incremental), 1));
        state.projection = null;
      }));
    }
    visit(visitor) {
      if (typeof visitor !== "function") throw new TypeError("visitor callback required");
      return streamRun(this, (pointer, state) => {
        if (state.projection === "events") throw new StreamError(INVALID_STATE);
        state.projection = "nodes";
        let failed = false, failure;
        const callback = wasm.addFunction(json => {
          try {
            const item = streamItem(JSON.parse(wasm.UTF8ToString(json)));
            if (state.kind === 0) { delete item.depth; delete item.offset; }
            const result = visitor(item);
            if (!Object.values(Visit).includes(result)) throw new TypeError("Return a Visit constant synchronously");
            return result;
          } catch (error) { failed = true; failure = error; return Visit.ERROR; }
        }, "ii");
        try { return streamReply(wasm._opentlv_wasm_stream_visit(pointer, callback)); }
        finally { wasm.removeFunction(callback); if (failed) throw failure; }
      });
    }
  }
  class Reader extends InputStream {
    constructor(input = new Uint8Array(), options = {}) { super(0, input, options); }
    static read(input, options = {}) {
      const reader = new Reader(input, options);
      try { return reader.next(); } finally { reader.close(); }
    }
  }
  class TreeReader extends InputStream {
    constructor(input = new Uint8Array(), options = {}) { super(1, input, options); }
    nextEvent() { return this._pull(true); }
    skipSubtree() { return streamRun(this, p => streamReply(wasm._opentlv_wasm_stream_read(p, 2))); }
  }
  function streamWrite(object, operation, element = {}, encoded = new Uint8Array(), event = {}) {
    // Snapshot getters before entering native code, then check lifetime again.
    const suppliedTag = element.tag, suppliedValue = element.value;
    const tag = suppliedTag == null ? new Uint8Array() : bytes(suppliedTag);
    const value = suppliedValue == null ? new Uint8Array() : bytes(suppliedValue);
    bytes(encoded);
    if ((operation === 0 || operation === 2 || operation === 8) && suppliedValue == null)
      throw new TypeError("value bytes required");
    const kind = event.kind ?? 0, depth = size(event.depth ?? 0), skipped = flag(event.skipped ?? false);
    return streamRun(object, pointer => temporaries([tag, value, encoded], ([t, v, e]) =>
      streamReply(wasm._opentlv_wasm_stream_write(pointer, operation, suppliedTag == null ? 0 : t,
        tag.length, v, value.length, e, encoded.length, kind, depth, skipped))));
  }
  class OutputStream extends Stream {
    write(element) { streamWrite(this, 0, element); }
    measure(element) { return streamWrite(this, 8, element).measured; }
    get size() { return streamWrite(this, 9).size; }
    get remaining() { return streamWrite(this, 9).remaining; }
    get bytes() { return unhex(streamWrite(this, 6).value); }
  }
  class Writer extends OutputStream {
    constructor({ capacity = 65536, ...options } = {}) { super(2, size(capacity), options); }
    static encode(element, options = {}) {
      const writer = new Writer(options);
      try { writer.write(element); return writer.bytes; } finally { writer.close(); }
    }
    copyEncoded(encoded) { streamWrite(this, 1, {}, bytes(encoded)); }
    preserve(source, element = source) {
      // Re-decode the owned encoding through this Writer's Format; never trust JS ranges.
      streamWrite(this, 2, element, bytes(source.encoded));
    }
  }
  function eventKind(kind) {
    const result = ["begin", "element", "end"].indexOf(kind);
    if (result < 0) throw new TypeError("begin, element or end event required");
    return result;
  }
  class TreeWriter extends OutputStream {
    constructor({ capacity = 65536, ...options } = {}) { super(3, size(capacity), options); }
    begin(tag) { streamWrite(this, 3, { tag: bytes(tag) }); }
    end() { streamWrite(this, 4); }
    finish() { streamWrite(this, 5); return this.bytes; }
    writeEvent(event) {
      const kind = eventKind(event.kind);
      if (kind === 1) bytes(event.value);
      streamWrite(this, 7, event, undefined, { kind, depth: event.depth, skipped: event.skipped });
    }
    static measure(items, options = {}) { return measureTree(items, options, false); }
    static measureEvents(events, options = {}) { return measureTree(events, options, true); }
  }
  function measureTree(items, options, events) {
    if (!Array.isArray(items)) throw new TypeError("array of nodes/events required");
    // Snapshot input once. Keep all Tags alive until Core's one-shot measurement finishes.
    const entries = items.map(item => {
      const kind = events ? eventKind(item.kind) : flag(item.constructed ?? false) ? 0 : 1;
      const tag = item.tag == null ? null : bytes(item.tag).slice();
      const value = kind === 1 ? bytes(item.value).slice() : new Uint8Array();
      return { kind, depth: size(item.depth), tag, value, skipped: flag(item.skipped ?? false) };
    });
    const writer = new TreeWriter(options);
    try {
      return streamRun(writer, pointer => temporaries(entries.flatMap(e => [e.tag ?? new Uint8Array(), e.value]), ptrs => {
        const records = pointers(entries.flatMap((e, i) => [e.kind, e.depth, e.tag === null ? 0 : ptrs[2 * i],
          e.tag?.length ?? 0, ptrs[2 * i + 1], e.value.length, e.skipped]));
        return temporary(records, data => {
          const reply = streamReply(wasm._opentlv_wasm_stream_measure(pointer, data, entries.length, Number(events)));
          return { size: reply.size, bytes: unhex(reply.value) };
        });
      }));
    } finally { writer.close(); }
  }
  // END streaming #4
  class QueryProgram {
    constructor(text, options = {}, image = false) {
      if (!image && typeof text !== "string") throw new TypeError("Query text must be string");
      const data = image ? bytes(text) : encoder.encode(text);
      const ownFormat = !(options.format instanceof Format);
      this._formatOwner = ownFormat ? new Format(options.format ?? "ber") : options.format;
      this._formatOwner._retain();
      this._pointer = wasm._opentlv_wasm_program_with_format(this._formatOwner._pointer);
      if (ownFormat) this._formatOwner.close();
      if (!this._pointer) { this._formatOwner._release(); throw new QueryError(UNSUPPORTED); }
      this._callbacks = [];
      this._references = 1;
      this._providerActive = false;
      this._providerError = null;
      this._providerFailed = false;
      try {
        const optionNames = ["optimize", "max_text", "max_tokens", "max_nesting", "max_states", "max_pattern", "max_resolved_tag"];
        for (const [key, value] of Object.entries(options)) {
          if (["format", "variables", "names", "providers", "tags", "resolve"].includes(key)) continue;
          const index = optionNames.indexOf(key);
          if (index < 0) throw new TypeError(`unknown compile option: ${key}`);
          check(wasm._opentlv_wasm_program_option(this._pointer, index, index ? size(value) : Number(Boolean(value))));
        }
        for (const [name, type] of Object.entries(options.variables ?? {})) {
          if (!Object.hasOwn(types, type)) throw new TypeError("integer, bytes or string declaration required");
          temporary(string(name), pointer => check(wasm._opentlv_wasm_program_variable(this._pointer, pointer, types[type])));
        }
        for (const [name, tag] of Object.entries(options.names ?? {})) {
          temporary(string(name), pointer => temporary(bytes(tag), dataPointer =>
            check(wasm._opentlv_wasm_program_name(this._pointer, pointer, dataPointer, tag.length))));
        }
        if (options.resolve === "emv") {
          if (options.names !== undefined) throw new TypeError("use one scoped resolver or names mapping");
          check(wasm._opentlv_wasm_program_emv_resolver(this._pointer));
        } else if (options.resolve !== undefined) {
          if (typeof options.resolve !== "function" || options.names !== undefined) throw new TypeError("use one scoped resolver or names mapping");
          const resolve = options.resolve;
          const callback = wasm.addFunction((context, scope, scopeSize, name, nameSize, result) => {
            this._providerActive = true;
            try {
              const tag = resolve(decoder.decode(wasm.HEAPU8.slice(scope, scope + scopeSize)), decoder.decode(wasm.HEAPU8.slice(name, name + nameSize)));
              if (tag == null) return INVALID_TAG;
              return temporary(bytes(tag), data => wasm._opentlv_wasm_resolved_tag(context, result, data, tag.length));
            } catch (error) { this._providerError = error; this._providerFailed = true; return INVALID_ARG; }
            finally { this._providerActive = false; }
          }, "iiiiiii");
          this._callbacks.push(callback); check(wasm._opentlv_wasm_program_resolver(this._pointer, callback));
        }
        if (options.tags !== undefined) {
          const { id, classOf, numberOf } = options.tags;
          if (!size(id) || (!classOf && !numberOf)) throw new TypeError("nonzero tag capability ID and callback required");
          const tagCallback = fn => {
            if (fn === undefined) return 0;
            if (typeof fn !== "function") throw new TypeError("tag callback required");
            const pointer = wasm.addFunction((context, tag, result) => {
              this._providerActive = true;
              try { int64(fn(tagBytes(tag)), (low, high) => wasm._opentlv_wasm_integer_write(result, low, high)); return 0; }
              catch (error) { this._providerError = error; this._providerFailed = true; return INVALID_ARG; }
              finally { this._providerActive = false; }
            }, "iiii");
            this._callbacks.push(pointer); return pointer;
          };
          check(wasm._opentlv_wasm_program_tags(this._pointer, id, tagCallback(classOf), tagCallback(numberOf)));
        }
        const conversions = { num: 0, bcd: 1, text: 2, date: 3 };
        for (const [name, provider] of Object.entries(options.providers ?? {})) {
          if (!Object.hasOwn(conversions, name) || typeof provider?.decode !== "function" || !size(provider.id)) {
            throw new TypeError("providers require num/bcd/text/date, nonzero uint32 ID and decode callback");
          }
          const capacity = size(provider.max_result_bytes ?? 0);
          const decode = provider.decode;
          const callback = wasm.addFunction((context, event, data, length, scratch, available, result, _diagnostic) => {
            this._providerActive = true;
            try {
              const metadata = event ? Object.freeze({
                kind: wasm._opentlv_wasm_provider_event(event, 0),
                depth: wasm._opentlv_wasm_provider_event(event, 1),
                offset: wasm._opentlv_wasm_provider_event(event, 2),
                tag: (() => {
                  const start = wasm._opentlv_wasm_provider_event(event, 3);
                  return wasm.HEAPU8.slice(start, start + wasm._opentlv_wasm_provider_event(event, 4));
                })(),
                value: (() => {
                  const start = wasm._opentlv_wasm_provider_event(event, 5);
                  return wasm.HEAPU8.slice(start, start + wasm._opentlv_wasm_provider_event(event, 6));
                })(),
              }) : null;
              const value = decode(wasm.HEAPU8.slice(data, data + length), metadata);
              if (name === "text") {
                if (typeof value !== "string") throw new TypeError("text provider must return string");
                const output = encoder.encode(value);
                if (output.length > available) return BUFFER_TOO_SHORT;
                wasm.HEAPU8.set(output, scratch);
                wasm._opentlv_wasm_provider_text(result, scratch, output.length);
              } else {
                if (typeof value !== "bigint" && !Number.isSafeInteger(value)) throw new TypeError("integer provider must return safe integer or bigint");
                const integer = BigInt(value);
                if (integer < -(1n << 63n) || integer >= (1n << 63n)) throw new RangeError("int64 required");
                wasm._opentlv_wasm_provider_integer(result, Number(BigInt.asUintN(32, integer)),
                  Number(BigInt.asUintN(32, integer >> 32n)));
              }
              return 0;
            } catch (error) { this._providerError = error; this._providerFailed = true; return CALLBACK; }
            finally { this._providerActive = false; }
          }, "iiiiiiiii");
          this._callbacks.push(callback);
          check(wasm._opentlv_wasm_program_provider(this._pointer, conversions[name], provider.id, capacity, callback));
        }
        const compiled = this._native(() => temporary(data, pointer =>
          response(wasm._opentlv_wasm_program_compile(this._pointer, pointer, data.length, Number(image)))));
        this.info = Object.freeze(compiled.info);
        this.variables = Object.freeze(compiled.variables);
      } catch (error) { this.close(); throw error; }
    }
    static load(image, options = {}) { return new QueryProgram(image, options, true); }
    _check() { if (!this._pointer || this._providerActive || this._formatOwner._active) throw new QueryError(INVALID_STATE); }
    _native(run) {
      try { return this._formatOwner._native(run); }
      finally { if (this._providerFailed) { const error = this._providerError; this._providerFailed = false; this._providerError = null; throw error; } }
    }
    _release() {
      if (--this._references === 0) {
        for (const callback of this._callbacks) wasm.removeFunction(callback);
        this._callbacks = [];
        this._formatOwner._release();
      }
    }
    close() {
      if (this._providerActive || this._formatOwner._active) throw new QueryError(INVALID_STATE);
      if (this._pointer) { wasm._opentlv_wasm_program_free(this._pointer); this._release(); }
      this._pointer = 0;
    }
    format() { this._check(); return response(wasm._opentlv_wasm_program_render(this._pointer, 0)).value; }
    explain() { this._check(); return response(wasm._opentlv_wasm_program_render(this._pointer, 1)).value; }
    image() {
      this._check();
      const pointer = wasm._opentlv_wasm_program_image(this._pointer);
      const length = wasm._opentlv_wasm_program_image_size(this._pointer);
      return wasm.HEAPU8.slice(pointer, pointer + length);
    }
    execution(options = {}) { this._check(); return new QueryExecution(this, options); }
    evaluate(input, { bindings = {}, ...limits } = {}) {
      const execution = this.execution(limits);
      try {
        for (const [name, value] of Object.entries(bindings)) execution.bind(name, value);
        execution.setInput(input);
        if (this.info.result_kind) { execution.finish(); return execution.result(); }
        const matches = [];
        execution.visit(match => { matches.push(match); });
        return matches;
      } finally { execution.close(); }
    }
  }
  /** Bounded V1 path Query value and independent native matcher continuation. */
  class V1Query {
    constructor(text) {
      if (typeof text !== "string") throw new TypeError("Query text required");
      const input = encoder.encode(text);
      this._pointer = temporary(input, pointer => wasm._opentlv_wasm_v1_new(pointer, input.length));
      if (!this._pointer) throw new QueryError(OUT_OF_MEMORY);
      try { this._operation(0); } catch (error) { this.close(); throw error; }
    }
    _operation(operation, tag = new Uint8Array(), depth = 0) {
      if (!this._pointer) throw new QueryError(INVALID_STATE);
      return temporary(bytes(tag), pointer => response(wasm._opentlv_wasm_v1_operation(this._pointer, operation, pointer, tag.length, size(depth))));
    }
    format() { return this._operation(0).text; }
    get steps() { return this._operation(0).steps.map(unhex); }
    matcher() { return new V1Query(this.format()); }
    feed(tag, depth = 0) { return this._operation(2, tag, depth).value; }
    reset() { this._operation(1); return this; }
    evaluate(input, options = {}) {
      const program = new QueryProgram(this.format(), options);
      try { return program.evaluate(input); } finally { program.close(); }
    }
    close() { if (this._pointer) wasm._opentlv_wasm_v1_free(this._pointer); this._pointer = 0; }
  }
  class QuerySchema {
    constructor(rules, { format = "ber" } = {}) {
      this._programs = [];
      this._pointers = [];
      this._names = [];
      this._busy = false;
      this._owner = new QueryProgram("//*", { format });
      this._closed = false;
      try {
        for (const { context, assertion, name = "" } of rules) {
          for (const program of [context, assertion]) {
            if (!(program instanceof QueryProgram)) throw new TypeError("compiled context and assertion required");
            program._check();
            wasm._opentlv_wasm_program_retain(program._pointer);
            ++program._references;
            this._programs.push(program);
            this._pointers.push(program._pointer);
          }
          this._names.push(string(name));
        }
      } catch (error) { this.close(); throw error; }
    }
    close() {
      if (this._busy) throw new QueryError(INVALID_STATE);
      if (this._closed) return;
      this._pointers.forEach((pointer, index) => {
        wasm._opentlv_wasm_program_free(pointer);
        this._programs[index]._release();
      });
      this._pointers = []; this._programs = []; this._owner.close(); this._closed = true;
    }
    _validate(input, document, { max_depth = 64, max_nodes = 1024, max_work = 100000000,
      max_contexts = max_nodes, value_capacity = null } = {}) {
      if (this._closed || this._busy || this._owner._formatOwner._active || this._programs.some(program => program._providerActive || program._formatOwner._active)) throw new QueryError(INVALID_STATE);
      if (document) document._check();
      bytes(input);
      this._busy = true;
      try {
        if (document) ++document._active;
        return temporaries(this._names, names => temporary(pointers(names), namePointer =>
          temporary(pointers(this._pointers), programPointer => temporary(input, dataPointer =>
            response(wasm._opentlv_wasm_schema_validate(this._owner._pointer, programPointer,
              namePointer, this._names.length, document?._pointer ?? 0, dataPointer, input.length,
              size(max_depth), size(max_nodes), size(max_work), size(max_contexts),
              value_capacity === null ? 0 : size(value_capacity), Number(value_capacity === null)))))));
      } finally {
        this._busy = false;
        if (document) --document._active;
        this._owner._formatOwner._throw();
        for (const program of this._programs) {
          program._formatOwner._throw();
          if (program._providerFailed) {
            const error = program._providerError;
            program._providerFailed = false; program._providerError = null;
            throw error;
          }
        }
      }
    }
    validateBuffer(input, options) { this._validate(input, null, options); }
    validateDocument(document, options) {
      if (!(document instanceof Document)) throw new TypeError("Document required");
      this._validate(new Uint8Array(), document, options);
    }
  }
  class QueryExecution {
    constructor(program, { max_depth = 64, max_nodes = 1024, max_work = 100000000, retained = true } = {}) {
      if (!(program instanceof QueryProgram)) throw new TypeError("QueryProgram from this module required");
      program._check();
      this._program = program;
      this._pointer = wasm._opentlv_wasm_execution_new(program._pointer,
        size(max_depth), size(max_nodes), size(max_work), Number(Boolean(retained)));
      if (!this._pointer) response(wasm._opentlv_wasm_program_render(program._pointer, -1));
      ++program._references;
      this._maxNodes = max_nodes;
      this._maxDepth = max_depth;
      this._busy = false;
      this._invalid = false;
      this._document = null;
    }
    _check(allowInvalid = false) {
      if (!this._pointer || this._busy || this._program._providerActive || this._program._formatOwner._active || (!allowInvalid && this._invalid)) throw new QueryError(INVALID_STATE);
      if (!allowInvalid && this._document) this._document._check();
    }
    _operation(operation, argument = 0, allowEnd = false) {
      this._check();
      return this._native(() => wasm._opentlv_wasm_execution_operation(this._pointer, operation, size(argument)), allowEnd);
    }
    _native(run, allowEnd = false) {
      this._busy = true;
      try { return this._program._native(() => {
        try { return response(run(), allowEnd); }
        finally { if (this._program._providerFailed || this._program._formatOwner._failed) this._invalid = true; }
      }); } finally { this._busy = false; }
    }
    close() {
      if (this._busy || this._program._providerActive || this._program._formatOwner._active) throw new QueryError(INVALID_STATE);
      if (this._pointer) { wasm._opentlv_wasm_execution_free(this._pointer); this._program._release(); }
      this._pointer = 0; this._document = null;
    }
    reset() {
      this._check(true);
      response(wasm._opentlv_wasm_execution_operation(this._pointer, 0, 0));
      this._invalid = false; this._document = null;
      return this;
    }
    setInput(input, { discard = 0, final = true } = {}) {
      this._check(); bytes(input);
      temporary(input, pointer => response(wasm._opentlv_wasm_execution_input(this._pointer,
        pointer, input.length, size(discard), Number(Boolean(final)))));
      return this;
    }
    bind(name, value) {
      this._check();
      const type = this._program.variables[name];
      let integer = "0", data = new Uint8Array();
      if (type === "integer") {
        if (typeof value !== "bigint" && !Number.isSafeInteger(value)) throw new RangeError("safe integer or bigint required");
        const number = BigInt(value);
        if (number < -(1n << 63n) || number >= (1n << 63n)) throw new RangeError("int64 required");
        integer = String(number);
      } else if (type === "bytes") data = bytes(value);
      else if (type === "string") {
        if (typeof value !== "string") throw new TypeError("string binding required");
        data = encoder.encode(value);
      } else throw new TypeError("declared variable required");
      temporary(string(name), namePointer => temporary(string(integer), integerPointer => temporary(data, dataPointer =>
        response(wasm._opentlv_wasm_execution_bind(this._pointer, namePointer, types[type], integerPointer, dataPointer, data.length)))));
      return this;
    }
    context(ordinal) { this._operation(5, ordinal); return this; }
    pruning(enabled = true) { this._operation(6, Number(Boolean(enabled))); return this; }
    get info() { return Object.freeze(this._operation(3).value); }
    exists({ early_return = false } = {}) { return this._operation(4, Number(Boolean(early_return))).value; }
    finish() { this._operation(7); return this; }
    feed({ kind, tag = new Uint8Array(), value = new Uint8Array(), source = null, depth = 0, offset = 0, skipped = false }) {
      this._check();
      const kinds = { begin: 0, element: 1, end: 2 };
      if (!Object.hasOwn(kinds, kind)) throw new TypeError("begin, element or end event required");
      bytes(tag); bytes(value);
      if (source !== null && (tag.length || value.length)) throw new TypeError("source determines Tag and Value; omit explicit bytes");
      const reply = source !== null ? temporary(bytes(source), pointer => this._native(() =>
        wasm._opentlv_wasm_execution_feed_source(this._pointer, kinds[kind], pointer, source.length,
          size(depth), size(offset), Number(Boolean(skipped))))) : temporary(tag, tagPointer => temporary(value, valuePointer => this._native(() =>
        wasm._opentlv_wasm_execution_feed(this._pointer, kinds[kind], tagPointer, tag.length,
          valuePointer, value.length, size(depth), size(offset), Number(Boolean(skipped))))));
      return reply.value === null ? null : this._match(reply.value);
    }
    result() { return scalar(this._operation(2)); }
    /** Pull a finalized retained event with its traversal identity (independent of Source offset). */
    nextOrdinal() {
      const reply = this._operation(8, 0, true);
      return reply.code === END ? null : Object.freeze({ ordinal: reply.ordinal, match: this._match(reply.value) });
    }
    _match(value) {
      return Object.freeze({ offset: value.offset, depth: value.depth, constructed: value.kind === 0,
        tag: unhex(value.tag), value: unhex(value.bytes) });
    }
    next() {
      const reply = this._operation(1, 0, true);
      if (reply.code === END) return null;
      return this._document ? new Node(this._document, reply.value) : this._match(reply.value);
    }
    visit(callback) {
      this._check();
      if (typeof callback !== "function") throw new TypeError("callback required");
      if (this._program.info.result_kind) { this.finish(); return; }
      for (;;) {
        const match = this.next();
        if (match === null) return;
        this._busy = true;
        if (this._document) ++this._document._active;
        let action;
        try { action = callback(match); }
        catch (error) { this._invalid = true; throw error; }
        finally { this._busy = false; if (this._document) --this._document._active; }
        if (action === false) return;
      }
    }
    evaluateDocument(document, { value_capacity = null, context = null } = {}) {
      this._check();
      if (!(document instanceof Document)) throw new TypeError("Document required");
      document._check();
      if (document._active) throw new QueryError(INVALID_STATE);
      this._busy = true;
      try {
        if (value_capacity === null) value_capacity = this._program.info.constructed_values_required
          ? document.queryValueSize(this._maxDepth) : 0;
      } finally { this._busy = false; }
      const [address, identity] = documentNode(document, context);
      ++document._active;
      try { temporary(string(identity), id => this._native(() => wasm._opentlv_wasm_execution_document_context(
        this._pointer, document._pointer, size(value_capacity), address, id))); }
      finally { --document._active; }
      this._document = document;
      return this;
    }
    editDocument(kind, { tag = new Uint8Array(), value = new Uint8Array(), target_capacity = this._maxNodes } = {}) {
      this._check();
      const kinds = { remove: 0, replace: 1, insert_after: 2 };
      if (!this._document || !Object.hasOwn(kinds, kind)) throw new TypeError("Document selection and remove/replace/insert_after required");
      if (this._document._active) throw new QueryError(INVALID_STATE);
      bytes(tag); bytes(value);
      ++this._document._active;
      try { return temporary(tag, tagPointer => temporary(value, valuePointer => this._native(() =>
        wasm._opentlv_wasm_execution_edit(this._pointer, kinds[kind], tagPointer, tag.length,
          valuePointer, value.length, size(target_capacity))))).applied; }
      finally { --this._document._active; }
    }
    *[Symbol.iterator]() { for (let node = this.next(); node !== null; node = this.next()) yield node; }
  }
  class Document {
    constructor(input, { format = "ber", retain_source_locations = false, max_depth = 64, max_elements = 65536 } = {}) {
      const empty = input === null;
      if (empty) input = new Uint8Array();
      bytes(input);
      const config = pointers([size(max_depth), size(max_elements), flag(retain_source_locations), Number(empty)]);
      const program = new QueryProgram("//*", { format });
      this._program = program;
      this._pointer = 0;
      try {
        program._native(() => {
          this._pointer = temporaries([input, config], ([pointer, options]) => wasm._opentlv_wasm_document_create(
            program._pointer, pointer, input.length, options));
          if (!this._pointer) response(wasm._opentlv_wasm_program_render(program._pointer, -1));
        });
        ++program._references;
      } catch (error) {
        if (this._pointer) wasm._opentlv_wasm_document_free(this._pointer);
        this._pointer = 0; throw error;
      } finally { program.close(); }
      this._inputSize = input.length;
      this._active = 0;
    }
    _check() { if (!this._pointer || this._program._formatOwner._active) throw new QueryError(INVALID_STATE); }
    close() {
      if (this._active || this._program._formatOwner._active) throw new QueryError(INVALID_STATE);
      if (this._pointer) { wasm._opentlv_wasm_document_free(this._pointer); this._program._release(); }
      this._pointer = 0;
    }
    _node(node, operation, data = new Uint8Array()) {
      this._check();
      if (this._active && (operation === 4 || operation === 5)) throw new QueryError(INVALID_STATE);
      ++this._active;
      try { return this._program._native(() => temporary(string(node?.identity ?? "0"), identity => temporary(data, pointer =>
        response(wasm._opentlv_wasm_document_node(this._pointer, node?._address ?? 0, identity, operation, pointer, data.length)).value))); }
      finally { --this._active; }
    }
    get first() { const value = this._node(null, 0); return value ? new Node(this, value) : null; }
    encode() {
      this._check(); ++this._active;
      try { return this._program._native(() => unhex(response(wasm._opentlv_wasm_document_encode(this._pointer)).value)); }
      finally { --this._active; }
    }
  }
  class Node {
    constructor(document, value) { this._document = document; this._address = value.node; this.identity = value.identity; }
    _get(operation) { return this._document._node(this, operation); }
    _navigate(operation) { const value = this._get(operation); return value ? new Node(this._document, value) : null; }
    get tag() { return unhex(this._get(6).tag); }
    get value() { const value = this._get(6); return value.constructed ? null : unhex(value.bytes); }
    get constructed() { return Boolean(this._get(6).constructed); }
    get firstChild() { return this._navigate(1); }
    get next() { return this._navigate(2); }
    get parent() { return this._navigate(3); }
    setValue(value) { this._document._node(this, 4, bytes(value)); }
    erase() { this._get(5); }
  }
  // BEGIN document-schema #5
  function dsReply(pointer, report = false) {
    if (!pointer) throw new QueryError(OUT_OF_MEMORY);
    try {
      const reply = JSON.parse(wasm.UTF8ToString(pointer));
      if (reply.code && !report) {
        const error = new QueryError(reply.code);
        Object.assign(error, reply.detail ?? reply);
        throw error;
      }
      return reply;
    } finally { wasm._opentlv_wasm_free(pointer); }
  }
  function documentNode(document, node) {
    if (node === null) return [0, "0"];
    if (!(node instanceof Node) || node._document !== document) throw new TypeError("Node from this Document required");
    return [node._address, node.identity];
  }
  Document.create = options => new Document(null, options);
  Document.prototype._operation = function(operation, { node = null, before = null,
    tag = new Uint8Array(), value = new Uint8Array(), format = null } = {}) {
    this._check();
    if (this._active) throw new QueryError(INVALID_STATE);
    const [address, id] = documentNode(this, node), [other, otherId] = documentNode(this, before);
    bytes(tag); bytes(value);
    const target = format === null ? null : new QueryProgram("//*", { format });
    ++this._active;
    try {
      const run = () => temporaries([pointers([operation, address, other]), string(id), string(otherId), tag, value],
        ([config, identity, otherIdentity, t, v]) => dsReply(wasm._opentlv_wasm_document_operation(
          this._pointer, config, identity, otherIdentity, t, tag.length, v, value.length, target?._pointer ?? 0)));
      return this._program._native(() => target ? target._native(run) : run());
    } finally { --this._active; target?.close(); }
  };
  Object.defineProperties(Document.prototype, {
    count: { get() { return this._operation(0).count; } },
    revision: { get() { return BigInt.asUintN(64, BigInt(this._operation(0).revision)); } },
    retireEpoch: { get() { return BigInt.asUintN(64, BigInt(this._operation(0).retireEpoch)); } },
  });
  Document.prototype.insert = function(tag, value = new Uint8Array(), { parent = null, before = null } = {}) {
    return new Node(this, this._operation(1, { node: parent, before, tag, value }).node);
  };
  Document.prototype.find = function(tag, parent = null) {
    const found = this._operation(2, { node: parent, tag }).node;
    return found ? new Node(this, found) : null;
  };
  Document.prototype.findPath = function(path) {
    if (typeof path !== "string") throw new TypeError("Query path string required");
    const found = this._operation(4, { value: encoder.encode(path) }).node;
    return found ? new Node(this, found) : null;
  };
  Document.prototype.encodedSize = function(format = null) { return this._operation(6, { format }).size; };
  Document.prototype.encodeAs = function(format) { return unhex(this._operation(7, { format }).bytes); };
  Document.prototype.queryValueSize = function(max_depth = 64) {
    this._check(); if (this._active) throw new QueryError(INVALID_STATE);
    ++this._active;
    try { return this._program._native(() => dsReply(wasm._opentlv_wasm_document_query_size(this._pointer, size(max_depth))).size); }
    finally { --this._active; }
  };
  Object.defineProperties(Node.prototype, {
    nextSameTag: { get() {
      const found = this._document._operation(3, { node: this }).node;
      return found ? new Node(this._document, found) : null;
    } },
    sourceLocation: { get() { return Object.freeze(this._document._operation(5, { node: this }).location); } },
  });
  Node.prototype.encodedSize = function(format = null) { return this._document._operation(6, { node: this, format }).size; };
  Node.prototype.encode = function(format = null) { return unhex(this._document._operation(7, { node: this, format }).bytes); };
  QueryProgram.prototype.evaluateDocument = function(document, { bindings = {}, ...options } = {}) {
    const execution = this.execution(options);
    try {
      for (const [name, value] of Object.entries(bindings)) execution.bind(name, value);
      execution.evaluateDocument(document, options);
      return this.info.result_kind ? execution.result() : [...execution];
    } finally { execution.close(); }
  };
  QueryProgram.prototype.editDocument = function(document, kind, { bindings = {}, ...options } = {}) {
    const execution = this.execution(options);
    try {
      for (const [name, value] of Object.entries(bindings)) execution.bind(name, value);
      execution.evaluateDocument(document, options);
      return execution.editDocument(kind, options);
    } finally { execution.close(); }
  };
  class DocumentBuilder {
    #reader; #program; #pointer = 0; #busy = false; #done = false;
    constructor(input = new Uint8Array(), { format = "ber", max_depth = 64, max_elements = 65536,
      retain_source_locations = false, ...options } = {}) {
      bytes(input);
      const own = !(format instanceof Format), owner = own ? new Format(format) : format;
      try {
        this.#reader = new TreeReader(input, { ...options, format: owner, max_depth, max_elements });
        this.#program = new QueryProgram("//*", { format: owner });
        this.#pointer = temporary(pointers([size(max_depth), size(max_elements), flag(retain_source_locations)]), config =>
          created(error => wasm._opentlv_wasm_document_builder_new(this.#program._pointer,
            streamState.get(this.#reader).pointer, config, error)));
      } catch (error) { this.#reader?.close(); this.#program?.close(); throw error; }
      finally { if (own) owner.close(); }
    }
    #check() {
      if (!this.#pointer || this.#busy || this.#done || this.#program._formatOwner._active) throw new QueryError(INVALID_STATE);
    }
    setInput(input, options) { this.#check(); this.#reader.setInput(input, options); return this; }
    get state() { this.#check(); return this.#reader.state; }
    consume() {
      this.#check(); this.#busy = true;
      let reply;
      try {
        this.#program._native(() => { reply = streamReply(wasm._opentlv_wasm_document_builder_consume(this.#pointer)); });
        if (reply.status !== "ok") return { status: reply.status, document: null };
        const document = Object.create(Document.prototype);
        document._pointer = reply.document; document._program = this.#program;
        document._active = 0; document._inputSize = 0; ++this.#program._references;
        this.#done = true;
        return { status: "ok", document };
      } catch (error) {
        if (reply?.document) wasm._opentlv_wasm_document_free(reply.document);
        this.#done = true; throw error;
      } finally { this.#busy = false; }
    }
    close() {
      if (this.#busy || this.#program?._formatOwner._active) throw new QueryError(INVALID_STATE);
      if (this.#pointer) wasm._opentlv_wasm_document_builder_free(this.#pointer);
      this.#pointer = 0; this.#reader?.close(); this.#program?.close();
    }
  }
  class SchemaError extends Error {
    constructor(reply) {
      super(wasm.UTF8ToString(wasm._opentlv_wasm_strerror(reply.code)));
      Object.assign(this, reply.detail); this.code = reply.code;
      this.diagnostics = reply.diagnostics ?? [];
      this.schema = reply.detail?.schema ?? null;
    }
  }
  class Schema {
    #pointer = 0; #owner; #busy = false; #entries = []; #tables = [];
    constructor(definition, { format = "ber" } = {}) {
      const tables = [], rules = [], groups = [], buffers = [], seen = new Map();
      const put = data => { buffers.push(data); return buffers.length - 1; };
      const visit = table => {
        if (!table || typeof table !== "object" || !Array.isArray(table.rules)) throw new TypeError("Schema table with rules required");
        if (seen.has(table)) return seen.get(table);
        if (tables.length === 256) throw new RangeError("at most 256 Schema tables");
        const index = tables.length; seen.set(table, index); tables.push(null);
        const start = rules.length, groupStart = groups.length;
        const order = { any: 0, sequence: 1 }[table.order ?? "any"];
        if (order === undefined) throw new TypeError("any or sequence order required");
        for (const r of table.rules) {
          const kind = { any: 0, primitive: 1, constructed: 2 }[r.kind ?? "any"];
          if (kind === undefined) throw new TypeError("invalid Schema kind");
          const entry = { tag: bytes(r.tag).slice(), name: r.name ?? "", min_length: size(r.min_length ?? 0),
            max_length: size(r.max_length ?? 0xffffffff), length_multiple: size(r.length_multiple ?? 0),
            endpoints: r.endpoints ?? false };
          this.#entries.push(entry);
          rules.push([put(entry.tag), entry.tag.length, put(string(entry.name)), entry.min_length, entry.max_length,
            flag(entry.endpoints), entry.length_multiple, size(r.min_occurs ?? 0), size(r.max_occurs ?? 1), kind, 0, size(r.group ?? 0)]);
        }
        for (const g of table.groups ?? []) groups.push([size(g.id), size(g.min_occurs ?? 0), size(g.max_occurs ?? 1), put(string(g.name ?? ""))]);
        tables[index] = [start, table.rules.length, groupStart, groups.length - groupStart, flag(table.allow_unknown ?? false), order];
        table.rules.forEach((r, i) => { if (r.children) rules[start + i][10] = visit(r.children) + 1; });
        return index;
      };
      visit(definition); this.#tables = tables;
      this.#owner = new QueryProgram("//*", { format });
      try {
        temporaries(buffers, pointersToData => {
          const nativeRules = rules.map(r => r.map((v, i) => i === 0 || i === 2 ? pointersToData[v] : v));
          const nativeGroups = groups.map(g => g.map((v, i) => i === 3 ? pointersToData[v] : v));
          temporaries([pointers(tables.flat()), pointers(nativeRules.flat()), pointers(nativeGroups.flat())], ([t, r, g]) => {
            const reply = dsReply(wasm._opentlv_wasm_structure_new(t, tables.length, r, rules.length, g, groups.length), true);
            if (reply.code) throw new SchemaError(reply);
            this.#pointer = reply.schema; structureSchemaHandles.set(this, this.#pointer);
          });
        });
      } catch (error) { this.#owner.close(); throw error; }
    }
    #check() { if (!this.#pointer || this.#busy || this.#owner._formatOwner._active) throw new QueryError(INVALID_STATE); }
    close() {
      if (this.#busy || this.#owner._formatOwner._active) throw new QueryError(INVALID_STATE);
      if (this.#pointer) wasm._opentlv_wasm_structure_free(this.#pointer);
      this.#pointer = 0; this.#owner.close();
    }
    #validate(input, all, { max_depth = 64, max_elements = 65536, capacity = 64, unknown = "schema" } = {}) {
      this.#check(); bytes(input);
      const policy = { schema: 0, allow: 1, reject: 2 }[unknown];
      if (policy === undefined) throw new TypeError("schema, allow or reject unknown policy required");
      const config = pointers([size(max_depth), size(max_elements), Number(all), size(capacity), policy]);
      this.#busy = true;
      try {
        const reply = this.#owner._native(() => temporaries([input, config], ([data, p]) =>
          dsReply(wasm._opentlv_wasm_structure_validate(this.#pointer, this.#owner._pointer, data, input.length, p), true)));
        if (reply.code) throw new SchemaError(reply);
        return reply.diagnostics;
      } finally { this.#busy = false; }
    }
    validate(input, options) { this.#validate(input, false, options); }
    validateAll(input, options) { return this.#validate(input, true, options); }
    find(tag, table = 0) {
      this.#check(); bytes(tag); size(table);
      if (table >= this.#tables.length) throw new RangeError("Schema table index out of range");
      const reply = temporary(tag, p => dsReply(wasm._opentlv_wasm_structure_find(this.#pointer, table, p, tag.length, 0, 0)));
      if (reply.index === null) return null;
      const entry = this.#entries[reply.index]; return { ...entry, tag: entry.tag.slice() };
    }
    validateLength(tag, length, table = 0) {
      this.#check(); bytes(tag); size(table); size(length);
      if (table >= this.#tables.length) throw new RangeError("Schema table index out of range");
      temporary(tag, p => dsReply(wasm._opentlv_wasm_structure_find(this.#pointer, table, p, tag.length, length, 1)));
    }
  }
  // END document-schema #5
  // BEGIN codecs-generator #6
  class CodecError extends Error {
    constructor(reply) {
      super(wasm.UTF8ToString(wasm._opentlv_wasm_strerror(reply.code)));
      this.name = "CodecError"; this.code = reply.code;
      this.diagnostic = reply.diagnostic ?? null; this.codec = reply.codec_detail ?? null;
    }
  }
  function codecReply(pointer) {
    const reply = dsReply(pointer, true);
    if (reply.code) throw new CodecError(reply);
    return reply;
  }
  function integerBytes(value, width = 8, signed = false) {
    if (typeof value !== "bigint" && !Number.isSafeInteger(value)) throw new TypeError("safe integer or bigint required");
    const n = BigInt(value), bits = BigInt(width * 8);
    if (n < (signed ? -(1n << (bits - 1n)) : 0n) || n >= (1n << (signed ? bits - 1n : bits)))
      throw new RangeError(`${signed ? "int" : "uint"}${bits} required`);
    const data = new Uint8Array(width);
    for (let i = 0; i < width; ++i) data[i] = Number((n >> BigInt(i * 8)) & 255n);
    return data;
  }
  const codecToken = Symbol("codec");
  class Codec {
    #config; #kind; #closed = false;
    constructor(token, config) {
      if (token !== codecToken) throw new TypeError("use Codec factories");
      this.#kind = config[0]; this.#config = pointers(config);
    }
    static builtin(name) {
      const kind = ["uint8", "uint16-be", "uint16-le", "uint32-be", "uint32-le", "int64-minimal-be", "bytes", "ipv4", "ipv4-list"].indexOf(name);
      if (kind < 0) throw new TypeError("unknown generic codec");
      return new Codec(codecToken, [kind, 0, 0, 0, 0, 0, 0xffffffff, 0, 0]);
    }
    static number({ encoding = "big", width = 0, digits = 0 } = {}) {
      const kind = ["big", "little", "bcd"].indexOf(encoding);
      if (kind < 0) throw new TypeError("big, little or bcd encoding required");
      return new Codec(codecToken, [9, kind, size(width), size(digits), 0, 0, 0xffffffff, 0, 0]);
    }
    static schemaNumber({ min_length = 0, max_length = 0xffffffff, length_multiple = 0, endpoints = false, ...number } = {}) {
      const codec = Codec.number(number);
      codec.#kind = 12;
      const view = new DataView(codec.#config.buffer);
      [12, view.getUint32(4, true), view.getUint32(8, true), view.getUint32(12, true), 0,
        size(min_length), size(max_length), flag(endpoints), size(length_multiple)]
        .forEach((value, index) => view.setUint32(index * 4, value, true));
      return codec;
    }
    static digits({ width = 0 } = {}) { return new Codec(codecToken, [10, 0, size(width), 0, 0, 0, 0xffffffff, 0, 0]); }
    static text({ alphabet = "printable", width = 0, zero_padding = false } = {}) {
      const kind = ["printable", "alnum"].indexOf(alphabet);
      if (kind < 0) throw new TypeError("printable or alnum alphabet required");
      return new Codec(codecToken, [11, kind, size(width), 0, flag(zero_padding), 0, 0xffffffff, 0, 0]);
    }
    #input(value) {
      if (this.#kind <= 5 || this.#kind === 9 || this.#kind === 12)
        return integerBytes(value, this.#kind === 0 ? 1 : this.#kind <= 2 ? 2 : this.#kind <= 4 ? 4 : 8, this.#kind === 5);
      if (this.#kind === 10 || this.#kind === 11) {
        if (typeof value !== "string") throw new TypeError("string required");
        return encoder.encode(value);
      }
      return bytes(value);
    }
    #run(operation, input, capacity = 0xffffffff, index = 0) {
      if (this.#closed) throw new QueryError(INVALID_STATE);
      return temporaries([this.#config, input], ([config, data]) =>
        codecReply(wasm._opentlv_wasm_codec(config, operation, data, input.length, size(capacity), size(index))));
    }
    decode(input) {
      const reply = this.#run(0, bytes(input));
      if (this.#kind === 5 || this.#kind === 9 || this.#kind === 12) return BigInt(reply.value);
      if (this.#kind <= 4 || this.#kind === 10) return reply.value;
      const value = unhex(reply.value);
      return this.#kind === 11 ? decoder.decode(value) : value;
    }
    encode(value, { capacity = 0xffffffff } = {}) { return unhex(this.#run(1, this.#input(value), capacity).value); }
    measure(value) { return this.#run(2, this.#input(value)).size; }
    at(input, index) {
      if (this.#kind !== 8) throw new TypeError("IPv4 list codec required");
      return unhex(this.#run(3, bytes(input), 0, index).value);
    }
    close() { this.#closed = true; }
  }
  const structureSchemaHandles = new WeakMap();
  class StructureCodec {
    #owner; #schema; #decode; #encode; #limits; #busy = false; #closed = false;
    constructor({ format = "ber", schema, max_depth = 64, max_elements = 65536, decode, encode } = {}) {
      if (decode !== undefined && typeof decode !== "function" || encode !== undefined && typeof encode !== "function")
        throw new TypeError("synchronous codec callbacks required");
      this.#decode = decode; this.#encode = encode;
      this.#limits = [size(max_depth), size(max_elements)];
      this.#owner = new QueryProgram("//*", { format });
      try { if (schema !== undefined) this.#schema = new Schema(schema, { format }); }
      catch (error) { this.#owner.close(); throw error; }
    }
    #run(operation, input, capacity = 0xffffffff) {
      const config = pointers([operation, ...this.#limits, size(capacity)]);
      return this.#owner._native(() => temporaries([config, input], ([p, data]) =>
        unhex(codecReply(wasm._opentlv_wasm_structure_codec(this.#owner._pointer,
          this.#schema ? structureSchemaHandles.get(this.#schema) : 0, p, data, input.length)).value)));
    }
    #enter(run) {
      if (this.#closed || this.#busy || this.#owner._formatOwner._active) throw new QueryError(INVALID_STATE);
      this.#busy = true;
      try { return run(); } finally { this.#busy = false; }
    }
    decode(input) {
      return this.#enter(() => {
        if (!this.#decode) throw new CodecError({ code: UNSUPPORTED });
        const value = this.#decode(this.#run(0, bytes(input)));
        if (value && typeof value.then === "function") throw new TypeError("synchronous codec callback required");
        return value;
      });
    }
    encode(value, { capacity = 0xffffffff } = {}) {
      return this.#enter(() => {
        if (!this.#encode) throw new CodecError({ code: UNSUPPORTED });
        return this.#run(1, bytes(this.#encode(value)).slice(), capacity);
      });
    }
    measure(value) { return this.encode(value).length; }
    close() {
      if (this.#busy || this.#owner._formatOwner._active) throw new QueryError(INVALID_STATE);
      if (this.#closed) return;
      this.#schema?.close(); this.#owner.close(); this.#closed = true;
    }
  }
  class Generator {
    #owner; #config; #candidates; #closed = false; #busy = false; #workspaceSize; #version;
    constructor({ format = "ber", candidates, seed = 0n, max_elements = 64, max_depth = 8,
                  max_value_size = 256, max_case_size = 4096 } = {}) {
      if (!Array.isArray(candidates)) throw new TypeError("ordered candidates required");
      this.#candidates = candidates.map(({ tag, min_value_size = 0, max_value_size: max = max_value_size }) =>
        ({ tag: tag === null ? null : bytes(tag).slice(), min: size(min_value_size), max: size(max) }));
      const seedBytes = integerBytes(seed), seedView = new DataView(seedBytes.buffer);
      this.#config = [seedView.getUint32(0, true), seedView.getUint32(4, true), 0, 0,
        size(max_elements), size(max_depth), size(max_value_size), size(max_case_size)];
      this.#owner = new QueryProgram("//*", { format });
      try { const reply = this.#run(0n, true); this.#workspaceSize = reply.workspaceSize; this.#version = reply.version; }
      catch (error) { this.#owner.close(); throw error; }
    }
    #run(case_index, measure) {
      if (this.#closed || this.#busy || this.#owner._formatOwner._active) throw new QueryError(INVALID_STATE);
      const index = new DataView(integerBytes(case_index).buffer);
      const config = [...this.#config]; config[2] = index.getUint32(0, true); config[3] = index.getUint32(4, true);
      this.#busy = true;
      try {
        return this.#owner._native(() => temporaries(this.#candidates.map(c => c.tag ?? new Uint8Array()), tags => {
          const entries = this.#candidates.flatMap((c, i) => [c.tag === null ? 0 : tags[i], c.tag?.length ?? 0, c.min, c.max]);
          return temporaries([pointers(config), pointers(entries)], ([p, e]) =>
            dsReply(wasm._opentlv_wasm_generate(this.#owner._pointer, p, e, tags.length, Number(measure))));
        }));
      } finally { this.#busy = false; }
    }
    get workspaceSize() { if (this.#closed) throw new QueryError(INVALID_STATE); return this.#workspaceSize; }
    get version() { if (this.#closed) throw new QueryError(INVALID_STATE); return this.#version; }
    generate(case_index = 0n) { return unhex(this.#run(case_index, false).value); }
    close() {
      if (this.#busy || this.#owner._formatOwner._active) throw new QueryError(INVALID_STATE);
      if (this.#closed) return;
      this.#owner.close(); this.#closed = true;
    }
  }
  // END codecs-generator #6
  // BEGIN generic-completion #7
  class ConstraintError extends Error {
    constructor(code) {
      super(wasm.UTF8ToString(wasm._opentlv_wasm_strerror(code)));
      this.name = "ConstraintError"; this.code = code;
    }
  }
  const constraintToken = Symbol("constraint");
  class ValueConstraint {
    #kind; #values; #names; #closed = false;
    constructor(token, kind, min, max, entries) {
      if (token !== constraintToken) throw new TypeError("use ValueConstraint factories");
      this.#kind = kind;
      this.#values = new Uint8Array((3 + entries.length) * 8);
      [min, max, 0, ...entries.map(entry => entry.value)].forEach((value, index) =>
        this.#values.set(integerBytes(value, 8, true), index * 8));
      this.#names = entries.map(entry => entry.name == null ? null : string(entry.name));
      this.#run(0, 0);
    }
    static none() { return new ValueConstraint(constraintToken, 0, 0, 0, []); }
    static range(min, max) { return new ValueConstraint(constraintToken, 1, min, max, []); }
    static allowed(entries) {
      if (!Array.isArray(entries)) throw new TypeError("allowed value entries required");
      return new ValueConstraint(constraintToken, 2, 0, 0, entries);
    }
    #run(operation, value) {
      if (this.#closed) throw new QueryError(INVALID_STATE);
      const values = this.#values.slice(); values.set(integerBytes(value, 8, true), 16);
      return temporaries([values, ...this.#names.map(name => name ?? new Uint8Array())], addresses =>
        temporary(pointers(addresses.slice(1).map((p, i) => this.#names[i] === null ? 0 : p)), names => {
          const reply = dsReply(wasm._opentlv_wasm_constraint(this.#kind, operation, addresses[0], this.#names.length, names), true);
          if (reply.code) throw new ConstraintError(reply.code);
          return reply.name;
        }));
    }
    validate(value) { this.#run(1, value); }
    name(value) { return this.#run(2, value); }
    close() { this.#closed = true; this.#values = null; this.#names = null; }
  }
  function tagOperation(operation, left, right) {
    bytes(left); bytes(right);
    return temporaries([left, right], ([a, b]) =>
      dsReply(wasm._opentlv_wasm_tag_operation(operation, a, left.length, b, right.length)).value);
  }
  const Tag = Object.freeze({
    compare: (left, right) => tagOperation(0, left, right),
    equal: (left, right) => tagOperation(0, left, right) === 0,
    hash: tag => tagOperation(1, tag, new Uint8Array()),
  });
  // END generic-completion #7
  return { ValueConstraint, ConstraintError, Tag, Codec, CodecError, StructureCodec, Generator, Schema, SchemaError, DocumentBuilder, Reader, TreeReader, Writer, TreeWriter, StreamError, StreamResult, Visit, QueryProgram, QueryExecution, QuerySchema, QueryError, Document, Node, Format, Field, FormatError, V1Query, nameResolver, definitionResolver,
    compileQuery: (text, options) => new QueryProgram(text, options),
    loadQuery: (image, options) => QueryProgram.load(image, options),
    querySchema: (rules, options) => new QuerySchema(rules, options),
    document: (input, options) => new Document(input, options) };
}
