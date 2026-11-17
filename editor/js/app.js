import { WAVES, LEN, parseWavetable, parseSingleCycle, looksLikeBank, encodeWavetable } from './wav.js';
import * as dsp from './dsp.js';
import { LaniakeaSerial } from './serial.js';

// Wave index layout assumed row-major: index = Y * 8 + X (Y = row / ORBITS-menu SHAPE, X = column / SHAPE).
const COLS = 8;
const ROW_NAMES = ['Basic', 'Drone', 'Envelopes', 'Basic fusion', 'Ambient', 'Organ A', 'Organ B', 'Harmonics'];
const STORAGE_KEY = 'laniakea-editor-bank-v1';
const $ = (id) => document.getElementById(id);

// ------------------------------------------------------------------ state
let waves = [];
let cur = 0;
let selA = 0, selB = 0;
let clipboard = null;
const undoStack = [], redoStack = [];

function snapshot() { return waves.map((w) => Float32Array.from(w)); }
function pushUndo() {
  undoStack.push(snapshot());
  if (undoStack.length > 60) undoStack.shift();
  redoStack.length = 0;
}
function undo() { if (!undoStack.length) return; redoStack.push(snapshot()); waves = undoStack.pop(); refreshAll(); }
function redo() { if (!redoStack.length) return; undoStack.push(snapshot()); waves = redoStack.pop(); refreshAll(); }
const selRange = () => [Math.min(selA, selB), Math.max(selA, selB)];

function save() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(waves.map((w) => Array.from(w, (v) => Math.round(v * 32767)))));
  } catch { /* storage unavailable - fine */ }
}
function load() {
  try {
    const s = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
    if (Array.isArray(s) && s.length === WAVES) return s.map((w) => Float32Array.from(w, (v) => v / 32767));
  } catch { /* ignore */ }
  return null;
}

// ------------------------------------------------------------------ logging / progress
function log(msg) {
  const el = $('log');
  el.textContent += `[${new Date().toLocaleTimeString()}] ${msg}\n`;
  el.scrollTop = el.scrollHeight;
}
function progress(v) {
  $('progress').hidden = v === null;
  $('progress-bar').style.width = `${Math.round((v || 0) * 100)}%`;
}

// ------------------------------------------------------------------ drawing helpers
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
function drawWave(canvas, w, color, { center = true, lineWidth = 1.5 } = {}) {
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  if (center) {
    ctx.strokeStyle = css('--line'); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, H / 2); ctx.lineTo(W, H / 2); ctx.stroke();
  }
  ctx.strokeStyle = color; ctx.lineWidth = lineWidth; ctx.lineJoin = 'round';
  ctx.beginPath();
  for (let i = 0; i < w.length; i++) {
    const x = (i / (w.length - 1)) * W, y = H / 2 - w[i] * (H / 2 - 3);
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  }
  ctx.stroke();
}

// ------------------------------------------------------------------ grid
const cells = [];
function buildGrid() {
  const g = $('grid');
  g.innerHTML = '';
  g.append(Object.assign(document.createElement('div'), { className: 'axis' }));
  for (let x = 0; x < COLS; x++) g.append(Object.assign(document.createElement('div'), { className: 'axis', textContent: `X${x + 1}` }));
  for (let y = 0; y < COLS; y++) {
    g.append(Object.assign(document.createElement('div'), { className: 'axis', textContent: `Y${y + 1}`, title: `Factory row: ${ROW_NAMES[y]}` }));
    for (let x = 0; x < COLS; x++) {
      const i = y * COLS + x;
      const c = Object.assign(document.createElement('canvas'), { width: 112, height: 80, title: `Wave ${i + 1} (X${x + 1}, Y${y + 1})` });
      c.addEventListener('click', (e) => {
        if (e.shiftKey) selB = i; else { selA = selB = i; }
        cur = i; refreshAll(false);
      });
      c.addEventListener('dragover', (e) => { e.preventDefault(); c.classList.add('drop'); });
      c.addEventListener('dragleave', () => c.classList.remove('drop'));
      c.addEventListener('drop', (e) => { e.preventDefault(); e.stopPropagation(); c.classList.remove('drop'); g.classList.remove('dragging'); importFiles([...e.dataTransfer.files], i); });
      cells[i] = c;
      g.append(c);
    }
  }
  g.addEventListener('dragover', (e) => { e.preventDefault(); g.classList.add('dragging'); });
  g.addEventListener('dragleave', (e) => { if (e.target === g) g.classList.remove('dragging'); });
  g.addEventListener('drop', (e) => { e.preventDefault(); g.classList.remove('dragging'); importFiles([...e.dataTransfer.files], cur); });
}
function refreshGrid() {
  const [a, b] = selRange();
  const color = css('--wave'), sel = css('--wave-sel');
  cells.forEach((c, i) => {
    c.classList.toggle('sel', i >= a && i <= b && a !== b);
    c.classList.toggle('cur', i === cur);
    drawWave(c, waves[i], i === cur ? sel : color, { lineWidth: 1.4 });
  });
}

