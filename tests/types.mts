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
