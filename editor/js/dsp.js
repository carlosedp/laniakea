// Small DSP toolkit for single-cycle waves (Float32Array, periodic).
const TAU = Math.PI * 2;

/** Real DFT -> {re, im} for harmonics 0..maxH (naive, fine for N<=4096, maxH<=128). */
export function dft(x, maxH = x.length / 2) {
  const N = x.length, H = Math.min(maxH, Math.floor(N / 2));
  const re = new Float64Array(H + 1), im = new Float64Array(H + 1);
  for (let h = 0; h <= H; h++) {
    let r = 0, s = 0;
    const w = (TAU * h) / N;
    for (let n = 0; n < N; n++) { r += x[n] * Math.cos(w * n); s -= x[n] * Math.sin(w * n); }
    re[h] = r; im[h] = s;
  }
  return { re, im };
}

/** Inverse of dft() into `len` samples (band-limited synthesis). */
export function idft({ re, im }, len) {
  const out = new Float32Array(len);
  // Skip the Nyquist bin for even lengths (its phase is ambiguous); scaling is up to the caller.
  const H = Math.min(re.length - 1, Math.floor(len / 2) - (len % 2 === 0 ? 1 : 0));
  for (let n = 0; n < len; n++) {
    let v = re[0];
    for (let h = 1; h <= H; h++) {
      const w = (TAU * h * n) / len;
      v += 2 * (re[h] * Math.cos(w) - im[h] * Math.sin(w));
    }
    out[n] = v;
  }
  return out;
}

/** Band-limited resample of one periodic cycle to `len` samples. */
export function resampleCycle(x, len) {
  if (x.length === len) return Float32Array.from(x);
  const H = Math.floor(Math.min(x.length, len) / 2) - 1;
  const spec = dft(x, H);
  const out = idft(spec, len);
  const scale = 1 / x.length;
  for (let i = 0; i < len; i++) out[i] *= scale;
  return out;
}

/** Magnitudes of harmonics 1..H normalised to max = 1. */
export function harmonics(x, H = 32) {
  const { re, im } = dft(x, H);
  const m = [];
  for (let h = 1; h <= H; h++) m.push(Math.hypot(re[h], im[h]));
  const mx = Math.max(1e-9, ...m);
  return m.map((v) => v / mx);
}

// ---------------------------------------------------------------- generators
export function fromHarmonics(amps, len = 256, phases = null) {
  const w = new Float32Array(len);
  for (let h = 1; h <= amps.length; h++) {
    const a = amps[h - 1];
    if (!a) continue;
    const ph = phases ? phases[h - 1] : 0;
    for (let i = 0; i < len; i++) w[i] += a * Math.sin((TAU * h * i) / len + ph);
  }
  return normalize(w);
}

const BL = 48; // band-limit for classic shapes (well below 128-sample Nyquist of 64)
export const gen = {
  sine: (len) => fromHarmonics([1], len),
  triangle: (len) => fromHarmonics(Array.from({ length: BL }, (_, k) => ((k + 1) % 2 ? ((((k / 2) | 0) % 2 ? -1 : 1) / (k + 1) ** 2) : 0)), len),
  saw: (len) => fromHarmonics(Array.from({ length: BL }, (_, k) => 1 / (k + 1)), len),
  square: (len) => fromHarmonics(Array.from({ length: BL }, (_, k) => ((k + 1) % 2 ? 1 / (k + 1) : 0)), len),
  pulse: (len, width = 0.25) => fromHarmonics(Array.from({ length: BL }, (_, k) => Math.sin(Math.PI * (k + 1) * width) / (k + 1)), len,
    Array.from({ length: BL }, () => Math.PI / 2)),
  noise: (len) => { const w = new Float32Array(len); for (let i = 0; i < len; i++) w[i] = Math.random() * 2 - 1; return normalize(smooth(w, 1)); },
  fm: (len, ratio = 2, index = 2) => { const w = new Float32Array(len); for (let i = 0; i < len; i++) { const t = i / len; w[i] = Math.sin(TAU * t + index * Math.sin(TAU * ratio * t)); } return w; },
  sync: (len, ratio = 2.5) => normalize(resampleCycle((() => { const w = new Float32Array(2048); for (let i = 0; i < 2048; i++) { const t = (i / 2048) * ratio; w[i] = 2 * (t - Math.floor(t)) - 1; } return w; })(), len)),
  formant: (len, f1 = 3, f2 = 9) => fromHarmonics(Array.from({ length: BL }, (_, k) => Math.exp(-(((k + 1 - f1) / 1.5) ** 2)) + 0.6 * Math.exp(-(((k + 1 - f2) / 2) ** 2))), len),
};


// ---------------------------------------------------------------- operations (return new arrays)
export function normalize(w) {
  let mean = 0; for (const v of w) mean += v; mean /= w.length;
  let mx = 1e-9; for (const v of w) mx = Math.max(mx, Math.abs(v - mean));
  return Float32Array.from(w, (v) => (v - mean) / mx);
}
export const invert = (w) => Float32Array.from(w, (v) => -v);
export const reverse = (w) => Float32Array.from(w).reverse();
export function smooth(w, r = 2) {
  const N = w.length, o = new Float32Array(N);
  for (let i = 0; i < N; i++) { let s = 0; for (let k = -r; k <= r; k++) s += w[(i + k + N) % N]; o[i] = s / (2 * r + 1); }
  return o;
}
export function fold(w, amount = 2) { return Float32Array.from(w, (v) => Math.sin(v * amount * Math.PI / 2)); }
export function clip(w, drive = 2) { return Float32Array.from(w, (v) => Math.tanh(v * drive) / Math.tanh(drive)); }
export function shift(w, frac = 0.25) { const N = w.length, s = Math.round(frac * N); return Float32Array.from(w, (_, i) => w[(i + s) % N]); }
export function lerp(a, b, t) { return Float32Array.from(a, (v, i) => v * (1 - t) + b[i] * t); }

/** Bilinear morph on the 8x8 grid (x,y in 0..7), like the module's X/Y interpolation. */
export function morph(waves, x, y, cols = 8) {
  const x0 = Math.floor(x), y0 = Math.floor(y);
  const x1 = Math.min(x0 + 1, cols - 1), y1 = Math.min(y0 + 1, cols - 1);
  const tx = x - x0, ty = y - y0;
  const a = waves[y0 * cols + x0], b = waves[y0 * cols + x1], c = waves[y1 * cols + x0], d = waves[y1 * cols + x1];
  const out = new Float32Array(a.length);
  for (let i = 0; i < a.length; i++) {
    out[i] = (a[i] * (1 - tx) + b[i] * tx) * (1 - ty) + (c[i] * (1 - tx) + d[i] * tx) * ty;
  }
  return out;
}

/** Convert 256-sample float waves to what the module stores: 128 int16 per wave (band-limited). */
export function toModuleFormat(waves, { decimate = false } = {}) {
  return waves.map((w) => {
    const r = decimate ? Float32Array.from({ length: 128 }, (_, i) => w[i * 2]) : resampleCycle(w, 128);
    return Array.from(r, (v) => Math.max(-32767, Math.min(32767, Math.round(v * 32767))));
  });
}
