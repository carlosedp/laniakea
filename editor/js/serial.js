// Web Serial implementation of Magerit's Laniakea wave protocol (see re/webupdater/dl-audio-waves.js):
//   reset (RTS pulse, DTR low) -> wait 2 s -> "MAGW" -> ACK(0x06)
//   64 x '{"W":k,"S":[128 int16]}' each answered by ACK
//   "MAGD" -> ACK : restore factory wavetable
const ACK = 0x06, NACK = 0x15;
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

  /** waves: Array(64) of Array(128) int16 */
  async uploadWaves(waves, onProgress = () => {}) {
    this.log('Resetting module...');
    await this.reset();
    await sleep(2000);
    if (!(await this.handshake('MAGW'))) throw new Error('Module did not answer MAGW (powered from the rack? Laniakea firmware running?)');
    for (let k = 0; k < waves.length; k++) {
      await this.write(`{"W":${k},"S":[${waves[k].join(',')}]}`);
      if (!(await this.waitAck(2000))) throw new Error(`No ACK after wave ${k}`);
      onProgress((k + 1) / waves.length);
    }
    this.log('Waves uploaded.');
  }

  async restoreFactory() {
    this.log('Resetting module...');
    await this.reset();
    await sleep(2000);
    if (!(await this.handshake('MAGD'))) throw new Error('Module did not answer MAGD');
    this.log('Factory wavetable restored.');
  }
}