// ------------------------------------------------------------------ wave editor (draw)
const waveCanvas = $('wave-canvas');
let drawing = null;
function wavePoint(e) {
  const r = waveCanvas.getBoundingClientRect();
  const i = Math.round(((e.clientX - r.left) / r.width) * (LEN - 1));
  const v = 1 - ((e.clientY - r.top) / r.height) * 2;
  return [Math.max(0, Math.min(LEN - 1, i)), Math.max(-1, Math.min(1, v))];
}
waveCanvas.addEventListener('pointerdown', (e) => {
  pushUndo();
  waveCanvas.setPointerCapture(e.pointerId);
  drawing = wavePoint(e);
  waves[cur][drawing[0]] = drawing[1];
  refreshWave();
});
waveCanvas.addEventListener('pointermove', (e) => {
  if (!drawing) return;
  const [i1, v1] = wavePoint(e), [i0, v0] = drawing;
  const n = Math.abs(i1 - i0);
  for (let k = 0; k <= n; k++) {
    const t = n ? k / n : 1;
    waves[cur][Math.round(i0 + (i1 - i0) * t)] = v0 + (v1 - v0) * t;
  }
  drawing = [i1, v1];
  refreshWave();
});
waveCanvas.addEventListener('pointerup', () => { if (drawing) { drawing = null; changed(); } });

function refreshWave() {
  $('wave-label').textContent = `${cur + 1}  (X${(cur % COLS) + 1}, Y${Math.floor(cur / COLS) + 1})`;
  drawWave(waveCanvas, waves[cur], css('--wave-sel'), { lineWidth: 2 });
  if (!harmDrag) drawHarmonics();
  drawWave(cells[cur], waves[cur], css('--wave-sel'), { lineWidth: 1.4 });
}

// ------------------------------------------------------------------ harmonics editor
const H = 63; // the module keeps 128 samples per wave -> harmonics 1..63
const harmCanvas = $('harm-canvas');
let harmDrag = null; // {amps, phases}
function harmState(w) {
  const { re, im } = dsp.dft(w, H);
  const amps = [], phases = [];
  for (let h = 1; h <= H; h++) { amps.push(Math.hypot(re[h], im[h])); phases.push(Math.atan2(im[h], re[h]) + Math.PI / 2); }
  const mx = Math.max(1e-9, ...amps);
  return { amps: amps.map((a) => a / mx), phases };
}
function drawHarmonics(state = harmState(waves[cur])) {
  const ctx = harmCanvas.getContext('2d');
  const W = harmCanvas.width, Hc = harmCanvas.height, bw = W / H;
  ctx.clearRect(0, 0, W, Hc);
  ctx.fillStyle = css('--wave-sel');
  state.amps.forEach((a, k) => {
    const h = Math.sqrt(a) * (Hc - 4); // sqrt scale shows quiet partials
    ctx.fillRect(k * bw + 1, Hc - h, Math.max(1, bw - 2), h);
  });
}
function harmEdit(e) {
  const r = harmCanvas.getBoundingClientRect();
  const k = Math.floor(((e.clientX - r.left) / r.width) * H);
  if (k < 0 || k >= H) return;
  const a = Math.max(0, Math.min(1, 1 - (e.clientY - r.top) / r.height));
  harmDrag.amps[k] = a * a;
  const w = new Float32Array(LEN);
  harmDrag.amps.forEach((amp, j) => {
    if (amp < 1e-5) return;
    for (let i = 0; i < LEN; i++) w[i] += amp * Math.sin((2 * Math.PI * (j + 1) * i) / LEN + harmDrag.phases[j]);
  });
  let mx = 1e-9; for (const v of w) mx = Math.max(mx, Math.abs(v));
  waves[cur] = Float32Array.from(w, (v) => v / mx);
  drawHarmonics(harmDrag);
  refreshWave();
}
harmCanvas.addEventListener('pointerdown', (e) => { pushUndo(); harmCanvas.setPointerCapture(e.pointerId); harmDrag = harmState(waves[cur]); harmEdit(e); });
harmCanvas.addEventListener('pointermove', (e) => { if (harmDrag) harmEdit(e); });
harmCanvas.addEventListener('pointerup', () => { if (harmDrag) { harmDrag = null; changed(); } });

