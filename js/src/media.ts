import { ConfigError } from "./errors.js";

/**
 * An image or WAV clip:
 * - `Uint8Array` / `ArrayBuffer` / any `ArrayBufferView` (Node `Buffer` included)
 * - `Blob` / `File`
 * - a base64 string or `data:...;base64,` URL
 * - a file path string (Node, Bun and Deno only; loaded with a dynamic `node:fs` import)
 * - `{ path }` or `{ base64 }` to skip the string guesswork
 */
export type MediaInput =
  | Uint8Array
  | ArrayBuffer
  | ArrayBufferView
  | Blob
  | string
  | { path: string }
  | { base64: string };

export type ImageMime = "image/jpeg" | "image/png";

const B64_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
const B64_LOOKUP = (() => {
  const table = new Int16Array(128).fill(-1);
  for (let i = 0; i < B64_CHARS.length; i++) table[B64_CHARS.charCodeAt(i)] = i;
  // accept URL-safe base64 too
  table["-".charCodeAt(0)] = 62;
  table["_".charCodeAt(0)] = 63;
  return table;
})();

export function bytesToBase64(bytes: Uint8Array): string {
  let out = "";
  const len = bytes.length;
  let i = 0;
  // build in chunks so huge images don't create millions of tiny strings
  const parts: string[] = [];
  for (; i + 2 < len; i += 3) {
    const n = (bytes[i]! << 16) | (bytes[i + 1]! << 8) | bytes[i + 2]!;
    out +=
      B64_CHARS[(n >> 18) & 63]! +
      B64_CHARS[(n >> 12) & 63]! +
      B64_CHARS[(n >> 6) & 63]! +
      B64_CHARS[n & 63]!;
    if (out.length >= 8192) {
      parts.push(out);
      out = "";
    }
  }
  const rest = len - i;
  if (rest === 1) {
    const n = bytes[i]! << 16;
    out += B64_CHARS[(n >> 18) & 63]! + B64_CHARS[(n >> 12) & 63]! + "==";
  } else if (rest === 2) {
    const n = (bytes[i]! << 16) | (bytes[i + 1]! << 8);
    out += B64_CHARS[(n >> 18) & 63]! + B64_CHARS[(n >> 12) & 63]! + B64_CHARS[(n >> 6) & 63]! + "=";
  }
  parts.push(out);
  return parts.join("");
}

/** Decode standard or URL-safe base64 (whitespace and missing padding are tolerated). */
export function base64ToBytes(input: string): Uint8Array {
  const clean = input.replace(/[\s=]+/g, "");
  if (clean.length % 4 === 1) throw new ConfigError("invalid base64");
  const out = new Uint8Array(Math.floor((clean.length * 3) / 4));
  let buffer = 0;
  let bits = 0;
  let o = 0;
  for (let i = 0; i < clean.length; i++) {
    const code = clean.charCodeAt(i);
    const v = code < 128 ? B64_LOOKUP[code]! : -1;
    if (v < 0) throw new ConfigError("invalid base64");
    buffer = (buffer << 6) | v;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out[o++] = (buffer >> bits) & 0xff;
    }
  }
  return out.subarray(0, o);
}

const BASE64_RE = /^[A-Za-z0-9+/_-]+={0,2}$/;

/** PNG or JPEG from magic bytes, else `undefined`. */
export function detectImageMime(bytes: Uint8Array): ImageMime | undefined {
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
    return "image/jpeg";
  }
  if (
    bytes.length >= 8 &&
    bytes[0] === 0x89 &&
    bytes[1] === 0x50 &&
    bytes[2] === 0x4e &&
    bytes[3] === 0x47 &&
    bytes[4] === 0x0d &&
    bytes[5] === 0x0a &&
    bytes[6] === 0x1a &&
    bytes[7] === 0x0a
  ) {
    return "image/png";
  }
  return undefined;
}

/** `RIFF....WAVE` header. */
export function isWav(bytes: Uint8Array): boolean {
  return (
    bytes.length >= 12 &&
    bytes[0] === 0x52 &&
    bytes[1] === 0x49 &&
    bytes[2] === 0x46 &&
    bytes[3] === 0x46 &&
    bytes[8] === 0x57 &&
    bytes[9] === 0x41 &&
    bytes[10] === 0x56 &&
    bytes[11] === 0x45
  );
}

function looksLikeMedia(bytes: Uint8Array): boolean {
  if (detectImageMime(bytes) || isWav(bytes)) return true;
  // GIF / WebP: `ifseen serve` accepts anything Pillow reads
  const head = String.fromCharCode(...bytes.subarray(0, 12));
  return head.startsWith("GIF8") || (head.startsWith("RIFF") && head.slice(8, 12) === "WEBP");
}

