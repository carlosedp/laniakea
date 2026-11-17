// WAV import/export for Laniakea wavetables.
// Internal format: 64 waves x 256 samples, Float32 in [-1, 1] (WaveEdit layout).
import { resampleCycle } from './dsp.js';

export const WAVES = 64;
export const LEN = 256;

function readChunks(view) {
  if (view.getUint32(0, false) !== 0x52494646 || view.getUint32(8, false) !== 0x57415645) {
    throw new Error('Not a RIFF/WAVE file');
  }
  const chunks = {};
  let p = 12;
  while (p + 8 <= view.byteLength) {
    const id = String.fromCharCode(view.getUint8(p), view.getUint8(p + 1), view.getUint8(p + 2), view.getUint8(p + 3));
    const size = view.getUint32(p + 4, true);
    chunks[id] = { offset: p + 8, size: Math.min(size, view.byteLength - p - 8) };
    p += 8 + size + (size & 1);
  }
  return chunks;
}

function decodeSamples(view, fmt, data) {
  const tag = view.getUint16(fmt.offset, true);
  const channels = view.getUint16(fmt.offset + 2, true);
  const bits = view.getUint16(fmt.offset + 14, true);
  const fmtTag = tag === 0xfffe ? view.getUint16(fmt.offset + 24, true) : tag; // WAVE_FORMAT_EXTENSIBLE
  const bytes = bits / 8;
  const frames = Math.floor(data.size / (bytes * channels));
  const out = new Float32Array(frames);
  for (let i = 0; i < frames; i++) {
    const o = data.offset + i * bytes * channels; // first channel only
    let v;
    if (fmtTag === 3 && bits === 32) v = view.getFloat32(o, true);
    else if (fmtTag === 3 && bits === 64) v = view.getFloat64(o, true);
    else if (bits === 8) v = (view.getUint8(o) - 128) / 128;
    else if (bits === 16) v = view.getInt16(o, true) / 32768;
    else if (bits === 24) {
      let x = view.getUint8(o) | (view.getUint8(o + 1) << 8) | (view.getUint8(o + 2) << 16);
      if (x & 0x800000) x -= 0x1000000;
      v = x / 8388608;
    } else if (bits === 32) v = view.getInt32(o, true) / 2147483648;
    else throw new Error(`Unsupported WAV: format ${fmtTag}, ${bits} bit`);
    out[i] = v;
  }
  return out;
}

// Serum-style 'clm ' chunk: "<!>2048 ..." gives the frame (cycle) size.
function clmFrameSize(view, chunks) {
  const c = chunks['clm '];
  if (!c) return 0;
  let s = '';
  for (let i = 0; i < Math.min(c.size, 16); i++) s += String.fromCharCode(view.getUint8(c.offset + i));
  const m = s.match(/<!>(\d+)/);
  return m ? parseInt(m[1], 10) : 0;
}

/** Parse any reasonable single-cycle wavetable WAV into 64 x 256 Float32Arrays. */
export function parseWavetable(arrayBuffer, { frameSize: forced } = {}) {
  const view = new DataView(arrayBuffer);
  const chunks = readChunks(view);
  if (!chunks['fmt '] || !chunks.data) throw new Error('WAV is missing fmt/data chunk');
  const samples = decodeSamples(view, chunks['fmt '], chunks.data);
  let frame = forced || clmFrameSize(view, chunks);
  if (!frame) {
    if (samples.length === WAVES * LEN) frame = LEN;
    else if (samples.length % 2048 === 0 && samples.length >= 2048 * 2) frame = 2048;
    else if (samples.length % WAVES === 0) frame = samples.length / WAVES;
    else if (samples.length % LEN === 0) frame = LEN;
    else throw new Error(`Cannot infer cycle length for ${samples.length} samples`);
  }
  const nFrames = Math.floor(samples.length / frame);
  if (nFrames < 1) throw new Error('WAV shorter than one cycle');
  const cycles = [];
  for (let f = 0; f < nFrames; f++) cycles.push(resampleCycle(samples.subarray(f * frame, (f + 1) * frame), LEN));
  // Map nFrames -> 64 waves (pick/interpolate evenly across the source table)
  const waves = [];
  for (let k = 0; k < WAVES; k++) {
    const pos = nFrames === 1 ? 0 : (k * (nFrames - 1)) / (WAVES - 1);
    const a = Math.floor(pos), b = Math.min(a + 1, nFrames - 1), t = pos - a;
    const w = new Float32Array(LEN);
    for (let i = 0; i < LEN; i++) w[i] = cycles[a][i] * (1 - t) + cycles[b][i] * t;
    waves.push(w);
  }
  return { waves, info: `${samples.length} samples, ${nFrames} cycles of ${frame}` };
}

/**
 * Parse a single-cycle WAV (AKWF = 600 samples, Serum/Vital single cycles = 2048, etc.)
 * into one 256-sample wave. The whole file is treated as exactly one period.
 */
export function parseSingleCycle(arrayBuffer) {
  const view = new DataView(arrayBuffer);
  const chunks = readChunks(view);
  if (!chunks['fmt '] || !chunks.data) throw new Error('WAV is missing fmt/data chunk');
  const samples = decodeSamples(view, chunks['fmt '], chunks.data);
  if (samples.length < 8) throw new Error('WAV too short');
  if (samples.length > 8192) throw new Error(`${samples.length} samples - looks like a wavetable, not a single cycle`);
  return resampleCycle(samples, LEN);
}

/** Heuristic: is this file a full 64-wave bank / multi-cycle table, or a single cycle? */
export function looksLikeBank(arrayBuffer) {
  const view = new DataView(arrayBuffer);
  const chunks = readChunks(view);
  const fmt = chunks['fmt '];
  if (!fmt || !chunks.data) return false;
  const bytes = (view.getUint16(fmt.offset + 14, true) / 8) * view.getUint16(fmt.offset + 2, true);
  const n = chunks.data.size / bytes;
  return !!chunks['clm '] || n === WAVES * LEN || n > 8192;
}

/** Encode 64 x 256 waves as a 16-bit mono WAV (WaveEdit / Magerit compatible). */
export function encodeWavetable(waves, sampleRate = 44100) {
  const n = WAVES * LEN;
  const buf = new ArrayBuffer(44 + n * 2);
  const v = new DataView(buf);
  const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  str(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); str(8, 'WAVE');
  str(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, sampleRate, true); v.setUint32(28, sampleRate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, 'data'); v.setUint32(40, n * 2, true);
  let o = 44;
  for (const w of waves) for (let i = 0; i < LEN; i++, o += 2) {
    v.setInt16(o, Math.max(-32768, Math.min(32767, Math.round(w[i] * 32767))), true);
  }
  return new Blob([buf], { type: 'audio/wav' });
}
