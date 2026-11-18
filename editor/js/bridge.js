// Module access through the `laniakea editor` server (tools/editor_bridge.py), which uses the
// CLI's pyserial/esptool code. Same interface as LaniakeaSerial (serial.js), which stays the
// fallback when the editor is opened without that server.

async function call(name, body = {}) {
  const r = await fetch(`/api/${name}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  let res;
  try { res = await r.json(); } catch { throw new Error(`bridge: HTTP ${r.status}`); }
  return res;
}

export class BridgeSerial {
  constructor(log = () => {}) {
    this.log = log;
    this.port = null;
    this.lastError = '';
  }

  /** True when the page is served by `laniakea editor`. */
  static async available() {
    try {
      const r = await fetch('/api/hello', { cache: 'no-store' });
      return r.ok && (await r.json()).bridge >= 1;
    } catch { return false; }
  }

  get connected() { return !!this.port; }
  get usesBridge() { return true; }

  async op(name, body, onProgress) {
    let timer = null;
    if (onProgress) {
      timer = setInterval(async () => {
        try { const p = (await (await fetch('/api/progress', { cache: 'no-store' })).json()).progress; if (p !== null) onProgress(p); } catch { /* ignore */ }
      }, 250);
    }
    try {
      const res = await call(name, body);
      (res.log || []).forEach((m) => this.log(m));
      if (res.error) {
        this.lastError = res.error;
        if (/not connected|SerialException|PermissionError|could not open/i.test(res.error)) this.port = null;
        throw new Error(res.error);
      }
      return res;
    } finally { if (timer) clearInterval(timer); }
  }

  async connect() {
    const { port } = await this.op('connect');
    this.port = port;
    this.log(`Connected to ${port} (through the laniakea editor server)`);
  }

  async disconnect() {
    try { await call('disconnect'); } finally { this.port = null; }
  }

  /** The flasher takes over the port: close ours. Returns null (bridge flashing doesn't need a SerialPort). */
  async release() { await this.disconnect(); return null; }

  rxNote() { return this.lastError ? ` (${this.lastError})` : ''; }

  async queryBank() {
    try { return (await this.op('bank')).bank || null; } catch { return null; }
  }

  async readWaves(onProgress = () => {}) {
    onProgress(0.5);
    const { waves } = await this.op('read');
    onProgress(1);
    return waves.map((w) => Int16Array.from(w));
  }

  async selectBank(bank) { await this.op('select', { bank }); }
  async switchBank(bank) { await this.op('select', { bank }); }

  /** jobs: [{bank, waves: Array(64) of Array(128) int16} | {bank, factory: true}] */
  async uploadBanks(jobs, onProgress = () => {}) {
    this.log('Uploading (the module resets first)...');
    await this.op('upload', { jobs }, onProgress);
  }

  async uploadWaves(waves, onProgress = () => {}, bank = null) { await this.uploadBanks([{ bank, waves }], onProgress); }

  async restoreFactory(bank = null) { await this.uploadBanks([{ bank, factory: true }]); }

  /** Flash a merged image with esptool on the server (calibration/NVS untouched). */
  async flash(bytes, name) {
    let s = '';
    for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    this.port = null;
    await this.op('flash', { image: btoa(s), name });
  }

  /** Full flash dump saved by the server into firmware/backup/. Returns the path. */
  async backup() {
    this.port = null;
    return (await this.op('backup')).path;
  }
}
