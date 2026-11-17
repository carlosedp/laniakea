"""Template for a new patch. Copy to patches/my_patch.py (no leading underscore) and edit.

Build:   .venv\\Scripts\\python.exe tools\\patcher.py build my_patch:amount=0.5
Inspect: .venv\\Scripts\\python.exe tools\\patcher.py disasm 0x400e3110 --bytes 32

Workflow (see docs/PATCHING.md):
 1. Find the code: re/ghidra/v3.6/decompiled.c, string_xrefs.txt, docs/RE-NOTES.md.
 2. Pick an instruction to hook (>= 3 bytes, not PC-relative if you use {orig}).
 3. Check which registers are dead there (written before being read afterwards).
 4. Add the address/bytes to tools/symbols.py so the patch documents its assumptions.
"""

DESCRIPTION = "Example: scale the SHAPE CV before it is added to the SHAPE knob"
OPTIONS = {
    # name: (default, help).  The default's type is used to parse "name=value" on the command line.
    "amount": (0.5, "multiplier applied to the SHAPE CV"),
}
TARGETS = ["3.6"]


def apply(fw, amount):
    # In FUN_400e2bf4 the SHAPE CV is added to the knob with:  add.s f6, f6, f5  @ 0x400e2d4d
    # (f5 = CV, f6 = knob). Replace it with a hook that does f6 += f5 * amount.
    addr, orig, _ = fw.sym["cv_add"]["shape"]
    fw.hook(addr, expect=orig, name="shape_cv_scale",
            literals={"amount": float(amount)},
            body="""
    l32r    a8, lit_amount          /* a8 is reloaded right after this spot, so it's free */
    wfr     f7, a8                  /* f7 is written later before being read: free */
    madd.s  f6, f5, f7              /* f6 = knob + CV * amount */
""")
    fw.tag(f"shapecv{amount:g}")
