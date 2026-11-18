"""Tame the string model's bow excitation (ORBITS-menu EFFECTS <= 50 %).

Stock (RE: docs/RE-NOTES.md): in bow mode the string is driven, all the time and even with no
cable in EXCITER, by sparse noise impulses. The ORBITS knob sets their density d = ORBITS^2, and
each impulse is scaled by (1/d) * (8 - 6d). At low ORBITS the impulses are rare but huge (a loud
crackle), at high ORBITS continuous noise; the string itself runs up to ~20x the oscillator's
level. So as soon as SHAPE brings the string in (from ~0.7), a hard noise dominates, even with
ORBITS low.

- level: scales the bow excitation (stock 1.0).
- even:  impulses scaled by 1/sqrt(d) instead of 1/d, so the bow has the same energy at every
         ORBITS setting: low ORBITS gives a fine grain instead of loud cracks.
Pluck is unchanged.
"""

DESCRIPTION = "Tame the harsh bow noise of the string model: lower level, same energy at any ORBITS"
OPTIONS = {
    "level": (0.3, "bow excitation level, 0.0..1.0 (stock 1.0)"),
    "even": (True, "same bow energy at every ORBITS position (stock: louder, crackly at low ORBITS)"),
}
RANGES = {"level": (0.0, 1.0)}
TARGETS = ["3.6", "3.7"]


def apply(fw, level, even):
    if not 0.0 <= level <= 1.0:
        raise ValueError("level must be 0.0..1.0")
    s = fw.sym

    if even:
        site = s["string_inv_density_store"]
        insns = [t for _a, _h, t in fw.disasm(site, 5)]
        if insns != ["s32i.n\ta10, a2, 16", "wfr\tf0, a8"]:
            raise ValueError(f"unexpected code at string_inv_density_store {site:#x}: {insns}")
        # a10 = 1/d; d ~= ORBITS^2 so (1/d) * ORBITS ~= 1/sqrt(d). a11, f2, f3 and b0 are free here
        # (a11 is reloaded, f3 reloaded from the stack, f2 written before use).
        fw.hook(site, expect=fw.read(site, 5), name="bow_even", literals={"floor": 0.0071}, body="""
    lsi     f2, a1, 12              /* ORBITS (the density's square root) */
    l32r    a11, lit_floor
    wfr     f3, a11
    olt.s   b0, f2, f3
    movt.s  f2, f3, b0              /* max(ORBITS, sqrt of the minimum density) */
    wfr     f3, a10
    mul.s   f3, f3, f2
    rfr     a10, f3                 /* 1/sqrt(d) */
    {orig}
""")

    if level != 1.0:
        site = s["string_bow_gain_site"]
        if fw.disasm(site, 3)[0][2] != "wfr\tf6, a6":
            raise ValueError(f"unexpected code at string_bow_gain_site {site:#x}")
        # f7 = bow gain, a7 = bow flag; a8 and f0 are written right after this instruction.
        fw.hook(site, expect=fw.read(site, 3), name="bow_level", literals={"level": float(level)}, body="""
    {orig}
    beqz    a7, 1f                  /* pluck: unchanged */
    l32r    a8, lit_level
    wfr     f0, a8
    mul.s   f7, f7, f0
1:
""")
    fw.tag(f"bow{int(round(level * 100))}" + ("e" if even else ""))
