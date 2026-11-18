// Web patcher: runs the repository's Python patch code (tools/, patches/) under Pyodide and
// flashes the result with the editor's esptool-js updater (../editor/js/flasher.js).
import { flashFirmware, backupFlash, inspectFirmware } from '../editor/js/flasher.js';
import { sha256Hex } from '../editor/js/fwimage.js';

const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.mjs';
const TOOLS = ['patcher.py', 'patchlib.py', 'espimage.py', 'symbols.py', 'xtasm.py', 'webpatch.py'];
const RECOMMENDED_OFF_NOTE = 'diagnostic patches are only in the command-line tool';

const $ = (id) => document.getElementById(id);
const el = (tag, props = {}, ...kids) => {
  const e = Object.assign(document.createElement(tag), props);
  for (const k of kids) e.append(k);
  return e;
};

let py = null;            // Pyodide instance
let catalog = null;       // {patches, presets, known}
let base = null;          // {bytes, version, name}
let built = null;         // {bytes, name}
let port = null;          // remembered SerialPort
let exampleChords = '';

// ------------------------------------------------------------------ Python runtime
async function fetchText(url) {
  const r = await fetch(url, { cache: 'no-cache' });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.text();
}

async function startPython() {
  const status = $('py-status');
  try {
    const { loadPyodide } = await import(PYODIDE);
    const [pyo, ...tools] = await Promise.all([loadPyodide(), ...TOOLS.map((f) => fetchText(`../tools/${f}`))]);
    py = pyo;
    py.FS.mkdirTree('/lk/tools'); py.FS.mkdirTree('/lk/patches'); py.FS.mkdirTree('/work');
    TOOLS.forEach((f, i) => py.FS.writeFile(`/lk/tools/${f}`, tools[i]));
    // the patch list lives in tools/webpatch.py (WEB_PATCHES), so this page never drifts from it
    const names = JSON.parse(tools[TOOLS.indexOf('webpatch.py')].match(/WEB_PATCHES = (\[[^\]]*\])/)[1].replace(/'/g, '"'));
    const srcs = await Promise.all(names.map((n) => fetchText(`../patches/${n}.py`)));
    names.forEach((n, i) => py.FS.writeFile(`/lk/patches/${n}.py`, srcs[i]));
    exampleChords = await fetchText('../patches/chord_sets/example.txt').catch(() => '');
    py.runPython('import sys; sys.path.insert(0, "/lk/tools"); import webpatch');
    catalog = JSON.parse(py.runPython('webpatch.catalog()'));
    renderPatches();
    status.textContent = 'patcher ready'; status.className = 'pill on';
    if (base) await identify();
    updateButtons();
  } catch (e) {
    status.textContent = 'patcher failed to load'; status.className = 'pill off';
    $('patch-list').replaceChildren(el('p', { className: 'hint', textContent: `Could not load the Python runtime: ${e.message}` }));
    console.error(e);
  }
}

// ------------------------------------------------------------------ step 1: firmware
function fwInfo(html, cls = '') {
  const box = $('fw-info');
  box.hidden = false; box.className = `fw-info ${cls}`;
  box.innerHTML = html;
}

async function setBase(bytes, name) {
  base = null; built = null;
  $('btn-save').disabled = true; $('build-name').textContent = '';
  let info;
  try { info = await inspectFirmware(bytes); } catch (e) {
    fwInfo(`<b class="bad">Not usable:</b> ${e.message}`, 'bad'); updateButtons(); return;
  }
  base = { bytes, name, info, sha: await sha256Hex(bytes), version: null };
  await identify();
  updateButtons();
}

async function identify() {
  if (!base) return;
  const { info, sha, name } = base;
  const desc = `<span class="mono">${name}</span> · built ${info.date} · ${info.size.toLocaleString()} bytes`;
  if (!catalog) { fwInfo(`${desc}<br>Checking… (waiting for the patcher to load)`); return; }
  const v = catalog.known[sha];
  if (v) {
    base.version = v;
    fwInfo(`<b class="ok">✓ Official Laniakea v${v}</b>: ${desc}<br><small>SHA-256 ${sha}</small>`, 'ok');
  } else {
    const patched = info.version.includes('+');
    fwInfo(`<b class="bad">✗ Can't patch this file.</b> ${desc} · app version "${info.version}"<br>` +
      (patched ? 'This is already a patched build. Start from the unmodified official image.'
               : `Only the official v${[...new Set(Object.values(catalog.known))].sort().join(' and v')} images are supported (exact SHA-256 match).`) +
      `<br><small>SHA-256 ${sha}</small>`, 'bad');
  }
  renderTargets();
}

function setupDrop() {
  const drop = $('drop');
  const take = async (file) => { if (file) await setBase(new Uint8Array(await file.arrayBuffer()), file.name); };
  $('fw-file').onchange = (e) => take(e.target.files[0]);
  drop.onclick = () => $('fw-file').click();
  drop.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') $('fw-file').click(); };
  for (const t of [drop, document.body]) {
    t.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
    t.addEventListener('dragleave', () => drop.classList.remove('over'));
    t.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('over'); take(e.dataTransfer.files[0]); });
  }
}

