// SPDX-License-Identifier: MIT
// Copyright (c) 2026 OpenTLV
import type { QueryAPI, FormatName } from './query.mjs';
export type * from './query.mjs';
export interface ModuleOptions {
  locateFile?: (name: string, directory: string) => string;
  wasmBinary?: Uint8Array | ArrayBuffer;
  [key: string]: unknown;
}
export interface ParsedElement {
  offset: number; depth: number; tag: string; length: number; headerSize: number;
  encodedSize: number; constructed: boolean; value?: string; children?: ParsedElement[];
  symbol?: string; name?: string; lengthValid?: boolean;
}
export interface ParseOptions {
  format?: FormatName; module?: 'none' | 'emv'; fixedTagSize?: number; fixedLengthSize?: number;
  fixedByteOrder?: 'big' | 'little'; fixedElementOrder?: 'tlv' | 'ltv'; fixedLengthScope?: 'value' | 'tag-and-value';
}
export interface OpenTLV extends QueryAPI {
  readonly version: string; readonly formats: readonly string[]; readonly modules: readonly string[];
  parse(bytes: Uint8Array, options?: ParseOptions): {
    format: string; module?: string; elements: ParsedElement[];
    error?: { code: number; message: string; offset: number }; padding?: { offset: number; length: number };
  };
}
export const FORMATS: readonly string[];
export const MODULES: readonly string[];
export function hexToBytes(text: string): Uint8Array;
export function loadOpenTLV(moduleOptions?: ModuleOptions): Promise<OpenTLV>;
