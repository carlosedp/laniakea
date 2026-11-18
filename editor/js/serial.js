// Web Serial implementation of Magerit's Laniakea wave protocol (see re/webupdater/dl-audio-waves.js):
//   reset (RTS pulse, DTR low) -> wait 2 s -> "MAGW" -> ACK(0x06)
//   64 x '{"W":k,"S":[128 int16]}' each answered by ACK
//   "MAGD" -> ACK : restore factory wavetable
// With the "banks" firmware patch (any time, no reset needed):
//   "MAG1".."MAG8" -> ACK : select + save + load a bank
//   "MAGB" -> 'B' '1'..'8' ACK : which bank is playing
//   "MAGR" -> "WAVS" + int16[64][128] little-endian + ACK : the waves playing now
const ACK = 0x06, NACK = 0x15;
const DUMP_BYTES = 64 * 128 * 2;

/** Find a MAGB reply in received bytes -> bank 1..8 or null. */
export function parseBankReply(bytes) {
  for (let i = 2; i < bytes.length; i++) {
    if (bytes[i] === ACK && bytes[i - 2] === 0x42 && bytes[i - 1] >= 0x31 && bytes[i - 1] <= 0x38) return bytes[i - 1] - 0x30;
  }
  return null;
}

/** Find a MAGR reply -> {waves: Array(64) of Int16Array(128)} | {need: true} (incomplete) | {bad: true} (misaligned). */
export function parseDump(bytes) {
  for (let i = 0; i + 4 <= bytes.length; i++) {
    if (bytes[i] !== 0x57 || bytes[i + 1] !== 0x41 || bytes[i + 2] !== 0x56 || bytes[i + 3] !== 0x53) continue;  // "WAVS"
    const start = i + 4;
    if (bytes.length < start + DUMP_BYTES + 1) return { need: true };
    if (bytes[start + DUMP_BYTES] !== ACK) return { bad: true };
    const dv = new DataView(bytes.buffer, bytes.byteOffset + start, DUMP_BYTES);
    return { waves: Array.from({ length: 64 }, (_, w) => Int16Array.from({ length: 128 }, (_, k) => dv.getInt16((w * 128 + k) * 2, true))) };
  }
  return { need: true };
}
const FILTERS = [{ usbVendorId: 0x1a86 }, { usbVendorId: 0x10c4 }, { usbVendorId: 0x303a }];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export class LaniakeaSerial {
  constructor(log = () => {}) {
    this.port = null;
    this.reader = null;
    this.queue = [];
    this.pending = null;
    this.log = log;
    this.onText = null; // console output callback
  }

  static supported() { return 'serial' in navigator; }

  /** Close the port and hand the SerialPort object to someone else (e.g. the firmware flasher). */
  async release() {
    const p = this.port;
    await this.disconnect();
    return p;
  }

  async connect(port = null) {
    this.port = port || await navigator.serial.requestPort({ filters: FILTERS });
    await this.port.open({ baudRate: 115200 });
    // Do not hold the chip in reset / bootloader.
    await this.port.setSignals({ dataTerminalReady: false, requestToSend: false });
    this.reader = this.port.readable.getReader();
    this.port.addEventListener('disconnect', () => { this.log('Device disconnected'); this.port = null; });
    const info = this.port.getInfo();
    this.log(`Connected (USB ${info.usbVendorId?.toString(16)}:${info.usbProductId?.toString(16)})`);
  }

  get connected() { return !!this.port; }

  async disconnect() {
    try { await this.reader?.cancel(); } catch { /* closing */ }
    try { this.reader?.releaseLock(); } catch { /* closing */ }
    try { await this.port?.close(); } catch { /* closing */ }
    this.port = null; this.reader = null; this.queue = []; this.pending = null;
  }

  async write(data) {
    const w = this.port.writable.getWriter();
    try { await w.write(typeof data === 'string' ? new TextEncoder().encode(data) : data); }
    finally { w.releaseLock(); }
  }

  /** Read one byte with timeout; keeps a single pending read() across timeouts. */
  async readByte(timeoutMs) {
    if (this.queue.length) return this.queue.shift();
    if (!this.pending) this.pending = this.reader.read();
    const r = await Promise.race([this.pending, sleep(timeoutMs).then(() => 'timeout')]);
    if (r === 'timeout') return null;
    this.pending = null;
    if (r.done || !r.value?.length) return null;
    this.queue = Array.from(r.value);
    if (this.onText) this.onText(new TextDecoder().decode(r.value));
    return this.queue.shift();
  }

  /** Collect incoming bytes until done(bytes) returns something non-null, or timeout. */
  async collect(done, timeoutMs) {
    const got = [];
    const t0 = performance.now();
    while (performance.now() - t0 < timeoutMs) {
      const b = await this.readByte(Math.max(1, timeoutMs - (performance.now() - t0)));
      if (b === null) break;
      got.push(b);
      if (this.queue.length) { got.push(...this.queue); this.queue = []; }
      const r = done(Uint8Array.from(got));
      if (r !== null && r !== undefined) return r;
    }
    return null;
  }

  async drain(ms = 50) { this.queue = []; while ((await this.readByte(ms)) !== null) { this.queue = []; } }

  async reset() {
    await this.port.setSignals({ dataTerminalReady: false, requestToSend: true });
    await sleep(150);
    await this.port.setSignals({ dataTerminalReady: false, requestToSend: false });
    await sleep(200);
  }

  async waitAck(timeoutMs = 2000) {
    const t0 = performance.now();
    while (performance.now() - t0 < timeoutMs) {
      const b = await this.readByte(timeoutMs - (performance.now() - t0));
      if (b === ACK) return true;
      if (b === NACK) return false;
      if (b === null) return false;
    }
    return false;
  }

  async handshake(magic, tries = 5) {
    await this.drain();
    for (let i = 0; i < tries; i++) {
      await this.write(magic);
      if (await this.waitAck(300)) return true;
    }
    return false;
  }

  /** 'MAG1'..'MAG8' (banks firmware patch): select + save + load a bank. Sent once: the module
   *  answers after saving and loading (up to ~1 s, longer right after an upload). */
  async selectBank(bank) {
    await this.drain();
    await this.write(`MAG${bank}`);
    if (!(await this.waitAck(5000))) throw new Error(`Module did not confirm bank ${bank} - flash a firmware with the "banks" patch`);
    this.log(`Bank ${bank} selected.`);
  }

  /** 'MAGB' (banks patch): bank playing now (1..8), or null (no answer: stock firmware / not booted). */
  async queryBank(tries = 3) {
    for (let i = 0; i < tries; i++) {
      await this.drain(20);
      await this.write('MAGB');
      const bank = await this.collect(parseBankReply, 500);
      if (bank) return bank;
    }
    return null;
  }

  /** 'MAGR' (banks patch): the waves playing now -> Array(64) of Int16Array(128). */
  async readWaves(onProgress = () => {}) {
    for (let i = 0; i < 2; i++) {
      await this.drain(20);
      await this.write('MAGR');
      const r = await this.collect((b) => { onProgress(Math.min(1, b.length / DUMP_BYTES)); const d = parseDump(b); return d.need ? null : d; }, 5000);
      if (r?.waves) return r.waves;
    }
    throw new Error('Module did not send its waves - flash a firmware with the "banks" patch');
  }

  /** Bank commands work at any time with the banks patch; reset only if the module doesn't answer. */
  async ensureAwake() {
    if (await this.queryBank(1)) return;
    this.log('Resetting module...');
    await this.reset();
    await sleep(2000);
  }

  async sendWaves(waves, onProgress, label = '') {
    if (!(await this.handshake('MAGW'))) throw new Error('Module did not answer MAGW (powered from the rack? Laniakea firmware running?)');
    for (let k = 0; k < waves.length; k++) {
      await this.write(`{"W":${k},"S":[${waves[k].join(',')}]}`);
      if (!(await this.waitAck(2000))) throw new Error(`No ACK after wave ${k}${label}`);
      onProgress((k + 1) / waves.length);
    }
  }

  /** waves: Array(64) of Array(128) int16. bank: 1..8 or null (= bank currently loaded on the module) */
  async uploadWaves(waves, onProgress = () => {}, bank = null) {
    await this.uploadBanks([{ bank, waves }], onProgress);
  }

  /** jobs: [{bank, waves} | {bank, factory: true}]. One reset, then per bank: select + upload
   *  (or restore the factory waves). The module saves each bank before it reads the next
   *  command, so banks never mix. */
  async uploadBanks(jobs, onProgress = () => {}) {
    this.log('Resetting module...');
    await this.reset();
    await sleep(2000);
    for (let j = 0; j < jobs.length; j++) {
      const { bank, waves, factory } = jobs[j];
      if (bank) await this.selectBank(bank);
      if (factory) {
        if (!(await this.handshake('MAGD'))) throw new Error('Module did not answer MAGD');
        this.log(`Bank ${bank}: factory waves restored.`);
      } else {
        await this.sendWaves(waves, (p) => onProgress((j + p) / jobs.length), bank ? ` (bank ${bank})` : '');
        this.log(bank ? `Bank ${bank} uploaded.` : 'Waves uploaded to the current bank.');
      }
      onProgress((j + 1) / jobs.length);
    }
  }

  async restoreFactory(bank = null) {
    this.log('Resetting module...');
    await this.reset();
    await sleep(2000);
    if (bank) await this.selectBank(bank);
    if (!(await this.handshake('MAGD'))) throw new Error('Module did not answer MAGD');
    this.log(bank ? `Factory waves restored in bank ${bank}.` : 'Factory wavetable restored.');
  }

  async switchBank(bank) {
    await this.ensureAwake();
    await this.selectBank(bank);
  }
}