// ------------------------------------------------------------------ step 2: patches
const state = {};   // name -> {on, values}

function optionInput(p, o) {
  const id = `opt-${p.name}-${o.key}`;
  const v = state[p.name].values;
  const wrap = el('div', { className: 'opt' }, el('label', { htmlFor: id, textContent: o.key }));
  let input;
  if (o.type === 'bool') {
    input = el('select', { id }, el('option', { value: 'true', textContent: 'yes' }), el('option', { value: 'false', textContent: 'no' }));
    input.value = String(v[o.key]);
  } else if (o.choices) {
    input = el('select', { id }, ...o.choices.map((c) => el('option', { value: c, textContent: c })));
    input.value = String(v[o.key]);
  } else {
    input = el('input', { id, type: o.type === 'str' ? 'text' : 'number', value: v[o.key] });
    if (o.type === 'float') input.step = 'any';
    if (o.range) [input.min, input.max] = o.range;
  }
  input.oninput = () => { v[o.key] = input.value; onPatchChange(p); };
  input.onchange = () => {                       // typed values: clamp to the patch's range
    if (o.range && input.value !== '') {
      const [lo, hi] = o.range;
      let x = Math.min(hi, Math.max(lo, Number(input.value)));
      if (o.type === 'int') x = Math.round(x);
      input.value = x;
    }
    input.oninput();
  };
  wrap.append(input, el('small', { textContent: `${o.help} (default ${o.default}${o.range ? `, ${o.range[0]}–${o.range[1]}` : ''})` }));

  if (p.name === 'quantizer' && o.key === 'scales') {         // scale chips: click to add/remove
    wrap.classList.add('wide');
    const chips = el('div', { className: 'chips' });
    const refresh = () => {
      const used = input.value.split(',').map((s) => s.trim()).filter(Boolean);
      for (const b of chips.children) b.classList.toggle('used', used.includes(b.textContent));
    };
    for (const name of p.library) {
      chips.append(el('button', {
        type: 'button', textContent: name, onclick: () => {
          let used = input.value.split(',').map((s) => s.trim()).filter(Boolean);
          used = used.includes(name) ? used.filter((x) => x !== name) : [...used, name].slice(0, 15);
          input.value = used.join(','); input.oninput(); refresh();
        },
      }));
    }
    input.addEventListener('input', refresh); refresh();
    wrap.append(chips);
  }
  if (p.name === 'chords' && o.key === 'set') {               // custom chord text
    const ta = el('textarea', { id: 'chord-text', value: state.chords.text ?? exampleChords, spellcheck: false });
    const box = el('div', { className: 'opt wide', id: 'chord-box' }, el('label', { htmlFor: 'chord-text', textContent: 'custom chords (up to 16 lines: "name: semitones…")' }), ta);
    ta.oninput = () => { state.chords.text = ta.value; };
    const show = () => { box.hidden = input.value !== 'custom'; };
    input.addEventListener('change', show);
    queueMicrotask(() => { wrap.after(box); show(); });
  }
  return wrap;
}

function renderPatches() {
  const list = $('patch-list');
  list.replaceChildren();
  for (const p of catalog.patches) {
    state[p.name] = { on: false, values: Object.fromEntries(p.options.map((o) => [o.key, o.default])) };
    const cb = el('input', { type: 'checkbox', id: `p-${p.name}` });
    const card = el('div', { className: 'patch', id: `card-${p.name}` },
      el('label', { htmlFor: cb.id }, cb, el('b', { textContent: p.name }), el('span', { className: 'desc', textContent: p.description }),
        el('small', { className: 'targets' })),
      el('details', {}, el('summary', { textContent: 'details' }), el('pre', { textContent: p.doc })),
    );
    if (p.options.length) card.append(el('div', { className: 'opts' }, ...p.options.map((o) => optionInput(p, o))));
    cb.onchange = () => { state[p.name].on = cb.checked; card.classList.toggle('on', cb.checked); onPatchChange(p); };
    list.append(card);
  }
  list.append(el('p', { className: 'hint', textContent: `Options are applied in each patch's own order; ${RECOMMENDED_OFF_NOTE}.` }));
  applyPreset('recommended');
  renderTargets();
}

function renderTargets() {
  if (!catalog) return;
  for (const p of catalog.patches) {
    const t = document.querySelector(`#card-${p.name} .targets`);
    const bad = base?.version && !p.targets.includes(base.version);
    t.textContent = bad ? ` (not for v${base.version})` : '';
  }
}

