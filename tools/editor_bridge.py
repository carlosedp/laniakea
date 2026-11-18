"""Serial bridge for the wavetable editor, served by `laniakea editor`.

The editor talks to the module through these HTTP endpoints, which reuse the CLI's pyserial and
esptool code, so it works in any browser and does not depend on Web Serial (which, on some
Windows/CH340 setups, never delivers a byte). When the editor is opened without this server
(e.g. as plain files), it falls back to Web Serial.

All endpoints are POST + JSON (GET /api/hello and /api/progress for polling) on 127.0.0.1 only.
"""
from __future__ import annotations

import base64
import http.server
import json
import tempfile
import threading
import time
from pathlib import Path

import laniakea as L

_lock = threading.Lock()          # one serial operation at a time
_state = {"serial": None, "port": None, "progress": None, "lines": []}


def _say(msg: str):
    print(f"[editor] {msg}")
    _state["lines"].append(msg)


def _need_serial():
    if _state["serial"] is None:
        raise L.CliError("not connected")
    return _state["serial"]


def _close():
    s = _state["serial"]
    _state["serial"] = None
    if s is not None:
        try:
            s.close()
        except Exception:
            pass


def _progress(p):
    _state["progress"] = p


# ------------------------------------------------------------------ operations
def op_connect(req):
    if _state["serial"] is None:
        port = L.find_port(req.get("port") or None)
        _state["serial"] = L.open_serial(port)
        _state["port"] = port
        _say(f"opened {port}")
    return {"port": _state["port"]}


def op_disconnect(_req):
    _close()
    return {}


def op_bank(_req):
    return {"bank": L.query_bank(_need_serial())}


def _awake(s):
    if L.query_bank(s, tries=1) is None:
        _say("module did not answer: resetting it")
        L.hard_reset(s)
        time.sleep(2.0)


def op_select(req):
    s = _need_serial()
    _awake(s)
    L.select_bank(s, int(req["bank"]))
    _say(f"bank {req['bank']} selected")
    return {"bank": int(req["bank"])}


def op_read(req):
    s = _need_serial()
    if req.get("bank"):
        L.select_bank(s, int(req["bank"]))
    raw = L.read_module_waves(s)
    return {"waves": raw.astype(int).tolist(), "bank": L.query_bank(s)}


def op_upload(req):
    """jobs: [{bank, waves: 64 x 128 int16} | {bank, factory: true}] - one reset, then per bank."""
    s = _need_serial()
    jobs = req["jobs"]
    _progress(0.0)
    L.hard_reset(s)
    time.sleep(2.0)
    for j, job in enumerate(jobs):
        bank = job.get("bank")
        if bank:
            L.select_bank(s, int(bank))
        if job.get("factory"):
            if not L.handshake(s, b"MAGD"):
                raise L.CliError("module did not ACK 'MAGD'")
            _say(f"bank {bank}: factory waves restored")
        else:
            L._send_waves(s, job["waves"], f"bank {bank}: " if bank else "",
                          progress=lambda p, j=j: _progress((j + p) / len(jobs)))
            _say(f"bank {bank} uploaded" if bank else "waves uploaded to the current bank")
        _progress((j + 1) / len(jobs))
    return {"banks": [job.get("bank") for job in jobs]}


def op_flash(req):
    """Body: {image: base64}. Same as `laniakea flash`: merged image at 0x0, NVS untouched."""
    data = base64.b64decode(req["image"])
    _close()
    with tempfile.TemporaryDirectory() as td:
        name = "".join(c if c.isalnum() or c in "._+-" else "_" for c in Path(req.get("name") or "").name)
        path = Path(td) / (name if name.endswith(".bin") else "firmware.bin")
        path.write_bytes(data)
        L.check_image(path)
        port = L.find_port(req.get("port") or _state["port"])
        _say(f"flashing {path.name} ({len(data)} bytes) on {port}, ~15 s")
        L.esptool("--after", "hard-reset", "write-flash", "--flash-mode", "keep", "--flash-freq", "keep",
                  "--flash-size", "keep", "-z", "0x0", str(path), port=port, baud=L.FLASH_BAUD)
    _say("flashed. If the LEDs stay dark, power-cycle the rack.")
    return {}


def op_backup(req):
    """Full 4 MB dump into firmware/backup/ (stays on this computer)."""
    _close()
    port = L.find_port(req.get("port") or _state["port"])
    L.BACKUPS.mkdir(parents=True, exist_ok=True)
    out = L.BACKUPS / f"laniakea_{time.strftime('%Y%m%d-%H%M%S')}.bin"
    _say(f"reading the whole flash from {port} (~40 s)")
    L.esptool("read-flash", "0", "ALL", str(out), port=port, baud=L.FLASH_BAUD)
    _say(f"backup saved: {out}")
    return {"path": str(out)}


OPS = {"connect": op_connect, "disconnect": op_disconnect, "bank": op_bank, "select": op_select,
       "read": op_read, "upload": op_upload, "flash": op_flash, "backup": op_backup}


# ------------------------------------------------------------------ HTTP
class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):            # keep the console for module messages
        if not self.path.startswith("/api/"):
            super().log_message(fmt, *args)

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/hello":
            return self._json(200, {"bridge": 1, "connected": _state["serial"] is not None, "port": _state["port"]})
        if self.path == "/api/progress":
            return self._json(200, {"progress": _state["progress"]})
        return super().do_GET()

    def do_POST(self):
        name = self.path.removeprefix("/api/")
        op = OPS.get(name)
        if op is None or not self.path.startswith("/api/"):
            return self._json(404, {"error": "unknown endpoint"})
        # Only the editor page itself may drive the module (it can flash firmware): refuse other
        # sites (Origin) and DNS-rebinding tricks (Host).
        host = self.headers.get("Host", "")
        if host.rsplit(":", 1)[0] not in ("127.0.0.1", "localhost") or \
                self.headers.get("Origin") not in (None, f"http://{host}"):
            return self._json(403, {"error": "request refused (only the local editor page may use the bridge)"})
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self._json(400, {"error": "bad JSON"})
        with _lock:
            _state["lines"] = []
            try:
                res = op(req)
                code = 200
            except L.CliError as e:
                res, code = {"error": e.msg}, 400
            except Exception as e:                  # serial errors, unplugged cable...
                if name not in ("flash", "backup"):
                    _close()
                res, code = {"error": f"{type(e).__name__}: {e}"}, 500
            finally:
                _state["progress"] = None
            res["log"] = _state["lines"]
        return self._json(code, res)
