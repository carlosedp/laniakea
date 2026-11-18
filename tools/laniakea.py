"""Local toolbox for the Magerit Laniakea (ESP32) eurorack module.

The module must be powered from the eurorack rails: USB only powers the CH340
USB-serial bridge, not the ESP32.

  python tools/laniakea.py ports                     list serial ports
  python tools/laniakea.py fetch [--pro]             download official firmware (+ verify sha256)
  python tools/laniakea.py info                      chip / flash / MAC / eFuse summary (read-only)
  python tools/laniakea.py backup                    full 4 MB flash dump -> firmware/backup/
  python tools/laniakea.py flash v3.6 | FILE.bin     flash a merged image at 0x0 (keeps NVS/calibration)
  python tools/laniakea.py restore BACKUP.bin        write a full flash dump back (incl. NVS)
  python tools/laniakea.py waves upload FILE.wav     upload a 64x256 wavetable (WaveEdit format)
  python tools/laniakea.py waves default             restore the factory wavetable
  python tools/laniakea.py waves upload F.wav --bank 3   upload into bank 3 (banks patch)
  python tools/laniakea.py waves banks 1=a.wav 2=b.wav  fill several banks in one go
  python tools/laniakea.py waves select --bank 2      switch the module to bank 2
  python tools/laniakea.py waves current             which bank is the module playing? (banks patch)
  python tools/laniakea.py waves read [--bank N] -o F.wav   read a bank back from the module (banks patch)
  python tools/laniakea.py akwf fetch bw_perfectwaves fmsynth   download AKWF single cycles (CC0)
  python tools/laniakea.py bank DIR [DIR...] -o out.wav          build a 64-wave bank from single cycles
  python tools/laniakea.py monitor                   serial console
  python tools/laniakea.py editor                    start the local wavetable editor
  python tools/laniakea.py patcher list|build ...    firmware patches (same as tools/patcher.py)
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import espimage  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FW_DIR = ROOT / "firmware"
OFFICIAL = FW_DIR / "official"
BACKUPS = FW_DIR / "backup"
MANIFEST_URL = "https://raw.githubusercontent.com/mageritsynth/binaries/main/manifest.json"

# USB-serial bridges / native USB used on ESP32 boards
KNOWN_USB = {(0x1A86, 0x7523): "CH340", (0x1A86, 0x55D4): "CH9102", (0x10C4, 0xEA60): "CP210x",
             (0x303A, 0x1001): "ESP USB-JTAG"}

ACK, NACK = 0x06, 0x15
WAVES, WAVE_LEN = 64, 128          # what the firmware stores
SRC_WAVE_LEN = 256                 # WaveEdit / Magerit .wav format
FLASH_BAUD = 460800                # CH340 bridge handles this fine (same as web updater)


# --------------------------------------------------------------------------- helpers
class CliError(SystemExit):
    """A user-facing error: exits the CLI with status 1; the editor bridge reports .msg instead."""
    def __init__(self, msg: str):
        super().__init__(1)
        self.msg = msg


def die(msg: str):
    print(f"error: {msg}", file=sys.stderr)
    raise CliError(msg)


def find_port(explicit: str | None) -> str:
    if explicit:
        return explicit
    from serial.tools import list_ports
    hits = [p for p in list_ports.comports() if (p.vid, p.pid) in KNOWN_USB]
    if sys.platform == "darwin":          # macOS lists each device as /dev/cu.* and /dev/tty.*: use cu
        cu = [p for p in hits if p.device.startswith("/dev/cu.")]
        hits = cu or hits
    if not hits:
        hint = (" On Linux, check `ls /dev/ttyUSB*`; on Ubuntu the brltty package can grab CH340 devices"
                " (sudo apt remove brltty).") if sys.platform.startswith("linux") else ""
        die("no CH340/CP210x/ESP serial port found - is the USB cable connected? (use --port)" + hint)
    if len(hits) > 1:
        die("several candidate ports: " + ", ".join(p.device for p in hits) + " - pick one with --port")
    return hits[0].device


def port_busy(port: str) -> bool:
    import serial
    try:
        open_serial(port).close()          # opens without toggling DTR/RTS (no reset)
        return False
    except serial.SerialException as e:
        msg = str(e).lower()
        if sys.platform.startswith("linux") and "permission denied" in msg:
            die(f"no permission to open {port}: add yourself to the serial group and log in again:\n"
                f"    sudo usermod -aG dialout $USER      (Arch/Fedora: group 'uucp')")
        return "denied" in msg or "busy" in msg


def esptool(*args, port: str, baud: int = 115200, check=True) -> subprocess.CompletedProcess:
    if port_busy(port):
        die(f"{port} is in use by another program (wavetable editor tab, serial monitor, Arduino IDE...). Close it and retry.")
    cmd = [sys.executable, "-m", "esptool", "--chip", "esp32", "--port", port, "--baud", str(baud), *args]
    print("$ esptool " + " ".join(args))
    r = subprocess.run(cmd)
    if check and r.returncode != 0:
        die("esptool failed. Is the module powered from the eurorack rails? (USB alone does not power the ESP32)")
    return r


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(refresh=False) -> dict:
    local = OFFICIAL / "manifest.json"
    if refresh or not local.exists():
        OFFICIAL.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(MANIFEST_URL) as r:
            local.write_bytes(r.read())
    return json.loads(local.read_text(encoding="utf-8"))


def module_entry(manifest: dict, slug: str) -> dict:
    for m in manifest["modules"]:
        if m["slug"] == slug:
            return m
    die(f"{slug} not in manifest")


def all_versions(entry: dict) -> list[dict]:
    return [entry["current"], *entry.get("history", [])]


def open_serial(port: str, baud=115200, timeout=0.1):
    """Open without toggling DTR/RTS (which would reset or hold the ESP32 in reset)."""
    import serial
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = port, baud, timeout
    s.dtr = False
    s.rts = False
    try:
        s.open()
    except serial.SerialException as e:
        if "denied" in str(e).lower() or "busy" in str(e).lower():
            die(f"{port} is in use by another program (wavetable editor tab, serial monitor...). Disconnect/close it and retry.")
        raise
    return s


def hard_reset(s):
    """EN pulse via RTS with GPIO0 (DTR) high -> normal boot. Same as Magerit's reiniciarChip()."""
    s.dtr = False
    s.rts = True
    time.sleep(0.15)
    s.rts = False
    time.sleep(0.2)


