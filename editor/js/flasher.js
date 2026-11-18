// Browser firmware updater for the Laniakea (Web Serial + Espressif's esptool-js).
// Same procedure as Magerit's web updater and tools/laniakea.py `flash`: write the merged
// image at 0x0 (bootloader + partition table + app), leaving the NVS partition untouched.
import { ESPLoader, Transport } from 'https://unpkg.com/esptool-js@0.7.0/bundle.js';
import { inspectFirmware, sha256Hex, md5, NVS_OFFSET } from './fwimage.js';

const MANIFEST_URL = 'https://raw.githubusercontent.com/mageritsynth/binaries/main/manifest.json';
const FILTERS = [{ usbVendorId: 0x1a86 }, { usbVendorId: 0x10c4 }, { usbVendorId: 0x303a }];
const FAST_BAUD = 460800;   // CH340 handles this fine (Magerit uses it too)
const FLASH_SIZE = 0x400000;

/** Official Laniakea releases from Magerit's public manifest (newest first). */
export async function officialReleases() {
  const r = await fetch(MANIFEST_URL, { cache: 'no-store' });
  if (!r.ok) throw new Error(`manifest: HTTP ${r.status}`);
  const m = (await r.json()).modules.find((x) => x.slug === 'laniakea');
  return [m.current, ...(m.history || [])];
}

/** Download an official release and verify its sha256 against the manifest. */
export async function downloadOfficial(release, log) {
  log(`Downloading official ${release.version} from Magerit's GitHub...`);
  const r = await fetch(release.url);
  if (!r.ok) throw new Error(`download: HTTP ${r.status}`);
  const bytes = new Uint8Array(await r.arrayBuffer());
  if ((await sha256Hex(bytes)) !== release.sha256) throw new Error('sha256 mismatch - download corrupted');
  log(`sha256 OK (${bytes.length} bytes)`);
  return bytes;
}

export { inspectFirmware };

async function connectLoader(port, log) {
  const transport = new Transport(port, false);
  const terminal = { clean() {}, writeLine: (s) => log(s), write: () => {} };
  const loader = new ESPLoader({ transport, baudrate: FAST_BAUD, romBaudrate: 115200, terminal });
  log('Connecting to the bootloader (module must be powered from the rack)...');
  const chip = await loader.main('default_reset');
  log(`Connected: ${chip}`);
  // chip family (e.g. "ESP32" for an ESP32-PICO-D4), not the description string
  if (loader.chip?.CHIP_NAME !== 'ESP32') throw new Error(`unexpected chip "${chip}" - Laniakea uses an ESP32`);
  return { transport, loader };
}

async function pickPort(existingPort) {
  return existingPort || navigator.serial.requestPort({ filters: FILTERS });
}

/** Flash a merged image at 0x0. `port` = an existing (closed) SerialPort, or null to ask the user. */
export async function flashFirmware({ port, bytes, log, onProgress }) {
  const info = await inspectFirmware(bytes);
  if (bytes.length > NVS_OFFSET) throw new Error('image larger than the app area');
  const sp = await pickPort(port);
  const { transport, loader } = await connectLoader(sp, log);
  try {
    log(`Writing ${info.project} ${info.version} (${bytes.length} bytes)...`);
    await loader.writeFlash({
      fileArray: [{ data: bytes, address: 0x0 }],
      flashMode: 'keep', flashFreq: 'keep', flashSize: 'keep',
      eraseAll: false, compress: true,
      reportProgress: (_i, written, total) => onProgress(written / total),
      calculateMD5Hash: (img) => md5(img),
    });
    log('Write verified (MD5). Resetting the module...');
    await loader.after('hard_reset');
  } finally {
    await transport.disconnect();
  }
  log('Done. If the LEDs stay dark, power-cycle the rack.');
  return sp;
}

/** Read the whole 4 MB flash (incl. calibration) and return it. */
export async function backupFlash({ port, log, onProgress }) {
  const sp = await pickPort(port);
  const { transport, loader } = await connectLoader(sp, log);
  try {
    log('Reading 4 MB of flash (about 2 minutes)...');
    const data = await loader.readFlash(0, FLASH_SIZE, (_pkt, progress, total) => onProgress(progress / total));
    await loader.after('hard_reset');
    return { port: sp, data };
  } finally {
    await transport.disconnect();
  }
}
