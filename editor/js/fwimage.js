// Firmware image checks for the browser updater (pure functions; tested in tests/editor_dsp.test.mjs).
// Mirrors tools/espimage.py: merged ESP32 image = bootloader @0x1000, partition table @0x8000, app @0x10000.

export const APP_OFFSET = 0x10000;
export const NVS_OFFSET = 0x1e0000;   // flashing must never reach the NVS partition (calibration lives there)

function parseImage(b, off) {
  if (b[off] !== 0xe9) throw new Error(`no ESP image at 0x${off.toString(16)}`);
  const dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
  const nseg = b[off + 1];
  const chip = dv.getUint16(off + 12, true);
  const hashAppended = b[off + 23] === 1;
  let p = off + 24;
  const segments = [];
  for (let i = 0; i < nseg; i++) {
    const addr = dv.getUint32(p, true), len = dv.getUint32(p + 4, true);
    segments.push({ addr, data: p + 8, len });
    p += 8 + len;
  }
  p += 15 - ((p - off) % 16);        // pad: checksum byte ends on a 16-byte boundary
  const checksumOffset = p++;
  const hashOffset = hashAppended ? p : null;
  if (hashAppended) p += 32;
  return { chip, segments, checksumOffset, hashOffset, end: p };
}

function checksumOk(b, img) {
  let c = 0xef;
  for (const s of img.segments) for (let i = s.data; i < s.data + s.len; i++) c ^= b[i];
  return b[img.checksumOffset] === c;
}

const cstr = (b, start, len) => new TextDecoder().decode(b.subarray(start, start + len)).split('\0')[0];

/** Validate a merged Laniakea firmware file. Returns {project, version, date, size, ...}; throws on problems. */
export async function inspectFirmware(bytes) {
  const b = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  if (b.length < APP_OFFSET + 64) throw new Error('file too small to be a merged firmware image');
  if (b[0] === 0xe9) throw new Error('bootloader at 0x0: this is an ESP32-S2/S3/C3 image (e.g. Laniakea Pro), not ESP32');
  const boot = parseImage(b, 0x1000);
  if (boot.chip !== 0) throw new Error('not an ESP32 image (Laniakea uses an ESP32)');
  const app = parseImage(b, APP_OFFSET);
  if (app.chip !== 0) throw new Error('application is not built for ESP32');
  if (app.end > NVS_OFFSET) throw new Error('image would overwrite the NVS (calibration) partition');
  if (!checksumOk(b, boot) || !checksumOk(b, app)) throw new Error('image checksum invalid');
  if (app.hashOffset !== null) {
    const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', b.slice(APP_OFFSET, app.hashOffset)));
    if (!digest.every((v, i) => v === b[app.hashOffset + i])) throw new Error('application SHA-256 invalid');
  }
  const d = app.segments[0].data;   // esp_app_desc_t at the start of the first DROM segment
  const dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
  if (dv.getUint32(d, true) !== 0xabcd5432) throw new Error('no application descriptor');
  const info = { version: cstr(b, d + 16, 32), project: cstr(b, d + 48, 32), time: cstr(b, d + 80, 16),
                 date: cstr(b, d + 96, 16), idf: cstr(b, d + 112, 32), size: b.length };
  if (info.project !== 'Magerit_LANIAKEA') throw new Error(`this is "${info.project}", not Laniakea firmware`);
  return info;
}

// Factory wavetable inside official images: int32[8 rows][1024] (64 waves x 128 samples, low 16 bits).
const FACTORY_TABLE = {
  '64f8ee24f19ee6085594ccb9a6d7697e7f90b7d325b4615a65651ff8a452e328': 0x3f4119fc,   // v3.6
};

/** Extract the factory bank from an official image -> Array(64) of Int16Array(128). */
export async function extractFactoryBank(bytes) {
  const b = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  const addr = FACTORY_TABLE[await sha256Hex(b)];
  if (!addr) throw new Error('unknown firmware version (factory table address only known for v3.6)');
  const app = parseImage(b, APP_OFFSET);
  const seg = app.segments.find((s) => addr >= s.addr && addr + 64 * 128 * 4 <= s.addr + s.len);
  if (!seg) throw new Error('factory table not inside the image');
  const dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
  const off = seg.data + (addr - seg.addr);
  return Array.from({ length: 64 }, (_, w) =>
    Int16Array.from({ length: 128 }, (_, i) => dv.getInt32(off + (w * 128 + i) * 4, true)));
}

export async function sha256Hex(bytes) {
  const d = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
  return Array.from(d, (x) => x.toString(16).padStart(2, '0')).join('');
}

/** MD5 (hex) - esptool-js uses it to verify what was written to flash. */
export function md5(bytes) {
  const S = [7, 12, 17, 22, 5, 9, 14, 20, 4, 11, 16, 23, 6, 10, 15, 21];
  const K = new Uint32Array(64);
  for (let i = 0; i < 64; i++) K[i] = Math.floor(Math.abs(Math.sin(i + 1)) * 2 ** 32) >>> 0;
  const len = bytes.length, total = (((len + 8) >>> 6) + 1) * 64;
  const buf = new Uint8Array(total);
  buf.set(bytes);
  buf[len] = 0x80;
  const dv = new DataView(buf.buffer);
  dv.setUint32(total - 8, (len * 8) >>> 0, true);
  dv.setUint32(total - 4, Math.floor(len / 0x20000000), true);
  let a0 = 0x67452301, b0 = 0xefcdab89, c0 = 0x98badcfe, d0 = 0x10325476;
  const M = new Uint32Array(16);
  for (let off = 0; off < total; off += 64) {
    for (let j = 0; j < 16; j++) M[j] = dv.getUint32(off + j * 4, true);
    let A = a0, B = b0, C = c0, D = d0;
    for (let i = 0; i < 64; i++) {
      let F, g;
      if (i < 16) { F = (B & C) | (~B & D); g = i; }
      else if (i < 32) { F = (D & B) | (~D & C); g = (5 * i + 1) % 16; }
      else if (i < 48) { F = B ^ C ^ D; g = (3 * i + 5) % 16; }
      else { F = C ^ (B | ~D); g = (7 * i) % 16; }
      const s = S[(i >> 4) * 4 + (i % 4)];
      F = (F + A + K[i] + M[g]) >>> 0;
      A = D; D = C; C = B;
      B = (B + ((F << s) | (F >>> (32 - s)))) >>> 0;
    }
    a0 = (a0 + A) >>> 0; b0 = (b0 + B) >>> 0; c0 = (c0 + C) >>> 0; d0 = (d0 + D) >>> 0;
  }
  return [a0, b0, c0, d0].map((x) => [0, 8, 16, 24].map((sh) => ((x >>> sh) & 255).toString(16).padStart(2, '0')).join('')).join('');
}