def latest_backup() -> Path | None:
    files = sorted(BACKUPS.glob("laniakea_*.bin"))
    return files[-1] if files else None


# --------------------------------------------------------------------------- commands
def cmd_ports(a):
    from serial.tools import list_ports
    for p in list_ports.comports():
        tag = KNOWN_USB.get((p.vid, p.pid), "")
        print(f"{p.device:8s} {tag:12s} {p.description}")


def ensure_official(version: str, slug: str = "laniakea") -> Path:
    """Return the path of an official firmware image, downloading + verifying it if needed.

    Magerit publishes the images on GitHub (mageritsynth/binaries); they are not stored in
    this repository. The sha256 from Magerit's manifest is checked on every download."""
    v = version if version.startswith("v") else f"v{version}"
    dest = OFFICIAL / slug / f"{slug}_{v}.bin"
    if dest.exists():
        return dest
    for e in all_versions(module_entry(load_manifest(refresh=True), slug)):
        if e["version"] == v:
            print(f"downloading official {slug} {v} from Magerit's GitHub ...")
            with urllib.request.urlopen(e["url"]) as r:
                data = r.read()
            if hashlib.sha256(data).hexdigest() != e["sha256"]:
                die(f"{slug} {v}: sha256 mismatch - download corrupted or changed upstream")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return dest
    die(f"{slug} {v} is not in Magerit's manifest")


def cmd_fetch(a):
    man = load_manifest(refresh=True)
    if a.manuals:
        d = ROOT / "docs" / "manuals"
        d.mkdir(parents=True, exist_ok=True)
        for m in man["modules"]:
            if m["slug"] in ("laniakea", "laniakea_pro") and m.get("manual_url"):
                dest = d / Path(m["manual_url"]).name
                with urllib.request.urlopen(m["manual_url"]) as r:
                    dest.write_bytes(r.read())
                print(f"manual  {dest.relative_to(ROOT)}")
    slugs = ["laniakea"] + (["laniakea_pro"] if a.pro else [])
    for slug in slugs:
        entry = module_entry(man, slug)
        d = OFFICIAL / slug
        d.mkdir(parents=True, exist_ok=True)
        for v in all_versions(entry):
            dest = d / Path(v["url"]).name
            if dest.exists() and sha256(dest) == v["sha256"]:
                print(f"ok      {dest.relative_to(ROOT)}")
                continue
            with urllib.request.urlopen(v["url"]) as r:
                dest.write_bytes(r.read())
            ok = sha256(dest) == v["sha256"]
            print(f"{'fetched' if ok else 'BADHASH'} {dest.relative_to(ROOT)}")
            if not ok:
                dest.unlink()
        (d / "versions.json").write_text(json.dumps(all_versions(entry), indent=2, ensure_ascii=False), encoding="utf-8")