function setOn(name, on) {
  const cb = $(`p-${name}`);
  cb.checked = on; cb.onchange();
}

function applyPreset(which) {
  for (const p of catalog.patches) setOn(p.name, false);
  if (which === 'all') {
    for (const p of catalog.patches) if (p.name !== 'quiet') setOn(p.name, true);
  } else if (which === 'recommended') {
    for (const { name, values } of catalog.presets.recommended) {
      Object.assign(state[name].values, values);
      setOn(name, true);
    }
  }
}

function onPatchChange() {
  built = null; $('btn-save').disabled = true; $('build-name').textContent = '';
  updateButtons();
}

// ------------------------------------------------------------------ step 3: build
function log(pre, line, err = false) {
  pre.hidden = false;
  const s = el('span', { textContent: line + '\n' });
  if (err) s.className = 'err';
  pre.append(s); pre.scrollTop = pre.scrollHeight;
}

async function build() {
  const out = $('build-log');
  out.replaceChildren();
  const selection = catalog.patches.filter((p) => state[p.name].on).map((p) => {
    const values = { ...state[p.name].values };
    if (p.name === 'chords' && values.set === 'custom') {
      py.FS.writeFile('/work/custom.txt', state.chords.text ?? exampleChords);
      values.set = '/work/custom.txt';
    }
    return { name: p.name, values };
  });
  if (!selection.length) { log(out, 'Select at least one patch.', true); return; }
  $('btn-build').disabled = true;
  log(out, `Building from official v${base.version}…`);
  await new Promise((r) => setTimeout(r, 30));   // let the UI paint
  try {
    py.FS.writeFile('/work/base.bin', base.bytes);
    py.globals.set('sel_json', JSON.stringify(selection));
    const res = JSON.parse(py.runPython('webpatch.build("/work/base.bin", sel_json, "/work/out.bin")'));
    for (const l of res.log || []) log(out, l);
    if (res.error) throw new Error(res.error);
    const bytes = py.FS.readFile('/work/out.bin');
    const info = await inspectFirmware(bytes);     // independent JS check: checksum + SHA-256 + descriptor
    built = { bytes: new Uint8Array(bytes), name: res.name };
    log(out, `✓ ${res.name}: ${bytes.length.toLocaleString()} bytes, version "${info.version}", checksum and SHA-256 valid`);
    $('build-name').textContent = res.name;
    $('btn-save').disabled = false;
  } catch (e) {
    log(out, `✗ ${e.message}`, true);
  }
  updateButtons();
}

function download(bytes, name) {
  const a = el('a', { href: URL.createObjectURL(new Blob([bytes], { type: 'application/octet-stream' })), download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

// ------------------------------------------------------------------ step 4: flash
let busy = false;
async function withSerial(fn) {
  const pre = $('flash-log');
  pre.replaceChildren();
  busy = true; updateButtons();
  $('fl-progress').hidden = false; $('fl-bar').style.width = '0';
  const onProgress = (f) => { $('fl-bar').style.width = `${Math.round(f * 100)}%`; };
  try {
    await fn({ log: (s) => log(pre, s), onProgress });
  } catch (e) {
    log(pre, `✗ ${e.message}`, true);
    if (/No port selected|cancel/i.test(e.message)) port = null;
  }
  busy = false; updateButtons();
}

const flash = (bytes, what) => withSerial(async ({ log: l, onProgress }) => {
  if (!confirm(`Flash ${what} to the module?\n\nThe module must be powered from the rack. Calibration and settings are kept.`)) return;
  port = await flashFirmware({ port, bytes, log: l, onProgress });
});

const backup = () => withSerial(async ({ log: l, onProgress }) => {
  const res = await backupFlash({ port, log: l, onProgress });
  port = res.port;
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
  download(res.data, `laniakea_backup_${stamp}.bin`);
  l('Backup saved. Keep it safe: it contains your calibration.');
});

// ------------------------------------------------------------------ wiring
function updateButtons() {
  const okBase = !!(base && base.version);
  $('btn-build').disabled = !(py && okBase) || busy;
  const serial = 'serial' in navigator;
  $('serial-missing').hidden = serial;
  $('btn-flash').disabled = !serial || !built || busy;
  $('btn-official').disabled = !serial || !base || busy;
  $('btn-backup').disabled = !serial || busy;
}

$('btn-recommended').onclick = () => catalog && applyPreset('recommended');
$('btn-all').onclick = () => catalog && applyPreset('all');
$('btn-none').onclick = () => catalog && applyPreset('none');
$('btn-build').onclick = build;
$('btn-save').onclick = () => built && download(built.bytes, built.name);
$('btn-flash').onclick = () => built && flash(built.bytes, built.name);
$('btn-official').onclick = () => base && flash(base.bytes, `the unmodified official ${base.name}`);
$('btn-backup').onclick = backup;

setupDrop();
updateButtons();
startPython();
