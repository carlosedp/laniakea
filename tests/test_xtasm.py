"""tools/xtasm.py must match Espressif's GNU binutils exactly.

  .venv/bin/python tests/test_xtasm.py        (needs the Xtensa toolchain + official images)

1. Builds many patch combinations on every supported base with LANIAKEA_ASM=gnu and =py
   and compares the resulting images byte for byte.
2. Disassembles the whole .flash.text of each base with both and compares every instruction
   xtasm decodes (lengths must always agree).
"""
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import patchlib  # noqa: E402
import patcher  # noqa: E402
import xtasm  # noqa: E402
from laniakea import ensure_official  # noqa: E402

SPECS = [
    ["everything"],
    ["recommended"],
    ["recommended", "quantizer", "chords:set=stock", "quiet:level=2"],
    ["cv_to_y:source=orbits,exclusive=0,gain=-0.78", "led_menus:tint=0,flash=0"],
    ["cv_to_y:source=shape", "usability:y_top=0,freq_semis=0", "banks:banks=3", "led_menus:flash_led=1"],
    ["quantizer:scales=iwato,hyst=0.3", "led_dedupe", "chords:set=" +
     str(ROOT / "patches" / "chord_sets" / "example.txt")],
    ["banks:banks=2", "led_menus"],
    ["strum:mode=always,lpg=0,reset_bow=0,strength=0.5", "bow:level=0.5,even=0"],
    ["recommended", "strum", "bow:level=1,even=1"],
]


def build(spec, base, backend):
    os.environ["LANIAKEA_ASM"] = backend
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.bin"
        patcher.main(["build", *spec, "--base", base, "-o", str(out)])
        return out.read_bytes()


def main():
    patchlib.TOOL("as")          # fail early without the toolchain
    bad = 0
    for base in ("v3.6", "v3.7"):
        for spec in SPECS + ([["diag_guards"], ["diag_noled"]] if base == "v3.6" else []):
            g, p = build(spec, base, "gnu"), build(spec, base, "py")
            ok = g == p
            bad += not ok
            print(f"{'OK ' if ok else 'BAD'} build {base} {' '.join(spec)}")
            if not ok:
                d = next(i for i in range(min(len(g), len(p))) if g[i] != p[i])
                print(f"    first difference at file offset {d:#x}  (sizes {len(g)} / {len(p)})")

        os.environ["LANIAKEA_ASM"] = "gnu"
        fw = patchlib.Firmware(ensure_official(base))
        seg = fw.app.segments[fw.sym["text_segment"]]
        data = fw.read(seg.load_addr, seg.length)
        ours = {a: (h, t) for a, h, t in xtasm.disasm(data, seg.load_addr)}
        n = mism = 0
        for a, h, t in fw.disasm(seg.load_addr, seg.length):
            if a not in ours or t.startswith(".byte"):
                continue
            oh, ot = ours[a]
            if oh != h:
                mism += 1
                if mism < 10:
                    print(f"    length mismatch at {a:#x}: objdump {h} {t!r} / xtasm {oh} {ot!r}")
            elif ot != "?":
                n += 1
                if ot != re.sub(r" \(0x[0-9a-f]+\)$", "", t):   # objdump adds the l32r literal value
                    mism += 1
                    if mism < 10:
                        print(f"    text mismatch at {a:#x} ({h}): objdump {t!r} / xtasm {ot!r}")
        bad += mism > 0
        print(f"{'OK ' if not mism else 'BAD'} disasm {base}: {n} decoded instructions compared, {mism} mismatches")
    if bad:
        raise SystemExit(f"{bad} failure(s)")
    print("all OK")


if __name__ == "__main__":
    main()