// ------------------------------------------------------------------ operations
const OPS = {
  normalize: (w) => dsp.normalize(w), invert: dsp.invert, reverse: dsp.reverse,
  smooth: (w) => dsp.smooth(w, 2), fold: (w) => dsp.fold(w, 2.2), clip: (w) => dsp.clip(w, 3),
  shift: (w) => dsp.shift(w, 0.25), bandlimit: (w) => dsp.resampleCycle(dsp.resampleCycle(w, 128), LEN),
};
document.querySelectorAll('[data-op]').forEach((b) => b.addEventListener('click', () => {
  pushUndo();
  const [a, z] = selRange();
  for (let i = a; i <= z; i++) waves[i] = OPS[b.dataset.op](waves[i]);
  changed();
}));

function generate(type, p, len = LEN) {
  switch (type) {
    case 'pulse': return dsp.gen.pulse(len, 0.02 + p * 0.48);
    case 'fm': return dsp.gen.fm(len, 1 + Math.round(p * 7), 0.5 + p * 4);
    case 'sync': return dsp.gen.sync(len, 1 + p * 4);
    case 'formant': return dsp.gen.formant(len, 2 + p * 8, 8 + p * 14);
    default: return dsp.gen[type](len);
  }
}
$('btn-gen').addEventListener('click', () => {
  pushUndo();
  const [a, z] = selRange();
  for (let i = a; i <= z; i++) waves[i] = generate($('gen-type').value, Number($('gen-param').value));
  changed();
});

function interpolate(indices) {
  if (indices.length < 3) return;
  pushUndo();
  const A = waves[indices[0]], B = waves[indices[indices.length - 1]];
  indices.forEach((idx, k) => { waves[idx] = dsp.lerp(A, B, k / (indices.length - 1)); });
  changed();
}
$('btn-fill-row').addEventListener('click', () => { const y = Math.floor(cur / COLS); interpolate([...Array(COLS)].map((_, x) => y * COLS + x)); });
$('btn-fill-col').addEventListener('click', () => { const x = cur % COLS; interpolate([...Array(COLS)].map((_, y) => y * COLS + x)); });
$('btn-fill-sel').addEventListener('click', () => { const [a, z] = selRange(); interpolate([...Array(z - a + 1)].map((_, k) => a + k)); });
$('btn-norm-all').addEventListener('click', () => { pushUndo(); waves = waves.map(dsp.normalize); changed(); });

// ------------------------------------------------------------------ bank presets
function tilt(w, k) {
  if (!k) return w;
  const { re, im } = dsp.dft(w, 127);
  for (let h = 1; h < re.length; h++) { const g = Math.pow(h, -k); re[h] *= g; im[h] *= g; }
  re[0] = 0;
  return dsp.normalize(dsp.idft({ re, im }, w.length));
}
const PRESETS = {
  classic: () => {
    const shapes = [dsp.gen.sine(LEN), dsp.gen.triangle(LEN), dsp.gen.saw(LEN), dsp.gen.square(LEN), dsp.gen.pulse(LEN, 0.25),
      dsp.gen.pulse(LEN, 0.1), dsp.gen.fm(LEN, 2, 2), dsp.gen.sync(LEN, 3)];
    return [...Array(WAVES)].map((_, i) => tilt(shapes[i % COLS], Math.floor(i / COLS) * 0.18));
  },
  pwm: () => [...Array(WAVES)].map((_, i) => dsp.gen.pulse(LEN, 0.5 - (0.47 * i) / (WAVES - 1))),
  harm: () => [...Array(WAVES)].map((_, i) => dsp.fromHarmonics([...Array(i + 1)].map((__, h) => 1 / (h + 1)), LEN)),
  fm: () => [...Array(WAVES)].map((_, i) => dsp.gen.fm(LEN, 1 + (i % COLS), (Math.floor(i / COLS) / 7) * 5)),
  sync: () => [...Array(WAVES)].map((_, i) => tilt(dsp.gen.sync(LEN, 1 + ((i % COLS) / 7) * 4), Math.floor(i / COLS) * 0.2)),
  formant: () => [...Array(WAVES)].map((_, i) => dsp.gen.formant(LEN, 2 + (i % COLS), 7 + Math.floor(i / COLS) * 2)),
  fold: () => [...Array(WAVES)].map((_, i) => dsp.normalize(dsp.fold(dsp.gen.sine(LEN), 1 + (i / (WAVES - 1)) * 9))),
};
$('preset-bank').addEventListener('change', (e) => {
  const f = PRESETS[e.target.value];
  e.target.value = '';
  if (!f) return;
  pushUndo(); waves = f(); changed();
  log('Generated new bank.');
});

