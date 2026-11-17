"""Convert the app inside a merged ESP32 firmware .bin into an ELF for Ghidra.

  python tools/img2elf.py firmware/official/laniakea/laniakea_v3.6.bin re/ghidra/laniakea_v3.6.elf

Also writes <elf>.symbols.txt (name addr type) with ESP32 ROM + peripheral
symbols parsed from re/rom/*.ld, consumed by re/ghidra_scripts/ImportSymbols.java.
"""
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import espimage  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EM_XTENSA = 94
PT_LOAD = 1
SHT_PROGBITS, SHT_NOBITS, SHT_STRTAB = 1, 8, 3
SHF_WRITE, SHF_ALLOC, SHF_EXEC = 1, 2, 4
PF_X, PF_W, PF_R = 1, 2, 4


def classify(addr):
    if 0x3F400000 <= addr < 0x3F800000: return ".flash.rodata", PF_R, SHF_ALLOC
    if 0x400C2000 <= addr < 0x40C00000: return ".flash.text", PF_R | PF_X, SHF_ALLOC | SHF_EXEC
    if 0x40070000 <= addr < 0x400C0000: return ".iram0.text", PF_R | PF_X, SHF_ALLOC | SHF_EXEC
    if 0x3FFAE000 <= addr < 0x40000000: return ".dram0.data", PF_R | PF_W, SHF_ALLOC | SHF_WRITE
    if 0x50000000 <= addr < 0x50002000: return ".rtc.data", PF_R | PF_W, SHF_ALLOC | SHF_WRITE
    if 0x400C0000 <= addr < 0x400C2000: return ".rtc.text", PF_R | PF_X, SHF_ALLOC | SHF_EXEC
    return ".unknown", PF_R, SHF_ALLOC


# Uninitialised regions so ROM calls, .bss globals and peripheral registers resolve
NOBITS = [
    (".rom0", 0x40000000, 0x00070000, PF_R | PF_X, SHF_ALLOC | SHF_EXEC),
    (".drom0", 0x3FF90000, 0x00010000, PF_R, SHF_ALLOC),
    (".periph", 0x3FF00000, 0x00080000, PF_R | PF_W, SHF_ALLOC | SHF_WRITE),
]


def parse_ld_symbols():
    syms = {}
    pat = re.compile(r"^\s*(?:PROVIDE\s*\(\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(0x[0-9a-fA-F]+)")
    for f in sorted((ROOT / "re" / "rom").glob("*.ld")):
        for line in f.read_text(errors="replace").splitlines():
            m = pat.match(line)
            if m:
                syms[m.group(1)] = int(m.group(2), 16)
    return syms


def main(src, dst):
    buf = Path(src).read_bytes()
    app = espimage.parse_image(buf, espimage.APP_OFFSET)
    segs = []
    for s in app.segments:
        name, pf, shf = classify(s.load_addr)
        segs.append([name, s.load_addr, buf[s.file_offset:s.file_offset + s.length], pf, shf])
    # name duplicates (.dram0.data appears twice etc.)
    seen = {}
    for s in segs:
        n = seen.get(s[0], 0)
        seen[s[0]] = n + 1
        if n:
            s[0] = f"{s[0]}.{n}"
    # .bss after the last DRAM segment, up to the heap start region
    dram_end = max(a + len(d) for n, a, d, *_ in segs if n.startswith(".dram0"))
    nobits = NOBITS + [(".dram0.bss", dram_end, 0x3FFE0000 - dram_end, PF_R | PF_W, SHF_ALLOC | SHF_WRITE)]

    # ---- layout: ehdr | phdrs | data... | shstrtab | shdrs
    n_ph = len(segs) + len(nobits)
    off = 52 + 32 * n_ph
    phdrs, shdrs, blobs = [], [], []
    shstr = b"\0"

    def addname(n):
        nonlocal shstr
        i = len(shstr)
        shstr += n.encode() + b"\0"
        return i

    shdrs.append(struct.pack("<10I", *([0] * 10)))
    for name, addr, data, pf, shf in segs:
        off = (off + 3) & ~3
        blobs.append((off, data))
        phdrs.append(struct.pack("<8I", PT_LOAD, off, addr, addr, len(data), len(data), pf, 4))
        shdrs.append(struct.pack("<10I", addname(name), SHT_PROGBITS, shf, addr, off, len(data), 0, 0, 4, 0))
        off += len(data)
    for name, addr, size, pf, shf in nobits:
        phdrs.append(struct.pack("<8I", PT_LOAD, off, addr, addr, 0, size, pf, 4))
        shdrs.append(struct.pack("<10I", addname(name), SHT_NOBITS, shf, addr, off, size, 0, 0, 4, 0))
    shstr_idx = len(shdrs)
    shstr_name = addname(".shstrtab")
    shstr_off = off
    off += len(shstr)
    shdrs.append(struct.pack("<10I", shstr_name, SHT_STRTAB, 0, 0, shstr_off, len(shstr), 0, 0, 1, 0))
    off = (off + 3) & ~3
    sh_off = off

    ident = b"\x7fELF" + bytes([1, 1, 1, 0]) + bytes(8)
    ehdr = ident + struct.pack("<HHIIIIIHHHHHH", 2, EM_XTENSA, 1, app.entry, 52, sh_off, 0x300,
                               52, 32, n_ph, 40, len(shdrs), shstr_idx)
    out = bytearray(sh_off + 40 * len(shdrs))
    out[:52] = ehdr
    p = 52
    for ph in phdrs:
        out[p:p + 32] = ph
        p += 32
    for o, d in blobs:
        out[o:o + len(d)] = d
    out[shstr_off:shstr_off + len(shstr)] = shstr
    p = sh_off
    for sh in shdrs:
        out[p:p + 40] = sh
        p += 40
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    Path(dst).write_bytes(out)

    syms = parse_ld_symbols()
    with open(str(dst) + ".symbols.txt", "w") as f:
        for n, a in sorted(syms.items(), key=lambda x: x[1]):
            kind = "f" if 0x40000000 <= a < 0x40070000 else "l"
            f.write(f"{n} {a:#010x} {kind}\n")
        f.write(f"app_main_entry {app.entry:#010x} f\n")
    print(f"wrote {dst} ({len(out)} bytes, {len(segs)} segments) + {len(syms)} ROM/periph symbols")


if __name__ == "__main__":
    main(*sys.argv[1:3])