/** Width and height from a PNG or JPEG header, or `undefined` if it can't be read. */
export function imageSize(bytes: Uint8Array): { width: number; height: number } | undefined {
  const mime = detectImageMime(bytes);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (mime === "image/png") {
    if (bytes.length < 24) return undefined;
    return { width: view.getUint32(16), height: view.getUint32(20) };
  }
  if (mime === "image/jpeg") {
    let i = 2;
    while (i + 9 < bytes.length) {
      if (bytes[i] !== 0xff) {
        i++;
        continue;
      }
      const marker = bytes[i + 1]!;
      if (marker === 0xff) {
        i++; // fill byte
        continue;
      }
      if (marker === 0xd8 || marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) {
        i += 2; // standalone markers
        continue;
      }
      const length = view.getUint16(i + 2);
      // SOF0-15 except DHT (C4), JPG (C8) and DAC (CC)
      if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
        return { height: view.getUint16(i + 5), width: view.getUint16(i + 7) };
      }
      if (marker === 0xda || marker === 0xd9) return undefined; // start of scan / end
      i += 2 + length;
    }
  }
  return undefined;
}

interface FsPromises {
  readFile(path: string): Promise<Uint8Array>;
}

async function readFile(path: string): Promise<Uint8Array> {
  let fs: FsPromises;
  try {
    // A variable specifier keeps browser bundlers from trying to resolve node:fs.
    const specifier = "node:fs/promises";
    fs = (await import(/* @vite-ignore */ /* webpackIgnore: true */ specifier)) as FsPromises;
  } catch (e) {
    throw new ConfigError(
      "file paths need a runtime with node:fs (Node, Bun or Deno); pass bytes, a Blob or base64 instead",
      { cause: e },
    );
  }
  try {
    const data = await fs.readFile(path);
    return new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  } catch (e) {
    const code = (e as { code?: string }).code;
    if (code === "ENOENT") throw new ConfigError(`no such file: ${path}`, { cause: e });
    throw new ConfigError(`could not read ${path}`, { cause: e });
  }
}

function decodeDataUrl(value: string): Uint8Array {
  const comma = value.indexOf(",");
  if (comma < 0 || !value.slice(0, comma).includes(";base64")) {
    throw new ConfigError("only base64 data: URLs are supported");
  }
  return base64ToBytes(value.slice(comma + 1));
}

/**
 * A string is treated as base64 when it only has base64 characters and decodes to a known
 * image / WAV header; anything else is a file path. Use `{ path }` / `{ base64 }` to be explicit.
 */
function stringToBytes(value: string): Uint8Array | undefined {
  if (value.startsWith("data:")) return decodeDataUrl(value);
  const compact = value.replace(/\s+/g, "");
  if (compact.length >= 16 && BASE64_RE.test(compact)) {
    try {
      const bytes = base64ToBytes(compact);
      if (looksLikeMedia(bytes)) return bytes;
    } catch {
      // not base64: fall through to a path
    }
  }
  return undefined;
}

/** Normalise any {@link MediaInput} to bytes. */
export async function toBytes(input: MediaInput): Promise<Uint8Array> {
  if (input instanceof Uint8Array) {
    // Node Buffers are Uint8Array subclasses; hand back a plain view
    return input.constructor === Uint8Array ? input : new Uint8Array(input.buffer, input.byteOffset, input.byteLength);
  }
  if (input instanceof ArrayBuffer) return new Uint8Array(input);
  if (ArrayBuffer.isView(input)) {
    return new Uint8Array(input.buffer, input.byteOffset, input.byteLength);
  }
  if (typeof Blob !== "undefined" && input instanceof Blob) {
    return new Uint8Array(await input.arrayBuffer());
  }
  if (typeof input === "string") {
    if (!input) throw new ConfigError("empty media string");
    return stringToBytes(input) ?? (await readFile(input));
  }
  if (input && typeof input === "object") {
    if ("base64" in input && typeof input.base64 === "string") {
      return input.base64.startsWith("data:") ? decodeDataUrl(input.base64) : base64ToBytes(input.base64);
    }
    if ("path" in input && typeof input.path === "string") return readFile(input.path);
  }
  throw new ConfigError("unsupported media input: pass bytes, a Blob, base64 or a file path");
}

/** Bytes plus the detected MIME type; throws unless it's a JPEG or PNG. */
export async function loadImage(input: MediaInput): Promise<{ bytes: Uint8Array; mime: ImageMime }> {
  const bytes = await toBytes(input);
  const mime = detectImageMime(bytes);
  if (!mime) {
    throw new ConfigError(
      "could not read the image: only JPEG and PNG are supported for direct checks " +
        "(ifseen serve accepts any format Pillow reads)",
    );
  }
  return { bytes, mime };
}

export async function loadWav(input: MediaInput): Promise<Uint8Array> {
  const bytes = await toBytes(input);
  if (!isWav(bytes)) throw new ConfigError("audio must be a PCM WAV file");
  return bytes;
}
