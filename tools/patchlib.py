"""patchlib - write binary patches for the Laniakea (ESP32) firmware.

A patch is a Python file in patches/ that calls methods on a `Firmware` object:

    fw.read(addr, n)                         bytes at a virtual address
    fw.write(addr, data, expect=...)         raw bytes (expect = original bytes, hex or bytes)
    fw.replace(addr, "asm", expect=...)      assemble an instruction in place (same length)
    fw.nop(addr, expect=...)                 NOP out instruction(s)
    fw.hook(addr, body, expect=..., literals={...})
                                             detour: overwrite with `j tramp`, run `body`
                                             (use {orig} to execute the overwritten
                                             instruction), then jump back
    fw.add_code(body, literals={...})        place a routine in the code cave, returns addr
    fw.write_floats(addr, values, expect_len=None)
    fw.sym["name"]                           version-specific addresses (tools/symbols.py)
    fw.tag("name")                           appended to the app version string

All assembly goes through Espressif's real GNU assembler (tools/xtensa-esp-elf),
so you write normal Xtensa mnemonics. New code lives in a "code cave" appended to
the end of the flash .text segment; the image checksum and SHA-256 are fixed on save.
"""
from __future__ import annotations

import hashlib
import re
import struct
import subprocess
import tempfile
from pathlib import Path

import espimage
import symbols

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "tools" / "xtensa-esp-elf" / "bin"
TOOL = lambda t: str(BIN / f"xtensa-esp32-elf-{t}.exe")  # noqa: E731

# Instructions whose encoding depends on their address - can't be copied into a trampoline as-is.
PC_RELATIVE = re.compile(r"^(l32r|j|call\d+|loop\w*|b\w+|movi\.n?\s+\w+,\s*0x4)")


class PatchError(Exception):
    pass


def _hex(x) -> bytes:
    return bytes.fromhex(x.replace(" ", "")) if isinstance(x, str) else bytes(x)


def float_bits(f: float) -> int:
    return struct.unpack("<I", struct.pack("<f", f))[0]


