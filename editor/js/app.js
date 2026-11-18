import { WAVES, LEN, parseWavetable, parseSingleCycle, looksLikeBank, encodeWavetable } from './wav.js';
import * as dsp from './dsp.js';
import { LaniakeaSerial } from './serial.js';

// Wave index layout assumed row-major: index = Y * 8 + X (Y = row / ORBITS-menu SHAPE, X = column / SHAPE).
const COLS = 8;
const ROW_NAMES = ['Basic', 'Drone', 'Envelopes', 'Basic fusion', 'Ambient', 'Organ A', 'Organ B', 'Harmonics'];
const STORAGE_KEY = 'laniakea-editor-bank-v1';
const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let lastLoadedName = '';   // suggested name when the editor's waves are stored in a bank

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
function undo() { if (!undoStack.length) return; redoStack.push(snapshot()); waves = undoStack.pop(); changed(); }
function redo() { if (!redoStack.length) return; undoStack.push(snapshot()); waves = redoStack.pop(); changed(); }
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
        cur = i; refreshAll();
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
  if (f) lastLoadedName = e.target.selectedOptions[0].textContent;
  e.target.value = '';
  if (!f) return;
  pushUndo(); waves = f(); changed(); newContent();
  log('Generated new bank.');
});

// ------------------------------------------------------------------ file import / export
async function importFiles(files, startIndex) {
  files = files.filter((f) => /\.wav$/i.test(f.name)).sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
  if (!files.length) return;
  pushUndo();
  let slot = startIndex, bankLoaded = false;
  for (const f of files) {
    try {
      const buf = await f.arrayBuffer();
      if (files.length === 1 && looksLikeBank(buf)) {
        const { waves: w, info } = parseWavetable(buf);
        waves = w;
        lastLoadedName = f.name.replace(/\.wav$/i, '');
        bankLoaded = true;
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
  if (bankLoaded) newContent();
}
$('file-bank').addEventListener('change', async (e) => {
  const f = e.target.files[0]; e.target.value = '';
  if (!f) return;
  try {
    pushUndo(); const { waves: w, info } = parseWavetable(await f.arrayBuffer()); waves = w;
    lastLoadedName = f.name.replace(/\.wav$/i, '');
    log(`Loaded bank ${f.name} (${info})`); changed(); newContent();
  }
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
    cur = Math.max(0, Math.min(WAVES - 1, cur + d)); selA = selB = cur; refreshAll();
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
  // Map each axis with its own cell size: the canvas can be scaled non-uniformly by CSS.
  const r = xyPad.getBoundingClientRect(), sx = r.width / COLS, sy = r.height / COLS;
  setXY((e.clientX - r.left - sx / 2) / sx, (e.clientY - r.top - sy / 2) / sy);
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
let moduleBank = null;          // bank the module is playing (MAGB), null = unknown / stock firmware
function setConnected(on) {
  $('conn-status').textContent = on ? 'connected' : 'disconnected';
  $('conn-status').className = `pill ${on ? 'on' : 'off'}`;
  $('btn-connect').textContent = on ? 'Disconnect' : 'Connect';
  if (!on) moduleBank = null;
  renderBanks();
}
$('btn-connect').addEventListener('click', async () => {
  try {
    if (serial.connected) { await serial.disconnect(); setConnected(false); log('Disconnected'); return; }
    await serial.connect(); setConnected(true);
    await busy(syncWithModule);
  } catch (err) { log(`Connect failed: ${err.message}`); }
});
let isBusy = false;
async function busy(fn) {
  isBusy = true;
  renderBanks();
  ['btn-connect', 'btn-flash', 'btn-backup'].forEach((id) => { $(id).disabled = true; });
  try { await fn(); } catch (err) { log(`Error: ${err.message}`); }
  finally {
    isBusy = false;
    progress(null);
    $('btn-connect').disabled = false; $('btn-backup').disabled = false;
    $('btn-flash').disabled = !fwBytes;
    setConnected(serial.connected);
  }
}

/** On connect: ask which bank the module plays, select it, and show its waves in the editor. */
async function syncWithModule() {
  await sleep(300);
  let bank = await serial.queryBank();
  if (!bank) { await sleep(2000); bank = await serial.queryBank(); }   // opening the port may have rebooted it
  if (!bank) { log('Connected. The module did not report a bank (stock firmware or no banks patch): uploads go to its current bank.'); return; }
  moduleBank = bank;
  selectedBank = bank;
  saveLink();
  log(`Module is playing bank ${bank}.`);
  if (unsaved) { log('The editor has unsaved changes, so it was left as is. Use "Read bank from module" to load the module\'s waves.'); return; }
  const slot = library[bank - 1];
  if (slot?.waves && slot.uploaded) { await openSlot(bank); return; }
  await readFromModule();
}
async function readFromModule() {
  progress(0);
  const raw = await serial.readWaves(progress);
  const bank = moduleBank;
  pushUndo();
  waves = raw.map((w) => dsp.resampleCycle(Float32Array.from(w, (v) => v / 32767), LEN));
  editorBank = bank; unsaved = true;
  lastLoadedName = library[bank - 1]?.name || `Bank ${bank} (from module)`;
  changed(false);
  log(`Read bank ${bank ?? '(current)'} from the module into the editor. Click "Save to bank" to keep it in this browser.`);
}
$('btn-read').addEventListener('click', () => busy(async () => {
  if (!moduleBank) moduleBank = await serial.queryBank();
  if (unsaved && !confirm('Replace the editor\'s unsaved waves with the bank from the module? (Ctrl+Z undoes it)')) return;
  await readFromModule();
}));

// ------------------------------------------------------------------ firmware updater
// esptool-js comes from a CDN, so the flasher is loaded lazily: the editor works offline.
let fwBytes = null, fwReleases = [];
const flasherModule = () => import('./flasher.js');
async function showFirmware(bytes, label) {
  const { inspectFirmware } = await flasherModule();
  try {
    const info = await inspectFirmware(bytes);
    fwBytes = bytes;
    $('fw-info').textContent = `${label}: ${info.project} version "${info.version}", built ${info.date} ${info.time}, ${bytes.length} bytes, checksums OK`;
  } catch (err) {
    fwBytes = null;
    $('fw-info').textContent = `${label}: rejected: ${err.message}`;
  }
  $('btn-flash').disabled = !fwBytes || !LaniakeaSerial.supported();
}
async function loadReleases() {
  try {
    const { officialReleases } = await flasherModule();
    fwReleases = await officialReleases();
    $('fw-source').innerHTML = '<option value="">Official release…</option>' +
      fwReleases.map((r, i) => `<option value="${i}">Official ${r.version} (${r.date})</option>`).join('');
  } catch (err) {
    $('fw-source').innerHTML = '<option value="">Official releases unavailable (offline?)</option>';
  }
}
$('fw-source').addEventListener('change', (e) => busy(async () => {
  if (e.target.value === '') return;
  const rel = fwReleases[Number(e.target.value)];
  const { downloadOfficial } = await flasherModule();
  await showFirmware(await downloadOfficial(rel, log), `Official ${rel.version}`);
}));
$('fw-file').addEventListener('change', async (e) => {
  const f = e.target.files[0]; e.target.value = '';
  if (!f) return;
  $('fw-source').value = '';
  await showFirmware(new Uint8Array(await f.arrayBuffer()), f.name);
});
async function takePort() { return serial.connected ? serial.release() : null; }
$('btn-flash').addEventListener('click', () => {
  if (!fwBytes) return;
  if (!confirm(`Flash this firmware?\n\n${$('fw-info').textContent}\n\nCalibration and settings are kept. Keep the module powered and don't unplug USB until it's done.`)) return;
  busy(async () => {
    const { flashFirmware } = await flasherModule();
    progress(0);
    await flashFirmware({ port: await takePort(), bytes: fwBytes, log, onProgress: progress });
    log('Click Connect again to upload waves.');
  });
});
$('btn-backup').addEventListener('click', () => busy(async () => {
  const { backupFlash } = await flasherModule();
  progress(0);
  const { data } = await backupFlash({ port: await takePort(), log, onProgress: progress });
  const stamp = new Date().toISOString().replace(/[:T]/g, '-').slice(0, 19);
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(new Blob([data])), download: `laniakea_backup_${stamp}.bin` });
  a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  log(`Backup saved (${data.length} bytes). Keep it safe: it contains your calibration.`);
}));

// ------------------------------------------------------------------ banks (8 slots, kept in this browser)
// slot = null                               empty: uploads leave the module's bank alone
//      | {name, factory: true, uploaded}    upload = restore the firmware's factory waves in that bank
//      | {name, waves, uploaded}            64 x 256 floats
const LIB_KEY = 'laniakea-bank-library-v1';
const LINK_KEY = 'laniakea-editor-link-v1';
const moduleFormat = (w) => dsp.toModuleFormat(w, { decimate: $('resample').value === 'dec' });
function encodeBank(w) {            // 64 x 256 floats -> base64 of int16
  const i16 = new Int16Array(WAVES * LEN);
  w.forEach((wave, k) => wave.forEach((v, i) => { i16[k * LEN + i] = Math.max(-32767, Math.min(32767, Math.round(v * 32767))); }));
  let s = ''; const u8 = new Uint8Array(i16.buffer);
  for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode(...u8.subarray(i, i + 0x8000));
  return btoa(s);
}
function decodeBank(b64) {
  const bin = atob(b64); const u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  const i16 = new Int16Array(u8.buffer);
  return Array.from({ length: WAVES }, (_, k) => Float32Array.from(i16.subarray(k * LEN, (k + 1) * LEN), (v) => v / 32767));
}
function loadLibrary() {
  try {
    const raw = JSON.parse(localStorage.getItem(LIB_KEY) || '[]');
    return Array.from({ length: 8 }, (_, i) => {
      const r = raw[i];
      if (!r) return null;
      if (r.factory) return { name: r.name, factory: true, uploaded: !!r.uploaded };
      return { name: r.name, waves: decodeBank(r.data), uploaded: !!r.uploaded };
    });
  } catch { return Array(8).fill(null); }
}
function saveLibrary() {
  try {
    localStorage.setItem(LIB_KEY, JSON.stringify(library.map((s) => (!s ? null
      : s.factory ? { name: s.name, factory: true, uploaded: s.uploaded }
        : { name: s.name, data: encodeBank(s.waves), uploaded: s.uploaded }))));
  } catch (err) { log(`Could not store the banks in this browser: ${err.message}`); }
}
function saveLink() { try { localStorage.setItem(LINK_KEY, JSON.stringify({ editorBank, unsaved, selectedBank })); } catch { /* fine */ } }
function loadLink() { try { return JSON.parse(localStorage.getItem(LINK_KEY) || 'null'); } catch { return null; } }

const library = loadLibrary();
const copyBank = (w) => w.map((x) => Float32Array.from(x));
const link = loadLink() || {};
let selectedBank = link.selectedBank || 1;   // bank the Banks panel acts on
let editorBank = link.editorBank ?? null;    // bank the editor's waves came from / were saved to
let unsaved = !!link.unsaved;                // editor differs from that bank (or isn't in any bank)

const slotLabel = (slot) => (!slot ? 'empty' : slot.name);
function slotStatus(slot, n) {
  if (!slot) return `Empty in this browser. Uploads skip it: the module keeps what its bank ${n} holds (the factory waves until you upload something).`;
  const where = slot.factory ? 'Plays the factory waves built into the firmware.' : 'Stored in this browser.';
  const up = !serial.connected ? '' : slot.uploaded ? ' Uploaded to the module.' : ' Not uploaded to the module yet.';
  return where + up;
}
function drawThumb(slot) {
  const c = $('bank-thumb'), ctx = c.getContext('2d'), W = c.width, Hh = c.height;
  ctx.clearRect(0, 0, W, Hh);
  if (!slot?.waves) {
    ctx.fillStyle = css('--muted'); ctx.font = '13px system-ui, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(slot?.factory ? 'factory waves' : 'empty', W / 2, Hh / 2);
    return;
  }
  const cw = W / 8, ch = Hh / 8;    // the 8x8 grid in miniature
  ctx.strokeStyle = css('--wave'); ctx.lineWidth = 1;
  slot.waves.forEach((w, k) => {
    const x0 = (k % 8) * cw, y0 = Math.floor(k / 8) * ch;
    ctx.beginPath();
    for (let i = 0; i < w.length; i += 4) {
      const x = x0 + 2 + (i / (w.length - 1)) * (cw - 4), y = y0 + ch / 2 - w[i] * (ch / 2 - 1.5);
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.stroke();
  });
}

function renderBanks() {
  const on = serial.connected && !isBusy;
  const tabs = $('bank-tabs');
  tabs.innerHTML = '';
  library.forEach((slot, i) => {
    const n = i + 1;
    const b = Object.assign(document.createElement('button'), { className: `bank-tab${slot ? ' filled' : ''}` });
    b.setAttribute('role', 'tab');
    b.setAttribute('aria-selected', String(n === selectedBank));
    b.title = `Bank ${n}: ${slotLabel(slot)}${moduleBank === n ? ' (playing on the module)' : ''}. Double-click to open it in the editor.`;
    b.innerHTML = `<b>${n}</b><span></span>${moduleBank === n ? '<i class="playing"></i>' : ''}`;
    b.querySelector('span').textContent = slotLabel(slot);
    b.addEventListener('click', () => { selectedBank = n; saveLink(); renderBanks(); });
    b.addEventListener('dblclick', () => { if (library[i]) openSlot(n); });
    tabs.append(b);
  });
  const n = selectedBank, slot = library[n - 1];
  $('bank-title').textContent = `Bank ${n}${slot ? ` · ${slot.name}` : ''}`;
  $('bank-status').textContent = slotStatus(slot, n);
  drawThumb(slot);
  $('btn-store').textContent = `Use editor waves in bank ${n}`;
  $('btn-open').disabled = !slot;
  $('btn-rename').disabled = !slot;
  $('btn-clear').disabled = !slot;
  $('btn-upload-bank').textContent = `Upload bank ${n} to module`;
  $('btn-upload-bank').disabled = !on || !slot;
  $('btn-upload-all').disabled = !on || !library.some(Boolean);
  $('btn-read').disabled = !on;
  const sw = $('switch-tabs');
  sw.innerHTML = '';
  for (let k = 1; k <= 8; k++) {
    const b = Object.assign(document.createElement('button'), { textContent: String(k), className: moduleBank === k ? 'on' : '' });
    b.title = moduleBank === k ? `The module is playing bank ${k}` : `Make the module play bank ${k}`;
    b.disabled = !on;
    b.addEventListener('click', () => busy(async () => { await serial.switchBank(k); moduleBank = k; }));
    sw.append(b);
  }
  const mb = $('module-bank');
  mb.hidden = !serial.connected;
  mb.textContent = moduleBank ? `module: bank ${moduleBank}` : 'module: bank ?';
  mb.className = `pill ${moduleBank ? 'on' : 'off'}`;
  renderEditorStatus();
}
const escapeHtml = (s) => s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
function renderEditorStatus() {
  const st = $('editor-status'), save = $('btn-save-back');
  if (editorBank) {
    const name = library[editorBank - 1]?.name;
    st.innerHTML = `bank ${editorBank}${name ? ` · ${escapeHtml(name)}` : ''}${unsaved ? ' · <span class="unsaved">unsaved changes</span>' : ' · saved'}`;
    save.hidden = !unsaved;
    save.textContent = `Save to bank ${editorBank}`;
  } else {
    st.innerHTML = unsaved ? '<span class="unsaved">not in a bank yet</span>: pick a bank above and click <b>Use editor waves</b>' : '';
    save.hidden = true;
  }
}

function storeEditorIn(n, name) {
  const old = library[n - 1];
  library[n - 1] = { name: name || old?.name || `Bank ${n}`, waves: copyBank(waves), uploaded: false };
  editorBank = n; unsaved = false;
  saveLibrary(); saveLink(); renderBanks();
  log(`Editor waves stored in bank ${n}.`);
}
async function openSlot(n) {
  const slot = library[n - 1];
  if (!slot) return;
  if (unsaved && !confirm(`Open bank ${n}? The editor's unsaved changes are replaced (Ctrl+Z undoes it).`)) return;
  if (slot.factory) {
    await busy(loadFactoryIntoEditor);
    editorBank = n; unsaved = false; saveLink(); renderBanks();
    return;
  }
  pushUndo();
  waves = copyBank(slot.waves);
  editorBank = n; unsaved = false;
  changed(false);
  log(`Editing bank ${n}: ${slot.name}`);
}
$('btn-store').addEventListener('click', () => {
  const n = selectedBank, slot = library[n - 1];
  if (slot && editorBank !== n && !confirm(`Replace bank ${n} (${slot.name}) with the editor's waves?`)) return;
  const name = slot && editorBank === n ? slot.name : prompt(`Name for bank ${n}:`, lastLoadedName || slot?.name || `Bank ${n}`);
  if (name === null) return;
  storeEditorIn(n, name);
});
$('btn-save-back').addEventListener('click', () => { if (editorBank) storeEditorIn(editorBank); });
$('btn-use-factory').addEventListener('click', () => {
  const n = selectedBank, slot = library[n - 1];
  if (slot && !confirm(`Replace bank ${n} (${slot.name}) with the factory waves?`)) return;
  library[n - 1] = { name: 'Factory waves', factory: true, uploaded: false };
  if (editorBank === n) { editorBank = null; unsaved = true; }
  saveLibrary(); saveLink(); renderBanks();
});
$('btn-open').addEventListener('click', () => openSlot(selectedBank));
$('btn-rename').addEventListener('click', () => {
  const slot = library[selectedBank - 1];
  const name = slot && prompt(`Name for bank ${selectedBank}:`, slot.name);
  if (!name) return;
  slot.name = name; saveLibrary(); renderBanks();
});
$('btn-clear').addEventListener('click', () => {
  const n = selectedBank, slot = library[n - 1];
  if (!slot || !confirm(`Clear bank ${n} (${slot.name}) in this browser? The module keeps its bank ${n}.`)) return;
  library[n - 1] = null;
  if (editorBank === n) { editorBank = null; unsaved = true; }
  saveLibrary(); saveLink(); renderBanks();
});

const job = (n) => { const s = library[n - 1]; return s.factory ? { bank: n, factory: true } : { bank: n, waves: moduleFormat(s.waves) }; };
function offerSaveFirst(banks) {
  if (unsaved && editorBank && banks.includes(editorBank)
      && confirm(`Bank ${editorBank} has unsaved changes in the editor. Save them to bank ${editorBank} before uploading?`)) {
    storeEditorIn(editorBank);
  }
}
$('btn-upload-bank').addEventListener('click', () => {
  const n = selectedBank;
  if (!library[n - 1]) return;
  offerSaveFirst([n]);
  busy(async () => {
    progress(0);
    await serial.uploadBanks([job(n)], progress);
    library[n - 1].uploaded = true; moduleBank = n; saveLibrary();
  });
});
$('btn-upload-all').addEventListener('click', () => {
  const banks = library.map((s, i) => (s ? i + 1 : 0)).filter(Boolean);
  if (!banks.length) return;
  offerSaveFirst(banks);
  if (!confirm(`Upload bank(s) ${banks.join(', ')} to the module? This overwrites those banks on the module.`)) return;
  busy(async () => {
    progress(0);
    await serial.uploadBanks(banks.map(job), progress);
    banks.forEach((n) => { library[n - 1].uploaded = true; });
    moduleBank = banks[banks.length - 1]; saveLibrary();
    log('All banks uploaded.');
  });
});

async function loadFactoryIntoEditor() {
  const { officialReleases, downloadOfficial } = await flasherModule();
  const { extractFactoryBank } = await import('./fwimage.js');
  const rel = (await officialReleases()).find((r) => r.version === 'v3.6');
  if (!rel) throw new Error('official v3.6 not found in Magerit\'s manifest');
  const factory = await extractFactoryBank(await downloadOfficial(rel, log));
  pushUndo();
  waves = factory.map((w) => dsp.resampleCycle(Float32Array.from(w, (v) => v / 32767), LEN));
  lastLoadedName = 'Factory waves (edited)';
  changed();
  log('Factory waves loaded into the editor (from the official v3.6 firmware).');
}
$('btn-factory-bank').addEventListener('click', () => busy(async () => { await loadFactoryIntoEditor(); newContent(); }));

// ------------------------------------------------------------------ init
/** The editor now holds a different bank (file, preset, factory): it no longer belongs to a bank slot. */
function newContent() { editorBank = null; unsaved = true; saveLink(); renderEditorStatus(); }
function changed(dirty = true) {
  if (dirty) unsaved = true;
  save(); saveLink(); refreshAll(); renderEditorStatus();
}
function refreshAll() { refreshGrid(); refreshWave(); refreshMorph(); }

buildGrid();
waves = load() || PRESETS.classic();
refreshAll();
setXY(0, 0);
requestAnimationFrame(lfoLoop);
loadReleases();
setConnected(false);
if (!LaniakeaSerial.supported()) {
  $('btn-connect').disabled = true;
  $('btn-backup').disabled = true;
  log('Web Serial is not available in this browser - use Chrome or Edge to upload to the module. Editing and export still work.');
} else {
  log('Ready. Power the module from the rack, connect USB, then click Connect.');
}
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { refreshAll(); renderBanks(); });
