// Node test for the editor's pure modules (no DOM): node tests/editor_dsp.test.mjs
import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';
import * as dsp from '../editor/js/dsp.js';
import { parseWavetable, parseSingleCycle, encodeWavetable, looksLikeBank, WAVES, LEN } from '../editor/js/wav.js';

// 1. resample a sine 600 -> 256 (AKWF size) keeps shape
const s600 = Float32Array.from({ length: 600 }, (_, i) => Math.sin((2 * Math.PI * i) / 600));
const r = dsp.resampleCycle(s600, 256);
for (let i = 0; i < 256; i++) assert.ok(Math.abs(r[i] - Math.sin((2 * Math.PI * i) / 256)) < 1e-3, `sine resample @${i}`);

// 2. every generator yields finite, normalised-ish waves
for (const [k, g] of Object.entries(dsp.gen)) {
  const w = g(256);
  assert.equal(w.length, 256, k);
  assert.ok(w.every(Number.isFinite), k);
  assert.ok(Math.max(...w.map(Math.abs)) <= 1.0001, `${k} peak`);
}

// 3. bank round trip through WAV encode/parse
const bank = [...Array(WAVES)].map((_, i) => dsp.gen.pulse(LEN, 0.05 + (0.45 * i) / 63));
const blob = encodeWavetable(bank);
const ab = await blob.arrayBuffer();
assert.equal(ab.byteLength, 44 + WAVES * LEN * 2);
assert.ok(looksLikeBank(ab));
const back = parseWavetable(ab).waves;
let maxErr = 0;
back.forEach((w, k) => w.forEach((v, i) => { maxErr = Math.max(maxErr, Math.abs(v - bank[k][i])); }));
assert.ok(maxErr < 1e-3, `round trip err ${maxErr}`);
writeFileSync(new URL('./_pwm_bank.wav', import.meta.url), Buffer.from(ab));

// 4. single-cycle WAV (AKWF-like, 600 samples 16-bit)
const one = new ArrayBuffer(44 + 600 * 2); const v = new DataView(one);
const str = (o, t) => [...t].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
str(0, 'RIFF'); v.setUint32(4, 36 + 1200, true); str(8, 'WAVE'); str(12, 'fmt '); v.setUint32(16, 16, true);
v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, 44100, true); v.setUint32(28, 88200, true);
v.setUint16(32, 2, true); v.setUint16(34, 16, true); str(36, 'data'); v.setUint32(40, 1200, true);
s600.forEach((x, i) => v.setInt16(44 + i * 2, Math.round(x * 32767), true));
assert.ok(!looksLikeBank(one));
const sc = parseSingleCycle(one);
assert.equal(sc.length, 256);
assert.ok(Math.abs(sc[64] - 1) < 2e-3, 'single cycle peak');

// 5. module format: 64 x 128 int16 within range; morph corners equal source waves
const mod = dsp.toModuleFormat(bank);
assert.equal(mod.length, 64); assert.ok(mod.every((w) => w.length === 128 && w.every((x) => Number.isInteger(x) && Math.abs(x) <= 32767)));
assert.deepEqual(Array.from(dsp.morph(bank, 3, 5)), Array.from(bank[5 * 8 + 3]));
writeFileSync(new URL('./_pwm_bank_module.json', import.meta.url), JSON.stringify(mod));
console.log('editor dsp/wav tests: OK');