class Firmware:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.buf = bytearray(self.path.read_bytes())
        sha = hashlib.sha256(self.buf).hexdigest()
        if sha not in symbols.BY_SHA256:
            raise PatchError(f"{self.path.name}: not a known official image (sha256 {sha[:12]}…); "
                             "patches need version-specific addresses")
        self.version, self.sym = symbols.BY_SHA256[sha]
        self.app = espimage.parse_image(self.buf, espimage.APP_OFFSET)
        seg = self.app.segments[self.sym["text_segment"]]
        self.cave_base = seg.load_addr + seg.length       # first free address after .flash.text
        self.cave = bytearray()
        self.tags: list[str] = []
        self.log: list[str] = []
        self._n = 0

    # ------------------------------------------------------------ low level
    def off(self, addr: int) -> int:
        o = self.app.addr_to_offset(addr)
        if o is None:
            raise PatchError(f"{addr:#x} is not inside the app image")
        return o

    def read(self, addr: int, n: int) -> bytes:
        o = self.off(addr)
        return bytes(self.buf[o:o + n])

    def write(self, addr: int, data, expect=None):
        data = _hex(data)
        if expect is not None:
            exp = _hex(expect)
            cur = self.read(addr, len(exp))
            if cur != exp:
                raise PatchError(f"unexpected bytes at {addr:#x}: {cur.hex()} (expected {exp.hex()}) "
                                 "- wrong firmware version, or another patch already changed this spot")
        o = self.off(addr)
        self.buf[o:o + len(data)] = data
        self.log.append(f"write {addr:#x}: {data.hex()}")

    def write_floats(self, addr: int, values, expect_len: int | None = None):
        if expect_len is not None and len(values) != expect_len:
            raise PatchError(f"expected {expect_len} floats, got {len(values)}")
        self.write(addr, struct.pack(f"<{len(values)}f", *values))

    # ------------------------------------------------------------ assembler
    def asm(self, src: str, at: int, defs: dict[str, int] | None = None) -> tuple[bytes, dict[str, int]]:
        """Assemble `src` linked at absolute address `at`. Returns (bytes, symbol table)."""
        defs = dict(defs or {})
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "p.S").write_text('    .section .text, "ax"\n    .begin no-transform\n' + src +
                                    "\n    .end no-transform\n")
            r = subprocess.run([TOOL("as"), "-o", str(td / "p.o"), str(td / "p.S")], capture_output=True, text=True)
            if r.returncode:
                raise PatchError("assembler error:\n" + r.stderr + "\n--- source ---\n" + src)
            cmd = [TOOL("ld"), "-o", str(td / "p.elf"), f"-Ttext={at:#x}", "-e", "0", "--no-relax"]
            cmd += [f"--defsym={k}={v:#x}" for k, v in defs.items()]
            r = subprocess.run(cmd + [str(td / "p.o")], capture_output=True, text=True)
            if r.returncode:
                raise PatchError("link error (jump/branch out of range?):\n" + r.stderr)
            subprocess.run([TOOL("objcopy"), "-O", "binary", "-j", ".text", str(td / "p.elf"), str(td / "p.bin")], check=True)
            nm = subprocess.run([TOOL("nm"), str(td / "p.elf")], capture_output=True, text=True, check=True).stdout
            syms = {n: int(a, 16) for a, _t, n in (l.split() for l in nm.splitlines() if len(l.split()) == 3)}
            return (td / "p.bin").read_bytes(), syms

    def disasm(self, addr: int, n: int) -> list[tuple[int, str, str]]:
        """Disassemble n bytes at addr -> [(addr, hexbytes, text)]."""
        data = self.read(addr, n)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "b.bin"
            p.write_bytes(data)
            out = subprocess.run([TOOL("objdump"), "-D", "-b", "binary", "-m", "xtensa", f"--adjust-vma={addr:#x}", str(p)],
                                 capture_output=True, text=True, check=True).stdout
        res = []
        for line in out.splitlines():
            m = re.match(r"\s*([0-9a-f]+):\s+([0-9a-f]+)\s+(.*)", line)
            if m:
                res.append((int(m.group(1), 16), m.group(2), m.group(3).strip()))
        return res

    # ------------------------------------------------------------ high level
    def replace(self, addr: int, src: str, expect):
        exp = _hex(expect)
        code, _ = self.asm(src, addr)
        if len(code) != len(exp):
            raise PatchError(f"replacement at {addr:#x} is {len(code)} bytes, original is {len(exp)}")
        self.write(addr, code, expect=exp)

    def nop(self, addr: int, expect):
        exp = _hex(expect)
        n3, n2 = divmod(len(exp), 3)
        src = "    _nop\n" * n3 + ("    _nop.n\n" if n2 == 2 else "")
        if n2 == 1:
            raise PatchError("can't NOP a region whose length isn't 2/3-byte instructions")
        self.replace(addr, src, exp)

    def _literal_block(self, prefix: str, literals: dict) -> str:
        lines = ["    .align 4"]
        for name, v in (literals or {}).items():
            word = float_bits(v) if isinstance(v, float) else int(v) & 0xFFFFFFFF
            lines.append(f"{prefix}{name}: .word {word:#x}")
        return "\n".join(lines) + "\n"

    def add_code(self, body: str, literals: dict | None = None, defs: dict | None = None, name: str = "code") -> int:
        """Append a routine (with its literal pool before it) to the cave. Returns its entry address.

        In `body`, refer to literals as `lit_<name>` (e.g. `l32r a8, lit_gain`)."""
        self._n += 1
        while len(self.cave) % 4:
            self.cave += b"\0"
        base = self.cave_base + len(self.cave)
        src = (self._literal_block("lit_", literals) + "    .align 4\n    .global __entry\n__entry:\n" + body)
        code, syms = self.asm(src, base, defs)
        code += b"\0" * (-len(code) % 4)
        self.cave += code
        entry = syms["__entry"]
        self.log.append(f"cave {name} @ {entry:#x} ({len(code)} bytes)")
        return entry

    def hook(self, addr: int, body: str, expect, literals: dict | None = None, resume: int | None = None, name="hook") -> int:
        """Detour execution at `addr`.

        The overwritten bytes (`expect`, >= 3 bytes, whole instructions) are replaced by
        `j <trampoline>`. The trampoline runs `body` and then jumps to `resume`
        (default: the instruction right after the overwritten ones). Put `{orig}` in the
        body to execute the original instruction(s) at that point.
        Registers you use in `body` must be dead at `addr` - check with `patcher.py disasm`."""
        exp = _hex(expect)
        if len(exp) < 3:
            raise PatchError("hook needs at least 3 bytes (the size of a `j` instruction)")
        cur = self.read(addr, len(exp))
        if cur != exp:
            raise PatchError(f"unexpected bytes at {addr:#x}: {cur.hex()} (expected {exp.hex()})")
        insns = self.disasm(addr, len(exp))
        if sum(len(h) // 2 for _a, h, _t in insns) != len(exp):
            raise PatchError(f"`expect` at {addr:#x} doesn't cover whole instructions: {insns}")
        for a, _h, text in insns:
            if PC_RELATIVE.match(text) and "{orig}" in body:
                raise PatchError(f"can't relocate PC-relative instruction `{text}` at {a:#x} into a trampoline")
        resume = addr + len(exp) if resume is None else resume
        orig = "    .byte " + ",".join(f"{b:#04x}" for b in exp) + "\n"
        tramp = self.add_code(body.replace("{orig}", orig) + "\n    j       __resume\n", literals,
                              {"__resume": resume}, name=name)
        jump, _ = self.asm("    j       __tramp\n", addr, {"__tramp": tramp})
        # Fill the rest of the overwritten region with NOPs (never executed: we jump away and
        # resume after the region). A 1-byte remainder can't hold an instruction - leave it.
        pad = len(exp) - len(jump)
        n3, n2 = (pad // 3, 0) if pad % 3 == 0 else ((pad - 4) // 3, 2) if pad % 3 == 1 and pad >= 4 else (pad // 3, 1 if pad % 3 == 2 else 0)
        src = "    _nop\n" * n3 + "    _nop.n\n" * n2
        filler = self.asm(src, addr + 3)[0] if src else b""
        filler += exp[len(jump) + len(filler):]   # untouched remainder (only when pad == 1)
        if len(jump) + len(filler) != len(exp):
            raise PatchError("could not pad hook to the original length")
        self.write(addr, jump + filler)
        self.log.append(f"hook {addr:#x} -> {tramp:#x} (resume {resume:#x})")
        return tramp

    def tag(self, t: str):
        self.tags.append(t)

    # ------------------------------------------------------------ output
    def save(self, out: Path) -> Path:
        buf = self.buf
        app = self.app
        if self.tags:
            v = (f"{self.version}+" + "+".join(self.tags)).encode()[:31]
            i = app.segments[0].file_offset + 16
            buf[i:i + 32] = v + b"\0" * (32 - len(v))
        cave = bytes(self.cave) + b"\0" * (-len(self.cave) % 4)
        new = bytearray(buf[:app.offset + 24])
        for k, s in enumerate(app.segments):
            data = bytes(buf[s.file_offset:s.file_offset + s.length])
            if k == self.sym["text_segment"]:
                data += cave
            new += struct.pack("<II", s.load_addr, len(data)) + data
        new += b"\0" * (15 - ((len(new) - app.offset) % 16)) + b"\0"
        if app.hash_offset is not None:
            new += b"\0" * 32
        espimage.fix_image(new, espimage.parse_image(new, app.offset))
        info = espimage.describe_merged(new)
        if not (info["bootloader_ok"] and info["app_ok"]):
            raise PatchError(f"internal error: rebuilt image does not validate: {info}")
        if info["app_end"] > 0x1E0000:
            raise PatchError("image would overflow the factory partition")
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(new)
        return out
