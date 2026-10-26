import { loadOpenTLV, hexToBytes, packageVersion } from 'opentlv-js';
import type { Document, Node, SchemaTable, QueryAPI, Scalar } from 'opentlv-js';
import { loadOpenTLV as direct } from 'opentlv-js/opentlv.mjs';
import { queryFacade } from 'opentlv-js/query.mjs';
import { packageVersion as version } from 'opentlv-js/version';
const api = await loadOpenTLV();
const same: typeof loadOpenTLV = direct;
const factory: (module: unknown) => QueryAPI = queryFacade;
const versions: string[] = [packageVersion, version];
void same; void factory; void versions;
const document: Document = api.Document.create();
const node: Node = document.insert(hexToBytes('5A'), hexToBytes('01'));
const size: number = node.encodedSize();
const revision: bigint = document.revision;
const offset: number | null = node.sourceLocation.offset;
void size; void revision; void offset;
const rules: SchemaTable = { rules: [{ tag: node.tag, min_occurs: 1, max_length: 1, kind: 'primitive' }] };
const schema = new api.Schema(rules);
schema.validate(document.encode());
schema.validateAll(document.encode(), { unknown: 'reject', capacity: 8 });
const query = api.compileQuery('//5A');
const selection: Scalar | Node[] = query.evaluateDocument(document);
void selection;
query.editDocument(document, 'replace', { value: hexToBytes('02') });
const builder = new api.DocumentBuilder(new Uint8Array(), { incremental: true });
const result = builder.consume();
if (result.status === 'ok') result.document.encode();
else { const absent: null = result.document; void absent; }
// @ts-expect-error bytes are required
document.insert('5A');
// @ts-expect-error only the supported edit operations are accepted
query.editDocument(document, 'append');
// @ts-expect-error occurrence limits are numbers
new api.Schema({ rules: [{ tag: node.tag, min_occurs: '1' }] });
// @ts-expect-error Node handles are obtained from a Document
new api.Node();
// @ts-expect-error context is an ordinal, not a Node
query.execution().context(node);
schema.close(); builder.close(); query.close(); document.close();
const integerCodec = api.Codec.number({ encoding: 'bcd', digits: 12 });
const integer: bigint = integerCodec.decode(integerCodec.encode(123n));
const byteCodec = api.Codec.builtin('uint8');
const byte: number = byteCodec.decode(byteCodec.encode(255));
const ip: Uint8Array = api.Codec.builtin('ipv4-list').at(hexToBytes('C0000201'), 0);
const text: string = api.Codec.text().decode(hexToBytes('41'));
const objectCodec = new api.StructureCodec<{ id: number }>({
  decode: data => ({ id: data[2]! }), encode: value => Uint8Array.of(4, 1, value.id),
});
const object: { id: number } = objectCodec.decode(objectCodec.encode({ id: 7 }));
const generator = new api.Generator({ candidates: [{ tag: hexToBytes('04') }], seed: (1n << 64n) - 1n });
const wire: Uint8Array = generator.generate(7n);
void integer; void byte; void ip; void text; void object; void wire;
// @ts-expect-error typed numeric codec does not accept a string
integerCodec.encode('123');
// @ts-expect-error text codec requires text
api.Codec.text().encode(1);
// @ts-expect-error explicit ordered candidate table is required
new api.Generator({ seed: 1n });
// @ts-expect-error object shape is checked
objectCodec.encode({ id: '7' });
integerCodec.close(); byteCodec.close(); objectCodec.close(); generator.close();
const constraint = api.ValueConstraint.allowed([{ value: 7n, name: 'seven' }]);
constraint.validate(7);
const label: string | null = constraint.name(7n);
const ordering: -1 | 0 | 1 = api.Tag.compare(hexToBytes('01'), hexToBytes('02'));
const equal: boolean = api.Tag.equal(new Uint8Array(), new Uint8Array());
const hash: number = api.Tag.hash(hexToBytes('9F02'));
void label; void ordering; void equal; void hash;
// @ts-expect-error constraints validate integers
constraint.validate('7');
// @ts-expect-error tags are byte arrays
api.Tag.hash('9F02');
// @ts-expect-error named values need a scalar value
api.ValueConstraint.allowed([{ name: 'seven' }]);
constraint.close();