// ---- firmware updater helpers (fwimage.js)
import { md5, inspectFirmware, sha256Hex } from '../editor/js/fwimage.js';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
for (const n of [0, 1, 55, 56, 63, 64, 65, 1000, 100003]) {
  const data = Uint8Array.from({ length: n }, (_, i) => (i * 7 + 3) & 255);
  assert.equal(md5(data), createHash('md5').update(data).digest('hex'), `md5 len ${n}`);
}
const fwDir = new URL('../firmware/', import.meta.url);
for (const rel of ['official/laniakea/laniakea_v3.6.bin', 'custom/laniakea_v3.6+Y-effects+leddedupe.bin']) {
  const p = new URL(rel, fwDir);
  if (!existsSync(p)) { console.log(`  (skip ${rel}: not built/downloaded)`); continue; }
  const bytes = new Uint8Array(readFileSync(p));
  const info = await inspectFirmware(bytes);
  assert.equal(info.project, 'Magerit_LANIAKEA');
  assert.equal(md5(bytes), createHash('md5').update(bytes).digest('hex'));
  assert.equal(await sha256Hex(bytes), createHash('sha256').update(bytes).digest('hex'));
  const bad = bytes.slice(); bad[0x20000] ^= 0xff;
  await assert.rejects(inspectFirmware(bad), /checksum|SHA-256/);
  console.log(`  ${rel}: version "${info.version}" OK, corruption detected`);
}
const pro = new URL('official/laniakea_pro/laniakea_pro_v1.0.bin', fwDir);
if (existsSync(pro)) await assert.rejects(inspectFirmware(new Uint8Array(readFileSync(pro))), /ESP32/);
console.log('firmware helper tests: OK');

// ---- factory bank extraction (fwimage.extractFactoryBank) vs the Python exporter's source data
import { extractFactoryBank } from '../editor/js/fwimage.js';
{
  const p = new URL('official/laniakea/laniakea_v3.6.bin', fwDir);
  if (existsSync(p)) {
    const bank = await extractFactoryBank(new Uint8Array(readFileSync(p)));
    assert.equal(bank.length, 64); assert.equal(bank[0].length, 128);
    const peak = Math.max(...bank.flatMap((w) => Array.from(w, Math.abs)));
    assert.ok(peak > 30000 && peak <= 32767, `factory peak ${peak}`);
    console.log(`  factory bank extracted: 64 x 128, peak ${peak}`);
  }
  const p37 = new URL('official/laniakea/laniakea_v3.7.bin', fwDir);
  if (existsSync(p) && existsSync(p37)) {
    const a = await extractFactoryBank(new Uint8Array(readFileSync(p)));
    const b = await extractFactoryBank(new Uint8Array(readFileSync(p37)));
    assert.ok(a.every((w, i) => w.every((v, k) => v === b[i][k])), 'v3.7 factory bank = v3.6');
    console.log('  v3.7 factory bank extracted, identical to v3.6');
  }
  const other = new URL('official/laniakea/laniakea_v3.3.bin', fwDir);
  if (existsSync(other)) await assert.rejects(extractFactoryBank(new Uint8Array(readFileSync(other))), /unknown firmware version/);
}
console.log('factory bank tests: OK');

// ---- banks-patch replies (serial.parseBankReply / parseDump)
import { parseBankReply, parseDump } from '../editor/js/serial.js';
{
  const enc = (s) => Uint8Array.from(s, (c) => c.charCodeAt(0));
  assert.equal(parseBankReply(Uint8Array.from([...enc('I (123) log B9\n'), 0x42, 0x33, 0x06])), 3);
  assert.equal(parseBankReply(enc('B3')), null);                        // no ACK yet
  assert.equal(parseBankReply(Uint8Array.from([0x42, 0x39, 0x06])), null); // not a bank digit
  const body = new Uint8Array(64 * 128 * 2);
  const dv = new DataView(body.buffer);
  for (let w = 0; w < 64; w++) for (let k = 0; k < 128; k++) dv.setInt16((w * 128 + k) * 2, w * 100 - k * 50, true);
  const msg = Uint8Array.from([...enc('noise'), ...enc('WAVS'), ...body, 0x06]);
  assert.deepEqual(parseDump(msg.subarray(0, 100)), { need: true });
  const d = parseDump(msg);
  assert.equal(d.waves.length, 64);
  assert.equal(d.waves[5][7], 5 * 100 - 7 * 50);
  assert.equal(d.waves[63][127], 6300 - 6350);
  const bad = msg.slice(); bad[bad.length - 1] = 0x41;
  assert.deepEqual(parseDump(bad), { bad: true });
}
console.log('banks protocol parser tests: OK');