def cmd_info(a):
    port = find_port(a.port)
    esptool("flash-id", port=port)
    print("\n$ espefuse summary (read-only)")
    subprocess.run([sys.executable, "-m", "espefuse", "--chip", "esp32", "--port", port, "summary"])


def cmd_backup(a):
    port = find_port(a.port)
    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(a.output) if a.output else BACKUPS / f"laniakea_{stamp}.bin"
    esptool("read-flash", "0", "ALL", str(out), port=port, baud=FLASH_BAUD)
    buf = out.read_bytes()
    try:
        info = espimage.describe_merged(buf)
        print(f"\nbackup: {out}  ({len(buf) >> 20} MB)\ninstalled firmware: {info['app']}  "
              f"bootloader_ok={info['bootloader_ok']} app_ok={info['app_ok']}")
    except ValueError as e:
        print(f"backup written to {out}, but could not parse it: {e}")
    (out.with_suffix(".sha256")).write_text(hashlib.sha256(buf).hexdigest() + "  " + out.name + "\n")


def cmd_version(a):
    """Show which firmware (and which patches) the module runs: reads only the app header."""
    import tempfile
    port = find_port(a.port)
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "hdr.bin"
        esptool("read-flash", hex(espimage.APP_OFFSET), "0x200", str(out), port=port)
        hdr = out.read_bytes()
    d = 24 + 8                                   # esp_app_desc_t at the first segment's data
    import struct
    if struct.unpack_from("<I", hdr, d)[0] != 0xABCD5432:
        die("no application descriptor found - is Laniakea firmware installed?")
    cstr = lambda a_, b_: hdr[d + a_:d + b_].split(b"\0")[0].decode(errors="replace")
    version, built = cstr(16, 48), f"{cstr(96, 112)} {cstr(80, 96)}"
    print(f"\nproject: {cstr(48, 80)}\nversion: {version}\nbuilt:   {built}")
    if "+" in version:
        print("patches: " + ", ".join(version.split("+")[1:]))
    else:
        official = {"Jun 12 2023": "v2.2", "Mar  5 2024": "v2.8", "Oct 29 2025": "v3.0", "May  4 2026": "v3.1-v3.3",
                    "Aug 18 2026": "v3.4-v3.6"}
        print(f"official Magerit firmware ({official.get(cstr(96, 112), 'unknown')}; exact version: compare a backup "
              "with `laniakea fetch` images)")


def cmd_settings(a):
    """Read the NVS partition (read-only) and print saved settings / calibration."""
    import nvs
    import tempfile
    if a.file:
        raw = Path(a.file).read_bytes()
        data = raw[nvs.NVS_OFFSET:nvs.NVS_OFFSET + nvs.NVS_SIZE] if len(raw) > nvs.NVS_SIZE else raw
    else:
        port = find_port(a.port)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "nvs.bin"
            esptool("read-flash", hex(nvs.NVS_OFFSET), hex(nvs.NVS_SIZE), str(out), port=port, baud=FLASH_BAUD)
            data = out.read_bytes()
    names = {"tabla": "Y row (ORBITS SHAPE)", "acorde": "chord (ORBITS CLUSTER)", "octava": "FREQ range (ORBITS FREQ)",
             "cant_esp": "volume (ORBITS SPACE!)", "decay": "EXCITER decay (ORBITS ORBITS)",
             "lpg_color": "LPG colour (ORBITS COLOR)", "modores": "bow<=0.5<pluck (ORBITS EFFECTS)",
             "val_1": "SPACE amt FREQ", "val_2": "SPACE amt ORBITS", "val_3": "SPACE amt COLOR",
             "val_4": "SPACE amt SHAPE", "val_5": "SPACE amt SPACE!", "val_6": "SPACE amt EFFECTS",
             "val_7": "SPACE amt CLUSTER", "val_A": "V/OCT scale", "val_B": "V/OCT offset"}
    for ns, key, val in nvs.dump(data):
        print(f"{key:10s} {val:>10s}   {names.get(key, '')}")


