"""Usability fixes: make the module predictable, especially right after a factory reset.

1. space_defaults - factory-reset defaults for all 7 SPACE amounts become 0 (stock: 75 %).
   Stock behaviour after a reset: with the big SPACE! knob down, every parameter (including
   pitch) runs at 25 % of its knob, so the module seems silent or plays sub-bass. With this
   fix a reset gives "knobs do what they say". (Only affects reset/first boot; values you
   set in the SPACE menu are still saved as usual.) With the quantizer patch, this also
   means the quantizer starts switched off.
2. y_top - in the ORBITS menu, SHAPE reaches the last wavetable row at `y_top` of its travel
   (stock: ~0.78, then a long dead zone until the additive oscillator at 0.95). Default 0.88
   spreads the 8 rows wider and keeps a small dead zone before additive.
3. freq_semis - in the ORBITS-menu fixed-octave FREQ ranges, the FREQ knob spans this many
   semitones (stock: 7, though the manual says 12). 0 = keep stock.

The renderer multiplies Y by 9 and the FREQ range uses 7.0, both loaded from a literal pool
shared with other code. So each load is redirected to a 2-instruction trampoline that loads
the new constant into the same register.
"""

DESCRIPTION = "Usability: sane reset defaults, wider wavetable rows, 12-semitone FREQ ranges"
OPTIONS = {
    "space_defaults": (True, "factory-reset SPACE amounts = 0 (stock 0.75)"),
    "y_top": (0.88, "ORBITS-menu SHAPE position of the last row (stock ~0.78; must be < 0.94)"),
    "freq_semis": (12.0, "FREQ span in fixed-octave ranges (stock 7; 0 = keep)"),
}
TARGETS = ["3.6"]
ORDER = 10          # before cv_to_y, which reads fw.meta["y_scale"]

SPACE_DEFAULT_LOAD = 0x400E4ABA   # l32r a8, =0.75  (then 7x s32i a8 -> SPACE amounts)
Y_SCALE_LOAD = 0x400DD1FF         # l32r a8, =9.0   (voice renderer: row = Y * 9)
FREQ_SPAN_LOAD = 0x400E2F2B       # l32r a10, =7.0  (mixer: (oct-1)*12 + FREQ*7 + 12)


def _reload(fw, addr, reg, value, name):
    insn = fw.disasm(addr, 3)[0][2]
    if not insn.startswith(f"l32r\t{reg},"):
        raise ValueError(f"unexpected instruction at {addr:#x}: {insn}")
    fw.hook(addr, expect=fw.read(addr, 3), name=name, literals={"v": float(value)},
            body=f"    l32r    {reg}, lit_v\n")


def apply(fw, space_defaults, y_top, freq_semis):
    if space_defaults:
        if not fw.disasm(SPACE_DEFAULT_LOAD, 3)[0][2].startswith("l32r\ta8,"):
            raise ValueError("unexpected code at SPACE defaults")
        fw.replace(SPACE_DEFAULT_LOAD, "    movi    a8, 0\n", expect=fw.read(SPACE_DEFAULT_LOAD, 3))
    if y_top:
        if not 0.5 <= y_top < 0.94:
            raise ValueError("y_top must be between 0.5 and 0.94 (additive starts at 0.94/0.95)")
        k = 7.0 / y_top
        _reload(fw, Y_SCALE_LOAD, "a8", k, "y_scale")
        fw.meta["y_scale"] = k
    if freq_semis:
        _reload(fw, FREQ_SPAN_LOAD, "a10", freq_semis, "freq_span")
    fw.tag("usab")