// ------------------------------------------------------------------ file import / export
async function importFiles(files, startIndex) {
  files = files.filter((f) => /\.wav$/i.test(f.name)).sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
  if (!files.length) return;
  pushUndo();
  let slot = startIndex;
  for (const f of files) {
    try {
      const buf = await f.arrayBuffer();
      if (files.length === 1 && looksLikeBank(buf)) {
        const { waves: w, info } = parseWavetable(buf);
        waves = w;
        log(`Loaded bank ${f.name} (${info})`);
        break;
      }
      if (slot >= WAVES) { log(`Bank full, skipped ${f.name}`); continue; }
      waves[slot] = dsp.normalize(parseSingleCycle(buf));
      log(`Wave ${slot + 1} <- ${f.name}`);
      slot++;
    } catch (err) { log(`${f.name}: ${err.message}`); }
  }
  changed();
}
$('file-bank').addEventListener('change', async (e) => {
  const f = e.target.files[0]; e.target.value = '';
  if (!f) return;
  try { pushUndo(); const { waves: w, info } = parseWavetable(await f.arrayBuffer()); waves = w; log(`Loaded bank ${f.name} (${info})`); changed(); }
  catch (err) { log(`${f.name}: ${err.message}`); }
});
$('file-cycles').addEventListener('change', (e) => { const fs = [...e.target.files]; e.target.value = ''; importFiles(fs, cur); });
$('btn-export').addEventListener('click', () => {
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(encodeWavetable(waves)), download: 'laniakea_bank.wav' });
  a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});

// ------------------------------------------------------------------ keyboard
document.addEventListener('keydown', (e) => {
  if (e.target.matches('input, select, textarea')) return;
  const k = e.key.toLowerCase();
  if ((e.ctrlKey || e.metaKey) && k === 'z') { e.preventDefault(); e.shiftKey ? redo() : undo(); }
  else if ((e.ctrlKey || e.metaKey) && k === 'y') { e.preventDefault(); redo(); }
  else if ((e.ctrlKey || e.metaKey) && k === 'c') { const [a, z] = selRange(); clipboard = waves.slice(a, z + 1).map((w) => Float32Array.from(w)); log(`Copied ${clipboard.length} wave(s)`); }
  else if ((e.ctrlKey || e.metaKey) && k === 'v' && clipboard) { pushUndo(); clipboard.forEach((w, j) => { if (cur + j < WAVES) waves[cur + j] = Float32Array.from(w); }); changed(); }
  else if (k.startsWith('arrow')) {
    e.preventDefault();
    const d = { arrowleft: -1, arrowright: 1, arrowup: -COLS, arrowdown: COLS }[k];
    cur = Math.max(0, Math.min(WAVES - 1, cur + d)); selA = selB = cur; refreshAll(false);
  }
});

// ------------------------------------------------------------------ morph preview + audio
let mx = 0, my = 0;
const xyPad = $('xy-pad');
function drawXY() {
  const ctx = xyPad.getContext('2d'), W = xyPad.width, step = W / COLS;
  ctx.clearRect(0, 0, W, W);
  ctx.fillStyle = css('--muted');
  for (let y = 0; y < COLS; y++) for (let x = 0; x < COLS; x++) {
    ctx.beginPath(); ctx.arc(step / 2 + x * step, step / 2 + y * step, 2, 0, 7); ctx.fill();
  }
  ctx.fillStyle = css('--wave-sel');
  ctx.beginPath(); ctx.arc(step / 2 + mx * step, step / 2 + my * step, 7, 0, 7); ctx.fill();
}
function setXY(x, y) {
  mx = Math.max(0, Math.min(7, x)); my = Math.max(0, Math.min(7, y));
  $('mx').value = mx; $('my').value = my;
  $('mx-o').textContent = mx.toFixed(2); $('my-o').textContent = my.toFixed(2);
  refreshMorph();
}
function refreshMorph() {
  const w = dsp.morph(waves, mx, my);
  drawWave($('morph-canvas'), w, css('--wave-sel'), { lineWidth: 2 });
  drawXY();
  updateOsc(w);
}
xyPad.addEventListener('pointerdown', (e) => { xyPad.setPointerCapture(e.pointerId); padMove(e); xyPad.onpointermove = padMove; });
xyPad.addEventListener('pointerup', () => { xyPad.onpointermove = null; });
function padMove(e) {
  const r = xyPad.getBoundingClientRect(), step = r.width / COLS;
  setXY((e.clientX - r.left - step / 2) / step, (e.clientY - r.top - step / 2) / step);
}
$('mx').addEventListener('input', (e) => setXY(Number(e.target.value), my));
$('my').addEventListener('input', (e) => setXY(mx, Number(e.target.value)));

