"""Build patched Laniakea firmware from the official image + patch files in patches/.

  patcher.py list                                    available patches and their options
  patcher.py build PATCH[:opt=val,...] [PATCH...]    apply patches in order -> firmware/custom/
            [--base v3.6] [-o out.bin]
  patcher.py disasm ADDR [--bytes N]                 disassemble the official image around ADDR
  patcher.py find TEXT                               search strings -> functions (Ghidra export)
  patcher.py verify FILE.bin                         checksum / SHA-256 / app info

The official base image is downloaded from Magerit's public GitHub (sha256-verified)
the first time it's needed; it is never stored in this repository.

Presets:
  recommended   cv_to_y:source=effects led_dedupe   (EFFECTS jack -> wavetable Y + menu crackle fix)

Examples:
  patcher.py build recommended
  patcher.py build cv_to_y:source=effects
  patcher.py build cv_to_y:source=orbits,gain=-0.78 chords:set=pro
  patcher.py build chords:set=my_chords.txt
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import espimage  # noqa: E402
from patchlib import Firmware, PatchError  # noqa: E402
from laniakea import ensure_official  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PATCH_DIR = ROOT / "patches"
OUT_DIR = ROOT / "firmware" / "custom"
OFFICIAL = ROOT / "firmware" / "official" / "laniakea"
GHIDRA = ROOT / "re" / "ghidra"

PRESETS = {
    "recommended": ["cv_to_y:source=effects", "led_dedupe"],
}


def load_patch(name: str):
    path = PATCH_DIR / f"{name}.py"
    if not path.exists():
        raise SystemExit(f"no patch {name!r} (see `laniakea patcher list`)")
    spec = importlib.util.spec_from_file_location(f"patches.{name}", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_value(raw: str, default):
    if isinstance(default, bool):
        return raw.lower() in ("1", "true", "yes", "on")
    if isinstance(default, float):
        return float(raw)
    if isinstance(default, int):
        return int(raw, 0)
    return raw


def parse_spec(spec: str):
    name, _, opts = spec.partition(":")
    mod = load_patch(name)
    values = {k: d for k, (d, _h) in mod.OPTIONS.items()}
    for kv in filter(None, opts.split(",")):
        k, _, v = kv.partition("=")
        if k not in mod.OPTIONS:
            raise SystemExit(f"{name}: unknown option {k!r}; options: {', '.join(mod.OPTIONS)}")
        values[k] = parse_value(v, mod.OPTIONS[k][0])
    missing = [k for k, v in values.items() if v is None]
    if missing:
        raise SystemExit(f"{name}: option(s) required: {', '.join(missing)}  ({mod.OPTIONS[missing[0]][1]})")
    return name, mod, values


def cmd_list(a):
    for p in sorted(PATCH_DIR.glob("*.py")):
        if p.name.startswith("_"):
            continue
        mod = load_patch(p.stem)
        print(f"{p.stem:12s} {mod.DESCRIPTION}   [firmware {', '.join(mod.TARGETS)}]")
        for k, (d, h) in mod.OPTIONS.items():
            print(f"    {k}={d if d is not None else '<required>'}   {h}")


def cmd_build(a):
    base = ensure_official(a.base)        # downloaded from Magerit + sha256-checked if missing
    fw = Firmware(base)
    specs = [s for spec in a.patches for s in PRESETS.get(spec, [spec])]
    for spec in specs:
        name, mod, values = parse_spec(spec)
        if fw.version not in mod.TARGETS:
            raise SystemExit(f"{name} supports firmware {mod.TARGETS}, base is {fw.version}")
        try:
            res = mod.apply(fw, **values)
        except (PatchError, ValueError) as e:
            raise SystemExit(f"{name}: {e}")
        print(f"applied {name} {values}" + (f" -> {res}" if res else ""))
    out = Path(a.output) if a.output else OUT_DIR / f"laniakea_v{fw.version}+{'+'.join(fw.tags)}.bin"
    fw.save(out)
    for line in fw.log:
        print("   ", line)
    info = espimage.describe_merged(out.read_bytes())
    print(f"wrote {out}  ({out.stat().st_size} bytes)  version={info['app']['version']!r}  valid={info['app_ok']}")


def function_names():
    names = {}
    f = GHIDRA / "v3.6" / "functions.txt"
    if f.exists():
        for line in f.read_text().splitlines():
            p = line.split("\t")
            names[int(p[0], 16)] = (p[1], int(p[2]))
    return names


def cmd_disasm(a):
    fw = Firmware(ensure_official(a.base))
    addr = int(a.addr, 0)
    start = addr - a.before
    funcs = function_names()
    owner = max((f for f in funcs if f <= addr), default=None)
    if owner is not None:
        print(f"; inside {funcs[owner][0]} @ {owner:#x}")
    for ad, hx, text in fw.disasm(start, a.before + a.bytes):
        mark = ">>" if ad == addr else "  "
        print(f"{mark} {ad:08x}: {hx:8s} {text}")


def cmd_find(a):
    f = GHIDRA / "v3.6" / "string_xrefs.txt"
    if not f.exists():
        raise SystemExit("run scripts/ghidra_analyze.ps1 first")
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        if a.text.lower() in line.lower():
            addr, s, fns = (line.split("\t") + ["", ""])[:3]
            print(f"{addr}  {s[:70]!r:74s} {fns}")


def cmd_verify(a):
    info = espimage.describe_merged(Path(a.file).read_bytes())
    print(info)
    if not (info["bootloader_ok"] and info["app_ok"]):
        raise SystemExit("INVALID image")


def main(argv=None, prog=None):
    """argv/prog let `laniakea patcher ...` reuse this CLI in-process."""
    ap = argparse.ArgumentParser(prog=prog, description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    b = sub.add_parser("build"); b.add_argument("patches", nargs="+"); b.add_argument("--base", default="v3.6")
    b.add_argument("-o", "--output"); b.set_defaults(fn=cmd_build)
    d = sub.add_parser("disasm"); d.add_argument("addr"); d.add_argument("--bytes", type=int, default=32)
    d.add_argument("--before", type=int, default=0); d.add_argument("--base", default="v3.6"); d.set_defaults(fn=cmd_disasm)
    f = sub.add_parser("find"); f.add_argument("text"); f.set_defaults(fn=cmd_find)
    v = sub.add_parser("verify"); v.add_argument("file"); v.set_defaults(fn=cmd_verify)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
