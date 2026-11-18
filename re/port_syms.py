"""Port the RE symbol table (tools/symbols.py) from one firmware version to another.

usage: python re/port_syms.py firmware/official/laniakea/laniakea_v3.6.bin firmware/official/laniakea/laniakea_v3.7.bin

How:
- disassemble .flash.text of both images and normalise every instruction: branch/call targets
  become "T", l32r operands become the literal's *category* (DRAM/DROM/RTC/CODE) or its exact
  value when it is a plain constant (floats, masks...);
- align the two instruction streams (difflib) -> old code address -> new code address;
- every aligned l32r pair maps an old data address to a new one (consensus vote); addresses that
  are only reached as base+offset take the delta of the nearest mapped address below them.
Prints a proposed V3_x dict, with a confidence note per entry. Review before using it.
"""
import bisect
import difflib
import hashlib
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import espimage            # noqa: E402
import symbols             # noqa: E402
from patchlib import TOOL  # noqa: E402


class Img:
    def __init__(self, path):
        self.buf = Path(path).read_bytes()
        self.sha = hashlib.sha256(self.buf).hexdigest()
        self.app = espimage.parse_image(self.buf, espimage.APP_OFFSET)

    def read(self, addr, n):
        o = self.app.addr_to_offset(addr)
        return None if o is None else self.buf[o:o + n]

    def word(self, addr):
        b = self.read(addr, 4)
        return None if b is None or len(b) < 4 else int.from_bytes(b, "little")

    def disasm_text(self, seg_index):
        seg = self.app.segments[seg_index]
        data = self.read(seg.load_addr, seg.length)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.bin"
            p.write_bytes(data)
            out = subprocess.run([TOOL("objdump"), "-D", "-b", "binary", "-m", "xtensa",
                                  f"--adjust-vma={seg.load_addr:#x}", str(p)],
                                 capture_output=True, text=True, check=True).stdout
        res = []
        for line in out.splitlines():
            m = re.match(r"\s*([0-9a-f]+):\s+([0-9a-f]+)\s+(.*)", line)
            if m:
                res.append((int(m.group(1), 16), m.group(3).strip()))
        return res


def category(v):
    if v is None:
        return "?"
    if 0x3F400000 <= v < 0x3F800000:
        return "DROM"
    if 0x3FF80000 <= v < 0x40000000:
        return "DRAM"
    if 0x40000000 <= v < 0x40400000:
        return "CODE"
    if 0x50000000 <= v < 0x50002000:
        return "RTC"
    return f"#{v:x}"


def normalise(img, insns):
    norm, lits = [], []
    for addr, text in insns:
        lit = None
        m = re.match(r"l32r\s+(\w+),\s*0x([0-9a-f]+)", text)
        if m:
            lit = img.word(int(m.group(2), 16))
            text = f"l32r {m.group(1)},{category(lit)}"
        else:
            text = re.sub(r"0x4[0-9a-f]{7}", "T", text)
        norm.append(text)
        lits.append(lit)
    return norm, lits


def main(old_path, new_path):
    old, new = Img(old_path), Img(new_path)
    ver, sym = symbols.BY_SHA256[old.sha]
    seg = sym["text_segment"]
    oi, ni = old.disasm_text(seg), new.disasm_text(seg)
    on, ol = normalise(old, oi)
    nn, nl = normalise(new, ni)
    sm = difflib.SequenceMatcher(None, on, nn, autojunk=False)
    code_map = {}
    data_votes = defaultdict(Counter)
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            code_map[oi[a + k][0]] = ni[b + k][0]
            lo, ln = ol[a + k], nl[b + k]
            if lo is not None and ln is not None and category(lo) in ("DRAM", "DROM", "RTC", "CODE"):
                data_votes[lo][ln] += 1
    matched = sum(s for *_, s in sm.get_matching_blocks())
    print(f"# {ver} -> {Path(new_path).name}: {matched}/{len(on)} instructions aligned", file=sys.stderr)

    data_map = {o: c.most_common(1)[0][0] for o, c in data_votes.items()}
    keys = sorted(data_map)

    def map_code(a):
        if a in code_map:
            return code_map[a], "aligned"
        return None, "NOT ALIGNED"

    def map_data(a):
        if a in data_map:
            n = sum(data_votes[a].values())
            agree = data_votes[a].most_common(1)[0][1]
            return data_map[a], f"literal {agree}/{n}"
        i = bisect.bisect_right(keys, a) - 1
        if i >= 0 and a - keys[i] < 0x200 and category(keys[i]) == category(a):
            base = keys[i]
            return a - base + data_map[base], f"base {base:#x}+{a - base:#x}"
        return None, "NOT FOUND"

    def port(v, key=""):
        if isinstance(v, int) and v >= 0x3F000000:
            fn = map_code if category(v) == "CODE" else map_data
            nv, how = fn(v)
            return nv, [(key, v, nv, how)]
        if isinstance(v, tuple):
            out, notes = [], []
            for i, x in enumerate(v):
                nx, nt = port(x, f"{key}[{i}]")
                out.append(nx)
                notes += nt
            return tuple(out), notes
        if isinstance(v, list):
            out, notes = [], []
            for i, x in enumerate(v):
                nx, nt = port(x, f"{key}[{i}]")
                out.append(nx)
                notes += nt
            return out, notes
        if isinstance(v, dict):
            out, notes = {}, []
            for k, x in v.items():
                nx, nt = port(x, f"{key}.{k}" if key else k)
                out[k] = nx
                notes += nt
            return out, notes
        return v, []

    new_sym, notes = port(sym)
    for key, o, n, how in notes:
        flag = "" if n is not None else "   <<<<"
        print(f"{key:28s} {o:#010x} -> {('%#010x' % n) if n is not None else '?':10s}  {how}{flag}")
    return new_sym, code_map, data_map


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
