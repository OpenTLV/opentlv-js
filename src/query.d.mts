// SPDX-License-Identifier: MIT
// Copyright (c) 2026 OpenTLV
/** Types are exported only at compile time. Runtime constructors belong to the loaded API. */
export type Integer = number | bigint;
export type Scalar = boolean | Integer | string | Uint8Array;
export interface Owned { close(): void }
export type FormatName = 'ber' | 'der' | 'cer' | 'fixed' | 'bluetooth-ltv' | 'bluetooth-ad' | 'lldp' | 'emv' | 'nfc-type2';
export type FormatInput = FormatName | Format;
export interface Location { domain: string; kind: string; begin?: number; end?: number }
export interface Diagnostic {
  message?: string; expected?: string; path?: string[]; path_omitted?: number;
  location?: Location; [key: string]: unknown;
}
export interface QueryError extends Error {
  code: number; query: Readonly<Diagnostic>; applied: number; rule: number | null;
  schema: Readonly<Diagnostic> | null; location: Readonly<Location>;
}
export interface SchemaDiagnostic {
  code: number; cause: string; diagnostic: Diagnostic;
  reader?: Diagnostic; schema?: Diagnostic | null;
}
export interface SchemaError extends Omit<Error, 'cause'>, SchemaDiagnostic {
  schema: Diagnostic | null; diagnostics: SchemaDiagnostic[];
}
export interface DocumentOptions { format?: FormatInput; retain_source_locations?: boolean; max_depth?: number; max_elements?: number }
export interface Document extends Owned {
  readonly first: Node | null; readonly count: number; readonly revision: bigint; readonly retireEpoch: bigint;
  insert(tag: Uint8Array, value?: Uint8Array, options?: { parent?: Node | null; before?: Node | null }): Node;
  find(tag: Uint8Array, parent?: Node | null): Node | null;
  /** Legacy V1 path, e.g. "70/5A". */
  findPath(path: string): Node | null;
  encode(): Uint8Array; encodeAs(format: FormatInput): Uint8Array;
  encodedSize(format?: FormatInput | null): number; queryValueSize(max_depth?: number): number;
}
export interface Node {
  readonly identity: string; readonly tag: Uint8Array; readonly value: Uint8Array | null;
  readonly constructed: boolean; readonly firstChild: Node | null; readonly next: Node | null;
  readonly nextSameTag: Node | null; readonly parent: Node | null;
  readonly sourceLocation: Readonly<{ offset: number | null; headerSize: number | null }>;
  setValue(value: Uint8Array): void; erase(): void;
  encode(format?: FormatInput | null): Uint8Array; encodedSize(format?: FormatInput | null): number;
}
export interface InputOptions { discard?: number; final?: boolean }
export interface StreamState { consumed: number; offset: number; atEnd: boolean }
export interface DocumentBuilder extends Owned {
  setInput(input: Uint8Array, options?: InputOptions): this;
  readonly state: StreamState;
  consume(): { status: 'ok'; document: Document } | { status: 'need-more-data'; document: null };
}
export interface SchemaEntry {
  tag: Uint8Array; name?: string; min_length?: number; max_length?: number;
  length_multiple?: number; endpoints?: boolean;
}
export interface SchemaRule extends SchemaEntry {
  min_occurs?: number; max_occurs?: number; kind?: 'any' | 'primitive' | 'constructed';
  children?: SchemaTable; group?: number;
}
export interface SchemaTable {
  rules: readonly SchemaRule[]; allow_unknown?: boolean; order?: 'any' | 'sequence';
  groups?: readonly { id: number; name?: string; min_occurs?: number; max_occurs?: number }[];
}
export interface SchemaOptions {
  max_depth?: number; max_elements?: number; capacity?: number; unknown?: 'schema' | 'allow' | 'reject';
}
export interface Schema extends Owned {
  validate(input: Uint8Array, options?: SchemaOptions): void;
  /** Throws SchemaError with copied diagnostics when any violation is reported. */
  validateAll(input: Uint8Array, options?: SchemaOptions): SchemaDiagnostic[];
  find(tag: Uint8Array, table?: number): Required<SchemaEntry> | null;
  validateLength(tag: Uint8Array, length: number, table?: number): void;
}
export interface QueryOptions {
  format?: FormatInput; optimize?: boolean; max_text?: number; max_tokens?: number; max_nesting?: number;
  max_states?: number; max_pattern?: number; max_resolved_tag?: number;
  variables?: Record<string, 'integer' | 'bytes' | 'string'>; names?: Record<string, Uint8Array>;
  resolve?: 'emv' | ((scope: string, name: string) => Uint8Array | null);
  tags?: { id: number; classOf?: (tag: Uint8Array) => Integer; numberOf?: (tag: Uint8Array) => Integer };
  providers?: Partial<Record<'num' | 'bcd' | 'text' | 'date', {
    id: number; max_result_bytes?: number;
    decode: (value: Uint8Array, event: ProviderEvent | null) => Integer | string;
  }>>;
}
export interface ProviderEvent { kind: number; depth: number; offset: number; tag: Uint8Array; value: Uint8Array }
export interface ExecutionOptions { max_depth?: number; max_nodes?: number; max_work?: number; retained?: boolean }
export interface EvaluationOptions extends ExecutionOptions { bindings?: Record<string, Integer | string | Uint8Array>; value_capacity?: number | null; context?: Node | null }
export type EditKind = 'remove' | 'replace' | 'insert_after';
export interface EditOptions extends EvaluationOptions { tag?: Uint8Array; value?: Uint8Array; target_capacity?: number }
export interface Match { readonly offset: number; readonly depth: number; readonly constructed: boolean; readonly tag: Uint8Array; readonly value: Uint8Array }
export interface QueryProgram extends Owned {
  readonly info: Readonly<{ result_kind: number; constructed_values_required: number; [key: string]: unknown }>;
  readonly variables: Readonly<Record<string, 'integer' | 'bytes' | 'string'>>;
  format(): string; explain(): string; image(): Uint8Array;
  execution(options?: ExecutionOptions): QueryExecution;
  evaluate(input: Uint8Array, options?: EvaluationOptions): Scalar | Match[];
  evaluateDocument(document: Document, options?: EvaluationOptions): Scalar | Node[];
  editDocument(document: Document, kind: EditKind, options?: EditOptions): number;
}
export interface QueryExecution extends Owned, Iterable<Node | Match> {
  reset(): this; setInput(input: Uint8Array, options?: InputOptions): this;
  bind(name: string, value: Integer | string | Uint8Array): this; context(ordinal: number): this;
  pruning(enabled?: boolean): this; exists(options?: { early_return?: boolean }): boolean;
  readonly info: Readonly<{ elements: number; work: number; finished: number; full_validation: number; invalid: number; skipped_subtrees: number }>;
  finish(): this; result(): Scalar;
  feed(event: { kind: 'begin' | 'element' | 'end'; tag?: Uint8Array; value?: Uint8Array; source?: Uint8Array | null; depth?: number; offset?: number; skipped?: boolean }): Match | null;
  nextOrdinal(): Readonly<{ ordinal: number; match: Match }> | null;
  next(): Node | Match | null;
  visit(callback: (match: Node | Match) => void | boolean): void;
  evaluateDocument(document: Document, options?: { value_capacity?: number | null; context?: Node | null }): this;
  editDocument(kind: EditKind, options?: EditOptions): number;
}
export interface QuerySchemaOptions extends ExecutionOptions { max_contexts?: number; value_capacity?: number | null }
export interface QuerySchema extends Owned {
  validateBuffer(input: Uint8Array, options?: QuerySchemaOptions): void;
  validateDocument(document: Document, options?: QuerySchemaOptions): void;
}
export interface QueryRule { context: QueryProgram; assertion: QueryProgram; name?: string }
export interface V1Query extends Owned {
  format(): string; readonly steps: Uint8Array[]; matcher(): V1Query;
  feed(tag: Uint8Array, depth?: number): boolean; reset(): this;
  evaluate(input: Uint8Array, options?: QueryOptions): Scalar | Match[];
}
export interface Element { tag: Uint8Array; value?: Uint8Array | null; valueSize?: Integer }
export interface ByteRange { offset: number; size: number }
export interface Decoded { tag: Uint8Array; header: ByteRange; value: ByteRange; trailer?: ByteRange; tagRange?: ByteRange | null; lengthRange?: ByteRange | null }
export interface FormatOptions {
  tag_size?: number; length_size?: number; byte_order?: 'big' | 'little';
  element_order?: 'tlv' | 'ltv'; length_scope?: 'value' | 'tag-and-value';
  isConstructed?: (tag: Uint8Array) => boolean;
}
export interface CustomFormatOptions extends FormatOptions {
  decode: (input: Uint8Array) => Decoded | { code: number };
  measure?: (element: Element) => { header: number; value?: number; trailer?: number } | { code: number };
  encode?: (element: Element) => Uint8Array | { code: number };
}
export interface Format extends Owned {
  readonly canRead: boolean; readonly canWrite: boolean;
  decode(input: Uint8Array): Record<string, unknown>;
  measure(element: Element): Record<string, Integer>;
  encode(element: Element): Uint8Array; preserve(input: Uint8Array, element: Element): Uint8Array;
}
export interface Field extends Owned {
  read(input: Uint8Array): { consumed: number; tag: Uint8Array } | { consumed: number; value: Integer };
  encode(value: Uint8Array | Integer, storage?: Uint8Array): Uint8Array;
}
export interface StreamOptions extends DocumentOptions {
  incremental?: boolean; frame_capacity?: number; scratch_capacity?: number; tag_capacity?: number; capacity?: number;
}
export interface StreamItem { tag: Uint8Array | null; value: Uint8Array; depth?: number; offset?: number; constructed?: boolean; encoded?: Uint8Array; kind?: 'begin' | 'element' | 'end'; skipped?: boolean }
export interface StreamReply { status: 'ok' | 'end' | 'need-more-data'; code: number; item: StreamItem | null; consumed: number; offset: number; atEnd: boolean }
export interface Reader extends Owned {
  next(): StreamReply; readonly state: StreamState; setInput(input: Uint8Array, options?: InputOptions): void;
  reset(input?: Uint8Array, options?: { incremental?: boolean }): void;
  visit(visitor: (item: StreamItem) => 0 | 1 | 2): StreamReply;
}
export interface TreeReader extends Reader { nextEvent(): StreamReply; skipSubtree(): StreamReply }
export interface Writer extends Owned {
  write(element: Element): void; measure(element: Element): number;
  readonly bytes: Uint8Array; readonly size: number; readonly remaining: number;
  copyEncoded(encoded: Uint8Array): void; preserve(source: StreamItem, element?: Element): void;
}
export interface TreeWriter extends Omit<Writer, 'copyEncoded' | 'preserve'> {
  begin(tag: Uint8Array): void; end(): void; finish(): Uint8Array; writeEvent(event: StreamItem): void;
}
export interface QueryAPI {
  Document: { new(input: Uint8Array | null, options?: DocumentOptions): Document; create(options?: DocumentOptions): Document };
  /** Obtain Nodes from a Document or Query selection. */
  Node: { readonly prototype: Node };
  DocumentBuilder: new(input?: Uint8Array, options?: StreamOptions) => DocumentBuilder;
  Schema: new(definition: SchemaTable, options?: { format?: FormatInput }) => Schema;
  SchemaError: { readonly prototype: SchemaError; new(reply: Record<string, unknown>): SchemaError };
  QueryError: { readonly prototype: QueryError; new(code: number): QueryError };
  QueryProgram: { new(text: string, options?: QueryOptions): QueryProgram; load(image: Uint8Array, options?: QueryOptions): QueryProgram };
  QueryExecution: new(program: QueryProgram, options?: ExecutionOptions) => QueryExecution;
  QuerySchema: new(rules: readonly QueryRule[], options?: { format?: FormatInput }) => QuerySchema;
  V1Query: new(text: string) => V1Query;
  compileQuery(text: string, options?: QueryOptions): QueryProgram;
  loadQuery(image: Uint8Array, options?: QueryOptions): QueryProgram;
  querySchema(rules: readonly QueryRule[], options?: { format?: FormatInput }): QuerySchema;
  document(input: Uint8Array | null, options?: DocumentOptions): Document;
  nameResolver(names: Record<string, Uint8Array>): (scope: string, name: string) => Uint8Array | null;
  definitionResolver(scopes: Record<string, readonly { name: string; tag: Uint8Array }[]>): (scope: string, name: string) => Uint8Array | null;
  Format: {
    new(name?: FormatName, options?: FormatOptions): Format;
    fixed(options?: FormatOptions): Format; custom(options: CustomFormatOptions): Format;
    compose(identifier: Field, length: Field, options?: Record<string, unknown>): Format;
    variable(options?: Record<string, unknown>): Format; escaped(options?: Record<string, unknown>): Format;
    packed(options?: Record<string, unknown>): Format;
  };
  Field: {
    fixedIdentifier(width?: number): Field; variableIdentifier(options?: Record<string, unknown>): Field;
    fixedLength(width?: number, order?: 'big' | 'little'): Field; variableLength(options?: Record<string, unknown>): Field;
    escapedLength(options?: Record<string, unknown>): Field; packed(options?: Record<string, unknown>): Field;
  };
  Reader: { new(input?: Uint8Array, options?: StreamOptions): Reader; read(input: Uint8Array, options?: StreamOptions): StreamReply };
  TreeReader: new(input?: Uint8Array, options?: StreamOptions) => TreeReader;
  Writer: { new(options?: StreamOptions): Writer; encode(element: Element, options?: StreamOptions): Uint8Array };
  TreeWriter: { new(options?: StreamOptions): TreeWriter; measure(items: readonly StreamItem[], options?: StreamOptions): { size: number; bytes: Uint8Array }; measureEvents(events: readonly StreamItem[], options?: StreamOptions): { size: number; bytes: Uint8Array } };
  FormatError: new(code: number) => Error & { code: number };
  StreamError: new(code: number) => Error & { code: number; diagnostic?: Diagnostic; reader?: Diagnostic; writer?: Diagnostic };
  StreamResult: Readonly<Record<string, number>>; Visit: Readonly<{ CONTINUE: 0; STOP: 1; ERROR: 2 }>;
}
export function queryFacade(wasm: unknown): QueryAPI;