def resolve_image(spec: str) -> Path:
    p = Path(spec)
    if p.exists():
        return p
    import re
    if re.fullmatch(r"v?\d+\.\d+", spec):
        return ensure_official(spec)          # official release: download + verify if missing
    die(f"{spec}: not a file and not a version like v3.6")


def check_image(path: Path, allow_unverified=False) -> bytes:
    buf = path.read_bytes()
    info = espimage.describe_merged(buf)
    if info["chip"] != "esp32":
        die(f"{path.name} is a {info['chip']} image, Laniakea is esp32")
    if not (info["bootloader_ok"] and info["app_ok"]):
        die(f"{path.name}: checksum/SHA-256 invalid - the bootloader would refuse it (run tools/patcher.py fix?)")
    if info["app_end"] > 0x1E0000:
        die("image is larger than the factory partition and would overwrite NVS")
    print(f"image: {path.name}  {info['app']}")
    # Official image? compare with manifest hash
    h = hashlib.sha256(buf).hexdigest()
    try:
        known = {v["sha256"]: v["version"] for v in all_versions(module_entry(load_manifest(), "laniakea"))}
    except Exception:
        known = {}
    if h in known:
        print(f"        official Magerit {known[h]} (sha256 matches manifest)")
    elif not allow_unverified:
        print("        CUSTOM image (not an official release)")
    return buf


def cmd_flash(a):
    path = resolve_image(a.image)
    buf = check_image(path)
    if not a.no_backup and latest_backup() is None:
        die("no flash backup found in firmware/backup/ - run `backup` first (or pass --no-backup)")
    port = find_port(a.port)
    # Merged image starting at 0x0: bootloader @0x1000, partition table @0x8000, app @0x10000.
    # NVS (@0x1E0000, holds calibration + settings + user waves) is beyond the image and is NOT touched.
    esptool("--after", "hard-reset", "write-flash", "--flash-mode", "keep", "--flash-freq", "keep",
            "--flash-size", "keep", "-z", "0x0", str(path), port=port, baud=FLASH_BAUD)
    print(f"\nflashed {path.name} ({len(buf)} bytes). If the LEDs stay dark, power-cycle the rack.")


def cmd_restore(a):
    path = Path(a.backup)
    buf = path.read_bytes()
    if len(buf) != 4 * 1024 * 1024:
        die("expected a full 4 MB flash dump")
    espimage.describe_merged(buf)  # sanity
    if not a.yes:
        die("this rewrites the WHOLE flash including calibration/NVS from the dump; re-run with --yes")
    port = find_port(a.port)
    esptool("--after", "hard-reset", "write-flash", "-z", "0x0", str(path), port=port, baud=FLASH_BAUD)


# ----- wavetables
def decode_wav(path: Path):
    """Return mono float64 samples in [-1, 1] from any PCM / float WAV (first channel)."""
    import numpy as np
    import struct as st
    raw = path.read_bytes()
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        die("not a RIFF/WAVE file")
    # Parse chunks manually so 32-bit float (format 3) works too.
    p, fmt, data = 12, None, None
    while p + 8 <= len(raw):
        cid, size = raw[p:p + 4], st.unpack_from("<I", raw, p + 4)[0]
        body = raw[p + 8:p + 8 + size]
        if cid == b"fmt ":
            fmt = st.unpack_from("<HHIIHH", body)
        elif cid == b"data":
            data = body
        p += 8 + size + (size & 1)
    if not fmt or data is None:
        die("WAV missing fmt/data chunk")
    tag, ch, _sr, _br, _ba, bits = fmt
    if tag == 3 and bits == 32:
        x = np.frombuffer(data, "<f4").astype(np.float64)
    elif bits == 16:
        x = np.frombuffer(data, "<i2") / 32768.0
    elif bits == 8:
        x = (np.frombuffer(data, "u1").astype(np.float64) - 128) / 128.0
    elif bits == 24:
        b = np.frombuffer(data, "u1").reshape(-1, 3)
        x = ((b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16)) << 8 >> 8) / 8388608.0
    elif bits == 32:
        x = np.frombuffer(data, "<i4") / 2147483648.0
    else:
        die(f"unsupported WAV format tag={tag} bits={bits}")
    if ch > 1:
        x = x.reshape(-1, ch)[:, 0]
    return x


