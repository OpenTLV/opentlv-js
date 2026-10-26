// SPDX-License-Identifier: MIT
// Copyright (c) 2026 OpenTLV
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const { loadOpenTLV, hexToBytes: hex } = await import(pathToFileURL(resolve(process.argv[2], 'opentlv.mjs')));
const api = await loadOpenTLV();
const document = api.Document.create();
const query = api.compileQuery('//5A');
const schema = new api.Schema({ rules: [{ tag: hex('5A'), min_occurs: 1, min_length: 1, max_length: 1 }] });
try {
  document.insert(hex('5A'), hex('01'));
  query.editDocument(document, 'replace', { value: hex('02') });
  const encoded = document.encode();
  schema.validate(encoded);
  console.log(Array.from(encoded, byte => byte.toString(16).padStart(2, '0')).join(''));
} finally { schema.close(); query.close(); document.close(); }