let actx = null, osc = null, gain = null;
const NOTE = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const midiHz = (n) => 440 * Math.pow(2, (n - 69) / 12);
function updateOsc(w) {
  if (!osc) return;
  const { re, im } = dsp.dft(w, 63);
  const real = new Float32Array(64), imag = new Float32Array(64);
  for (let h = 1; h < 64; h++) { real[h] = (2 * re[h]) / LEN; imag[h] = (-2 * im[h]) / LEN; }
  osc.setPeriodicWave(actx.createPeriodicWave(real, imag, { disableNormalization: true }));
}
$('btn-play').addEventListener('click', () => {
  if (osc) { osc.stop(); osc = null; $('btn-play').textContent = '▶ Play'; return; }
  actx = actx || new AudioContext();
  gain = gain || Object.assign(actx.createGain(), {});
  gain.gain.value = Number($('vol').value);
  gain.connect(actx.destination);
  osc = actx.createOscillator();
  osc.frequency.value = midiHz(Number($('pitch').value));
  osc.connect(gain); osc.start();
  $('btn-play').textContent = '■ Stop';
  refreshMorph();
});
$('pitch').addEventListener('input', (e) => {
  const n = Number(e.target.value);
  $('pitch-o').textContent = NOTE[n % 12] + (Math.floor(n / 12) - 1);
  if (osc) osc.frequency.setTargetAtTime(midiHz(n), actx.currentTime, 0.01);
});
$('vol').addEventListener('input', (e) => { if (gain) gain.gain.setTargetAtTime(Number(e.target.value), actx.currentTime, 0.02); });

function lfoLoop(t) {
  const lx = $('lfo-x-on').checked, ly = $('lfo-y-on').checked;
  if (lx || ly) {
    const s = t / 1000;
    setXY(lx ? 3.5 + 3.5 * Math.sin(2 * Math.PI * Number($('lfo-x-rate').value) * s) : mx,
      ly ? 3.5 + 3.5 * Math.sin(2 * Math.PI * Number($('lfo-y-rate').value) * s) : my);
  }
  requestAnimationFrame(lfoLoop);
}

// ------------------------------------------------------------------ module connection
const serial = new LaniakeaSerial(log);
function setConnected(on) {
  $('conn-status').textContent = on ? 'connected' : 'disconnected';
  $('conn-status').className = `pill ${on ? 'on' : 'off'}`;
  $('btn-connect').textContent = on ? 'Disconnect' : 'Connect';
  $('btn-upload').disabled = !on; $('btn-factory').disabled = !on;
}
$('btn-connect').addEventListener('click', async () => {
  try {
    if (serial.connected) { await serial.disconnect(); setConnected(false); log('Disconnected'); return; }
    await serial.connect(); setConnected(true);
  } catch (err) { log(`Connect failed: ${err.message}`); }
});
async function busy(fn) {
  $('btn-upload').disabled = $('btn-factory').disabled = $('btn-connect').disabled = true;
  try { await fn(); } catch (err) { log(`Error: ${err.message}`); }
  finally { progress(null); $('btn-connect').disabled = false; setConnected(serial.connected); }
}
$('btn-upload').addEventListener('click', () => busy(async () => {
  const data = dsp.toModuleFormat(waves, { decimate: $('resample').value === 'dec' });
  progress(0);
  await serial.uploadWaves(data, progress);
}));
$('btn-factory').addEventListener('click', () => busy(() => serial.restoreFactory()));

// ------------------------------------------------------------------ init
function changed() { save(); refreshAll(); }
function refreshAll(full = true) {
  refreshGrid(); refreshWave();
  if (full || true) refreshMorph();
}

buildGrid();
waves = load() || PRESETS.classic();
refreshAll();
setXY(0, 0);
requestAnimationFrame(lfoLoop);
if (!LaniakeaSerial.supported()) {
  $('btn-connect').disabled = true;
  log('Web Serial is not available in this browser - use Chrome or Edge to upload to the module. Editing and export still work.');
} else {
  log('Ready. Power the module from the rack, connect USB, then click Connect.');
}
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => refreshAll());
