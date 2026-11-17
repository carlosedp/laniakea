import re, sys, difflib
sys.argv  # usage: fnpair.py dirA addrA dirB addrB
def get(d, addr):
    src = open(f"{d}/decompiled.c", encoding="utf-8", errors="replace").read()
    for p in re.split(r"\n// ==== ", src)[1:]:
        head, _, body = p.partition("\n")
        if int(head.split("@ ")[1].split()[0], 16) == addr:
            b = re.sub(r"\b(FUN|DAT|LAB|PTR|_DAT|uRam)_?([0-9a-fA-F]{6,})", "SYM", body)
            b = re.sub(r"\b(uVar|iVar|fVar|pfVar|puVar|piVar|bVar|cVar|sVar|local_|auStack_|fStack_|uStack_|iStack_|pfStack_|pcVar)\w*", "V", b)
            return [l.strip() for l in b.splitlines() if l.strip()]
a = get(sys.argv[1], int(sys.argv[2], 16)); b = get(sys.argv[3], int(sys.argv[4], 16))
for l in difflib.unified_diff(a, b, sys.argv[1], sys.argv[3], n=1, lineterm=""):
    print(l)
