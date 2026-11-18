"""Usability fixes: make the module predictable, especially right after a factory reset.

1. space_default / space_default_freq - factory-reset SPACE amounts (stock: 75 % for all 7).
   Stock behaviour after a reset: with the big SPACE! knob down, every parameter (including
   pitch) runs at 25 % of its knob, so the module seems silent or plays sub-bass.
   - space_default (%, default 25): ORBITS, COLOR, SHAPE, EFFECTS, CLUSTER. SPACE! still
     does something after a reset, but gently.
   - space_default_freq (%, default 0): pitch. Any amount makes SPACE! drop the pitch (25 %
     = about two octaves at SPACE! minimum). With the quantizer this slot is the scale, so
     0 = quantizer off.
   - The SPACE! knob's own slot is always 0: unused by stock firmware, quantizer root = C.
   Only affects a factory reset / first boot; values set in the SPACE menu are saved as usual.
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
    "space_default": (25.0, "factory-reset SPACE amount in % for ORBITS/COLOR/SHAPE/EFFECTS/CLUSTER (stock 75)"),
    "space_default_freq": (0.0, "factory-reset SPACE amount in % for FREQ/pitch (stock 75; quantizer: scale slot)"),
    "y_top": (0.88, "ORBITS-menu SHAPE position of the last row (stock ~0.78; must be < 0.94)"),
    "freq_semis": (12.0, "FREQ span in fixed-octave ranges (stock 7; 0 = keep)"),
}
TARGETS = ["3.6"]
ORDER = 10          # before cv_to_y, which reads fw.meta["y_scale"]

SPACE_DEFAULT_STORES = 0x400E4AC6  # 15 bytes: 7x s32i a8, a2, 0..24 (a8 = 0.75, a2 = 0x3ffc35d0)
SPACE_DEFAULT_RESUME = 0x400E4AD5  # call8 nvs_open ("storage") - a10..a12 are its args: don't touch
Y_SCALE_LOAD = 0x400DD1FF         # l32r a8, =9.0   (voice renderer: row = Y * 9)
FREQ_SPAN_LOAD = 0x400E2F2B       # l32r a10, =7.0  (mixer: (oct-1)*12 + FREQ*7 + 12)


def _reload(fw, addr, reg, value, name):
    insn = fw.disasm(addr, 3)[0][2]
    if not insn.startswith(f"l32r\t{reg},"):
        raise ValueError(f"unexpected instruction at {addr:#x}: {insn}")
    fw.hook(addr, expect=fw.read(addr, 3), name=name, literals={"v": float(value)},
            body=f"    l32r    {reg}, lit_v\n")


def apply(fw, space_default, space_default_freq, y_top, freq_semis):
    for v in (space_default, space_default_freq):
        if not 0 <= v <= 100:
            raise ValueError("SPACE defaults are percentages (0..100)")
    n = SPACE_DEFAULT_RESUME - SPACE_DEFAULT_STORES
    insns = [t for _a, _h, t in fw.disasm(SPACE_DEFAULT_STORES, n)]
    if len(insns) != 7 or not all(t.startswith("s32i") and "a8, a2" in t for t in insns):
        raise ValueError(f"unexpected code at SPACE defaults: {insns}")
    # slots (val_1..val_7): +0 FREQ, +4 ORBITS, +8 COLOR, +12 SHAPE, +16 SPACE!, +20 EFFECTS, +24 CLUSTER
    fw.hook(SPACE_DEFAULT_STORES, expect=fw.read(SPACE_DEFAULT_STORES, n), resume=SPACE_DEFAULT_RESUME,
            name="space_defaults", literals={"other": space_default / 100.0, "freq": space_default_freq / 100.0},
            body="""
    l32r    a8, lit_other
    l32r    a9, lit_freq
    s32i    a9, a2, 0               /* FREQ (pitch / quantizer scale) */
    s32i    a8, a2, 4               /* ORBITS */
    s32i    a8, a2, 8               /* COLOR */
    s32i    a8, a2, 12              /* SHAPE */
    movi    a9, 0
    s32i    a9, a2, 16              /* SPACE! slot: unused stock / quantizer root = C */
    s32i    a8, a2, 20              /* EFFECTS */
    s32i    a8, a2, 24              /* CLUSTER */
""")
    if y_top:
        if not 0.5 <= y_top < 0.94:
            raise ValueError("y_top must be between 0.5 and 0.94 (additive starts at 0.94/0.95)")
        k = 7.0 / y_top
        _reload(fw, Y_SCALE_LOAD, "a8", k, "y_scale")
        fw.meta["y_scale"] = k
    if freq_semis:
        _reload(fw, FREQ_SPAN_LOAD, "a10", freq_semis, "freq_span")
    fw.tag("usab")
