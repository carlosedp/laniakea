"""Diff two Ghidra decompile exports by normalised function bodies.
usage: python -I re/fndiff.py re/ghidra/v3.3 re/ghidra/v3.4"""
import re, sys, difflib
from collections import defaultdict

def load(d):
    src = open(f"{d}/decompiled.c", encoding="utf-8", errors="replace").read()
    fns = {}
    for p in re.split(r"\n// ==== ", src)[1:]:
        head, _, body = p.partition("\n")
        name = head.split(" ")[0]
        addr = int(head.split("@ ")[1].split()[0], 16)
        norm = re.sub(r"\b(FUN|DAT|LAB|PTR|s|_DAT|uRam|iRam|pcRam)_?[0-9a-fA-F]{6,}\w*", "SYM", body)
        norm = re.sub(r"0x(3f|40|3ff|50)[0-9a-f]{5,6}\b", "ADDR", norm)
        norm = re.sub(r"\b(uVar|iVar|fVar|pfVar|puVar|piVar|bVar|cVar|sVar|local_|auStack_|fStack_|uStack_|iStack_|pfStack_|pcVar)\w*", "V", norm)
        norm = re.sub(r"[ \t]+", " ", norm)
        fns[addr] = (name, norm, body)
    return fns

a, b = load(sys.argv[1]), load(sys.argv[2])
ia = defaultdict(list)
for ad, (n, norm, _) in a.items(): ia[norm].append(ad)
unmatched_b = [ad for ad, (n, norm, _) in b.items() if norm not in ia]
matched = len(b) - len(unmatched_b)
print(f"v_a {len(a)} fns, v_b {len(b)} fns, identical(normalised) {matched}, changed/new in b {len(unmatched_b)}")
# for each changed fn in b, find most similar fn in a (by size + ratio)
unmatched_a = set(ad for ad, (n, norm, _) in a.items() if norm not in {v[1] for v in b.values()})
for ad in sorted(unmatched_b):
    n, norm, body = b[ad]
    best, br = None, 0
    for aa in unmatched_a:
        na = a[aa][1]
        if abs(len(na) - len(norm)) > max(400, len(norm) * 0.5): continue
        r = difflib.SequenceMatcher(None, na, norm, autojunk=False).quick_ratio()
        if r > br: best, br = aa, r
    print(f"{ad:#x} {n:14s} len {len(norm):6d}  ~ {('%#x' % best) if best else '-':12s} sim {br:.2f}")
