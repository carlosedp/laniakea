"""Route a CV input to the wavetable Y axis (row).

Stock firmware: Y = settings.tabla (SHAPE knob inside the ORBITS menu), no CV at all.
Patched:        Y = clamp(tabla + gain * CV[source], 0, 7/9)
                (unless tabla >= 0.95, where the additive oscillator is selected - left alone)

With exclusive=1 (default) the chosen jack stops modulating its original knob, so
the jack is fully repurposed as "Y CV". The ORBITS-menu SHAPE position still sets
the starting row, so the CV modulates around it.

7/9 is the Y value of the last wavetable row (the engine computes row = tabla * 9,
clamped to 7), so gain = 7/9 sweeps rows at the same rate the SHAPE CV sweeps columns.
"""

DESCRIPTION = "Route a CV jack to the wavetable Y axis (row select)"
OPTIONS = {
    "source": (None, "CV jack to use: shape, cluster, color, orbits, space, effects"),
    "exclusive": (True, "remove the CV from its original knob (repurpose the jack)"),
    "gain": (7 / 9, "CV depth; 7/9 = same rows/volt as X columns; negative inverts"),
}
TARGETS = ["3.6"]


def apply(fw, source, exclusive, gain):
    if source not in fw.sym["cv"] or source == "exciter":
        raise ValueError(f"source must be one of {', '.join(fw.sym['cv_add'])}")
    addr, orig = fw.sym["y_load"]
    fw.hook(addr, expect=orig, name="cv_to_y", literals={
        "thr": 0.95,                     # tabla >= 0.95 selects the additive oscillator
        "max": 7 / 9,                    # last wavetable row
        "cv": fw.sym["cv"][source],      # address of the CV value (float)
        "gain": float(gain),
    }, body="""
    {orig}                          /* f1 = tabla (original instruction) */
    l32r    a8, lit_thr
    wfr     f2, a8
    ole.s   b0, f2, f1              /* additive osc selected? leave Y alone */
    bt      b0, 1f
    l32r    a8, lit_cv
    lsi     f2, a8, 0               /* f2 = CV */
    l32r    a8, lit_gain
    wfr     f0, a8
    madd.s  f1, f2, f0              /* Y += CV * gain */
    movi    a8, 0
    wfr     f2, a8
    olt.s   b0, f1, f2
    movt.s  f1, f2, b0              /* Y = max(Y, 0) */
    l32r    a8, lit_max
    wfr     f2, a8
    olt.s   b0, f2, f1
    movt.s  f1, f2, b0              /* Y = min(Y, 7/9) */
1:
""")
    if exclusive:
        a, o, asm = fw.sym["cv_add"][source]
        fw.replace(a, asm, expect=o)
    fw.tag(f"Y-{source}")