def resample_cycle(x, n: int):
    """Band-limited resample of one periodic cycle to n samples."""
    import numpy as np
    h = min(len(x), n) // 2
    spec = np.fft.rfft(x)[:h]
    return np.fft.irfft(spec, n=n) * (n / len(x))


def read_wavetable(path: Path, decimate=False):
    """Return int16 list[64][128] from a 64x256 (or 64xN) mono WAV."""
    import numpy as np
    if not path.exists():
        die(f"{path}: file not found")
    x = decode_wav(path)
    if len(x) % WAVES:
        die(f"{len(x)} samples is not a multiple of 64 waves")
    n = len(x) // WAVES
    waves = x.reshape(WAVES, n)
    if decimate and n == 2 * WAVE_LEN:
        out = waves[:, ::2]                                   # exactly what Magerit's web page does
    else:
        spec = np.fft.rfft(waves, axis=1)[:, :WAVE_LEN // 2]  # band-limited resample to 128
        out = np.fft.irfft(spec, n=WAVE_LEN, axis=1) * (WAVE_LEN / n)
    return np.clip(np.round(out * 32767), -32767, 32767).astype(int).tolist()


def handshake(s, magic: bytes, tries=5) -> bool:
    s.reset_input_buffer()
    for _ in range(tries):
        s.write(magic)
        t = time.time()
        while time.time() - t < 0.3:
            b = s.read(1)
            if b and b[0] == ACK:
                return True
    return False


def wait_ack(s, timeout=2.0) -> bool:
    t = time.time()
    while time.time() - t < timeout:
        b = s.read(1)
        if b:
            if b[0] == ACK:
                return True
            if b[0] == NACK:
                return False
    return False


def select_bank(s, bank: int) -> None:
    """'MAG1'..'MAG8' (banks patch): select + save + load a bank on the module. Sent once (not
    retried) - the module answers after saving and loading, which can take ~0.5-1 s."""
    if not 1 <= bank <= 8:
        die("bank must be 1..8")
    s.reset_input_buffer()
    s.write(f"MAG{bank}".encode())
    if not wait_ack(s, timeout=5.0):
        die(f"module did not confirm bank {bank} - is a firmware with the `banks` patch installed?")


def query_bank(s, tries=3) -> int | None:
    """'MAGB' (banks patch) -> 'B', '1'..'8', ACK. Returns the bank playing now, or None."""
    for _ in range(tries):
        s.reset_input_buffer()
        s.write(b"MAGB")
        buf, t = b"", time.time()
        while time.time() - t < 0.5:
            buf += s.read(16)
            i = buf.find(bytes([ACK]))
            if i >= 2 and buf[i - 2:i - 1] == b"B" and buf[i - 1:i].isdigit():
                return int(buf[i - 1:i])
    return None


def read_module_waves(s, tries=2):
    """'MAGR' (banks patch) -> "WAVS" + int16[64][128] LE + ACK: the waves playing now."""
    import numpy as np
    n = WAVES * WAVE_LEN * 2
    for _ in range(tries):
        s.reset_input_buffer()
        s.write(b"MAGR")
        buf, t = b"", time.time()
        while time.time() - t < 4.0:
            buf += s.read(4096)
            i = buf.find(b"WAVS")
            if i >= 0 and len(buf) >= i + 4 + n + 1:
                if buf[i + 4 + n] == ACK:
                    return np.frombuffer(buf[i + 4:i + 4 + n], dtype="<i2").reshape(WAVES, WAVE_LEN)
                break                                   # misaligned (log output mixed in?): retry
    die("module did not send its waves - is a firmware with the `banks` patch installed?")


def _send_waves(s, waves, label="", progress=None):
    if not handshake(s, b"MAGW"):
        die("module did not ACK 'MAGW' - is it powered from the rack and running Laniakea firmware?")
    for k, w in enumerate(waves):
        s.write(('{"W":%d,"S":[%s]}' % (k, ",".join(map(str, w)))).encode())
        if not wait_ack(s):
            die(f"no ACK after wave {k}")
        print(f"\r  {label}wave {k + 1}/{len(waves)}", end="", flush=True)
        if progress:
            progress((k + 1) / len(waves))
    print()


def upload_waves(port: str, waves, bank: int | None = None) -> None:
    upload_banks(port, [(bank, waves)])


def upload_banks(port: str, jobs) -> None:
    """jobs = [(bank or None, waves), ...]. One reset, then per bank: select (if given) + upload.
    The module saves each bank before it reads the next command, so they don't mix."""
    s = open_serial(port)
    try:
        hard_reset(s)
        time.sleep(2.0)                       # let the app boot (as the web updater does)
        for bank, waves in jobs:
            if bank is not None:
                select_bank(s, bank)
            _send_waves(s, waves, f"bank {bank}: " if bank else "")
        print("waves uploaded" + (f" to bank(s) {', '.join(str(b) for b, _ in jobs)}" if jobs[0][0] else "") + ".")
    finally:
        s.close()


def cmd_waves(a):
    port = find_port(a.port)
    if a.action in ("current", "read"):
        s = open_serial(port)
        try:
            time.sleep(0.3)
            bank = query_bank(s)
            if bank is None:                  # opening the port may have reset the module: wait for boot
                time.sleep(2.0)
                bank = query_bank(s)
            if bank is None:
                die("no answer to 'MAGB' - is a firmware with the `banks` patch installed?")
            if a.bank and a.bank != bank:
                select_bank(s, a.bank)
                bank = a.bank
            if a.action == "current":
                print(f"module is playing bank {bank}")
                return
            raw = read_module_waves(s)
        finally:
            s.close()
        out = Path(a.output or f"module_bank{bank}.wav")
        write_bank(out, [resample_cycle(w.astype(float) / 32767.0, SRC_WAVE_LEN) for w in raw])
        print(f"wrote {out}: bank {bank} as stored on the module (64 waves, 128 -> 256 samples)")
        return
    if a.action in ("default", "select"):
        if a.action == "select" and not a.bank:
            die("waves select needs --bank N (1..8)")
        s = open_serial(port)
        try:
            hard_reset(s)
            time.sleep(2.0)
            if a.bank:
                select_bank(s, a.bank)
                print(f"bank {a.bank} selected (saved; restored at power-up).")
            if a.action == "default":
                if not handshake(s, b"MAGD"):
                    die("module did not ACK 'MAGD'")
                print("factory wavetable restored" + (f" in bank {a.bank}." if a.bank else "."))
        finally:
            s.close()
        return
    if a.action == "banks":
        jobs = []
        for spec in a.files:
            bank, _, f = spec.partition("=")
            if not f or not bank.isdigit():
                die(f"expected BANK=FILE.wav, got {spec!r}")
            jobs.append((int(bank), read_wavetable(Path(f), decimate=a.decimate)))
        if not jobs:
            die("waves banks needs BANK=FILE.wav arguments, e.g. 1=a.wav 2=b.wav")
        upload_banks(port, jobs)
        return
    if len(a.files) != 1:
        die("waves upload needs exactly one .wav file (use `waves banks 1=a.wav 2=b.wav` for several)")
    upload_waves(port, read_wavetable(Path(a.files[0]), decimate=a.decimate), a.bank)


AKWF_REPO = "KristofferKarlAxelEkstrand/AKWF-FREE"
WAVETABLES = ROOT / "wavetables"


def cmd_akwf(a):
    """List or download AKWF (CC0) single-cycle folders into wavetables/akwf/<folder>/."""
    api = f"https://api.github.com/repos/{AKWF_REPO}/contents/AKWF"
    if a.action == "list" or not a.folders:
        with urllib.request.urlopen(api) as r:
            names = [x["name"].removeprefix("AKWF_") for x in json.load(r) if x["type"] == "dir"]
        print("AKWF folders (fetch with: akwf fetch <name> ...):\n  " + "  ".join(names))
        return
    for name in a.folders:
        folder = name if name.startswith("AKWF_") else f"AKWF_{name}"
        dest = WAVETABLES / "akwf" / folder
        dest.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(f"{api}/{folder}") as r:
            files = [x for x in json.load(r) if x["name"].lower().endswith(".wav")]
        for x in files:
            out = dest / x["name"]
            if not out.exists():
                with urllib.request.urlopen(x["download_url"]) as r:
                    out.write_bytes(r.read())
        print(f"{folder}: {len(files)} waves in {dest.relative_to(ROOT)}")


def collect_cycles(src: Path):
    """Single cycles from a folder of WAVs, one WAV file, or a 64-wave bank, as 256-sample arrays."""
    import numpy as np
    files = sorted(src.glob("*.wav"), key=lambda p: p.name.lower()) if src.is_dir() else [src]
    cycles = []
    for f in files:
        x = decode_wav(f)
        if len(x) == WAVES * SRC_WAVE_LEN:                       # already a bank: split it
            cycles += [resample_cycle(w, SRC_WAVE_LEN) for w in x.reshape(WAVES, SRC_WAVE_LEN)]
        else:
            cycles.append(resample_cycle(x, SRC_WAVE_LEN))
    if not cycles:
        die(f"no .wav files in {src}")
    return [c - np.mean(c) for c in cycles]


def spread(cycles, n: int):
    """Pick/crossfade n waves evenly across a list of cycles."""
    import numpy as np
    out = []
    for k in range(n):
        pos = 0 if len(cycles) == 1 else k * (len(cycles) - 1) / (n - 1)
        i = int(pos)
        j = min(i + 1, len(cycles) - 1)
        out.append(cycles[i] * (1 - (pos - i)) + cycles[j] * (pos - i))
    return out


def write_bank(path: Path, waves):
    import numpy as np
    import wave
    data = np.concatenate([w / max(1e-9, np.max(np.abs(w))) for w in waves])
    pcm = np.clip(np.round(data * 32767), -32768, 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(44100)
        wf.writeframes(pcm.tobytes())


def cmd_bank(a):
    """Build a 64x256 bank (WaveEdit/Magerit format) from single-cycle sources.

    1 source  -> 64 waves spread across the whole grid (row-major, wave = Y*8 + X)
    2-8 sources -> one source per row anchor; rows in between are crossfaded
    """
    sources = [Path(s) for s in a.sources]
    if len(sources) == 1:
        waves = spread(collect_cycles(sources[0]), WAVES)
    else:
        if len(sources) > 8:
            die("at most 8 sources (one per row)")
        rows = [spread(collect_cycles(s), 8) for s in sources]
        waves = []
        for r in range(8):
            pos = r * (len(rows) - 1) / 7
            i = int(pos); j = min(i + 1, len(rows) - 1); t = pos - i
            waves += [rows[i][x] * (1 - t) + rows[j][x] * t for x in range(8)]
    out = Path(a.output)
    write_bank(out, waves)
    print(f"wrote {out} (64 waves x 256 samples, 16-bit) - upload with: waves upload {out}")


def cmd_factory_waves(a):
    """Export the factory wavetable built into an official firmware image as a 64x256 WAV."""
    import numpy as np
    import symbols
    img = ensure_official(a.version)
    buf = img.read_bytes()
    entry = symbols.BY_SHA256.get(hashlib.sha256(buf).hexdigest())
    if not entry:
        die(f"{img.name}: no known factory-table address for this version (only {', '.join(v for v, _ in symbols.BY_SHA256.values())})")
    app = espimage.parse_image(buf, espimage.APP_OFFSET)
    off = app.addr_to_offset(entry[1]["factory_waves"])
    words = np.frombuffer(buf[off:off + 64 * 128 * 4], "<i4")
    waves = words.astype(np.int16).reshape(64, 128).astype(float) / 32767.0
    write_bank(Path(a.output), [resample_cycle(w, SRC_WAVE_LEN) for w in waves])
    print(f"wrote {a.output}: factory bank of {img.name} (64 waves, upsampled 128 -> 256)")


def cmd_monitor(a):
    port = find_port(a.port)
    s = open_serial(port, a.baud)
    if a.reset:
        hard_reset(s)
    print(f"--- {port} @ {a.baud}, Ctrl+C to exit ---")
    try:
        while True:
            d = s.read(256)
            if d:
                sys.stdout.write(d.decode("utf-8", "replace"))
                sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        s.close()


def cmd_editor(a):
    import http.server
    import functools
    import webbrowser
    import editor_bridge                  # serial bridge: the editor uses pyserial/esptool through this server
    handler = functools.partial(editor_bridge.Handler, directory=str(ROOT / "editor"))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", a.http_port), handler)
    url = f"http://127.0.0.1:{a.http_port}/"
    print(f"wavetable editor at {url}  (any browser; the module is reached through this server. Ctrl+C to stop)")
    if not a.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass

def cmd_patcher(a):
    """Run tools/patcher.py in-process: `laniakea patcher list|build|disasm|find|verify ...`."""
    from patcher import main as patcher_main
    patcher_main(a.args, prog=f"{Path(sys.argv[0]).stem} patcher")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="serial port (auto-detected CH340 by default)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ports").set_defaults(fn=cmd_ports)
    p = sub.add_parser("fetch", help="download official firmware (+ --pro, --manuals) from Magerit")
    p.add_argument("--pro", action="store_true"); p.add_argument("--manuals", action="store_true")
    p.set_defaults(fn=cmd_fetch)
    sub.add_parser("info").set_defaults(fn=cmd_info)
    p = sub.add_parser("backup"); p.add_argument("-o", "--output"); p.set_defaults(fn=cmd_backup)
    sub.add_parser("version", help="show installed firmware version and patches (read-only)").set_defaults(fn=cmd_version)
    p = sub.add_parser("settings", help="print saved settings/calibration from NVS (read-only)")
    p.add_argument("file", nargs="?", help="read from a flash dump instead of the module"); p.set_defaults(fn=cmd_settings)
    p = sub.add_parser("flash"); p.add_argument("image", help="version (v3.6) or path to merged .bin")
    p.add_argument("--no-backup", action="store_true"); p.set_defaults(fn=cmd_flash)
    p = sub.add_parser("restore"); p.add_argument("backup"); p.add_argument("--yes", action="store_true")
    p.set_defaults(fn=cmd_restore)
    p = sub.add_parser("waves", help="upload / restore / select wavetable banks")
    p.add_argument("action", choices=["upload", "default", "select", "banks", "current", "read"])
    p.add_argument("files", nargs="*", help="upload: FILE.wav  |  banks: BANK=FILE.wav ...")
    p.add_argument("--bank", type=int, help="target bank 1..8 (needs the `banks` patch); default: current bank")
    p.add_argument("-o", "--output", help="read: output .wav (default module_bank<N>.wav)")
    p.add_argument("--decimate", action="store_true", help="drop odd samples like the Magerit web page (default: band-limited resample)")
    p.set_defaults(fn=cmd_waves)
    p = sub.add_parser("akwf", help="list/fetch AKWF single-cycle folders (CC0)")
    p.add_argument("action", choices=["list", "fetch"]); p.add_argument("folders", nargs="*")
    p.set_defaults(fn=cmd_akwf)
    p = sub.add_parser("bank", help="build a 64-wave bank from single-cycle WAV folders/files")
    p.add_argument("sources", nargs="+", help="1 source = whole grid; 2-8 = one per row")
    p.add_argument("-o", "--output", required=True); p.set_defaults(fn=cmd_bank)
    p = sub.add_parser("factory-waves", help="export the firmware's built-in factory wavetable as a .wav")
    p.add_argument("-o", "--output", default=str(WAVETABLES / "banks" / "factory_v3.6.wav"))
    p.add_argument("--version", default="v3.6"); p.set_defaults(fn=cmd_factory_waves)
    # add_help=False + REMAINDER: everything after `patcher` (incl. -h) goes to the patcher CLI
    p = sub.add_parser("patcher", add_help=False, help="list/build firmware patches (same as tools/patcher.py)")
    p.add_argument("args", nargs=argparse.REMAINDER); p.set_defaults(fn=cmd_patcher)
    p = sub.add_parser("monitor"); p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--reset", action="store_true"); p.set_defaults(fn=cmd_monitor)
    p = sub.add_parser("editor"); p.add_argument("--http-port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true"); p.set_defaults(fn=cmd_editor)
    argv = sys.argv[1:]
    if argv[:1] == ["patcher"]:          # pass the rest through untouched (argparse would eat -h etc.)
        return cmd_patcher(argparse.Namespace(args=argv[1:]))
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
