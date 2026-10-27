// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const { loadOpenTLV, hexToBytes } = await import(pathToFileURL(resolve(process.argv[2], 'opentlv.mjs')));
const { Codec, Generator } = await loadOpenTLV();
const amount = Codec.schemaNumber({ encoding: 'bcd', digits: 12, min_length: 6, max_length: 6 });
const generator = new Generator({ seed: 42n, candidates: [{ tag: hexToBytes('04') }], max_case_size: 128 });
try {
  const encoded = amount.encode(12345n);
  console.log('BCD amount:', Buffer.from(encoded).toString('hex'), amount.decode(encoded));
  console.log('Wire case 7:', Buffer.from(generator.generate(7n)).toString('hex'));
} finally { amount.close(); generator.close(); }
