// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel
import type { ModuleOptions } from './dist/opentlv.mjs';
/** Low-level Emscripten module; prefer `loadOpenTLV()` unless the C bridge is required. */
export interface OpenTLVModule {
  readonly HEAPU8: Uint8Array;
  UTF8ToString(pointer: number, maxBytes?: number): string;
  stringToUTF8(text: string, pointer: number, maxBytes: number): void;
  lengthBytesUTF8(text: string): number;
  addFunction(callback: (...args: never[]) => unknown, signature?: string): number;
  removeFunction(pointer: number): void;
  [entry: `_opentlv_wasm_${string}`]: (...args: (number | bigint)[]) => number;
}
export default function createOpenTLV(moduleOptions?: ModuleOptions): Promise<OpenTLVModule>;
