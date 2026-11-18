"""Scale quantizer for pitch (FREQ knob + V/OCT), controlled from the SPACE menu.

  SPACE menu -> FREQ knob    : scale (12 zones, zone 1 = off). See SCALES below.
  SPACE menu -> SPACE! knob  : root / key (12 zones: C, C#, D ... B).

The *total* pitch (FREQ + V/OCT) snaps to the nearest note of the scale, so turning FREQ
steps through the scale (small bumps stay in key) and V/OCT sequences land in key.
The engine uses MIDI note numbers (note 69 = 440 Hz), so keys are absolute.

Side effects (by design):
  - SPACE! no longer bends pitch (the SPACE-menu FREQ slot now selects the scale).
  - The SPACE-menu slot of the SPACE! knob (stored but unused by stock firmware) is the root.
  - After a factory reset, SPACE-menu FREQ defaults to 75 % = zone 10: set it fully
    counter-clockwise to switch the quantizer off.
Hysteresis of `hyst` semitones avoids note flicker from CV noise near boundaries.
State (last note) lives in RTC slow memory at 0x50001F80.
"""

DESCRIPTION = "Scale quantizer: SPACE-menu FREQ = scale, SPACE-menu SPACE! = root"
OPTIONS = {
    "scales": ("chromatic,major,minor,harmonic_minor,major_pentatonic,minor_pentatonic,"
               "dorian,mixolydian,spanish,blues,whole_tone",
               "comma list (max 15) of scales for zones 2..; zone 1 is always 'off'"),
    "hyst": (0.12, "hysteresis in semitones"),
}
TARGETS = ["3.6", "3.7"]

LIBRARY = {
    "chromatic": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "harmonic_minor": [0, 2, 3, 5, 7, 8, 11],
    "melodic_minor": [0, 2, 3, 5, 7, 9, 11],
    "major_pentatonic": [0, 2, 4, 7, 9],
    "minor_pentatonic": [0, 3, 5, 7, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "lydian": [0, 2, 4, 6, 7, 9, 11],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "locrian": [0, 1, 3, 5, 6, 8, 10],
    "spanish": [0, 1, 4, 5, 7, 8, 10],        # phrygian dominant
    "blues": [0, 3, 5, 6, 7, 10],
    "whole_tone": [0, 2, 4, 6, 8, 10],
    "iwato": [0, 1, 5, 6, 10],
    "hirajoshi": [0, 2, 3, 7, 8],
    "fourths": [0, 5, 10],
    "fifths": [0, 7],
    "octaves": [0],
}

STATE = 0x50001F80            # [0] last output (float), [4] magic
# hook sites (tools/symbols.py): pitch_sum = add.s f0, f2, f3 (total pitch: V/OCT + FREQ note),
# freq_space_msub = msub.s f3, f2, f1 (note -= SPACE amount * note)


def nearest_table(degrees):
    """13 entries: for semitone n (0..12) the nearest scale degree (12 = next octave's root)."""
    cand = sorted(set(degrees)) + [12]
    return [min(cand, key=lambda d: (abs(d - n), d)) for n in range(13)]


def apply(fw, scales, hyst):
    names = [s.strip() for s in scales.split(",") if s.strip()]
    unknown = [n for n in names if n not in LIBRARY]
    if unknown:
        raise ValueError(f"unknown scale(s) {unknown}; available: {', '.join(LIBRARY)}")
    if not 1 <= len(names) <= 15:
        raise ValueError("1..15 scales")
    nzones = len(names) + 1                                  # zone 0 = off
    table = [0] * 13 + [d for n in names for d in nearest_table(LIBRARY[n])]
    # 32-bit words: the cave is flash on the instruction bus, which only allows 32-bit loads.
    table_addr = fw.add_code(name="quant_table", body="    .word " + ",".join(map(str, table)) + "\n")

    # 1) SPACE no longer scales the FREQ note: msub.s f3,f2,f1 -> mov.s f3,f1
    HOOK, SPACE_ON_FREQ = fw.sym["pitch_sum"], fw.sym["freq_space_msub"]
    fw.replace(SPACE_ON_FREQ, "    mov.s   f3, f1\n", expect=fw.read(SPACE_ON_FREQ, 3))

    # 2) quantize the total pitch. Free here: a8 a9 a11 a12 a13 a15, f1-f6. Live: f0 (result), f7, a14.
    fw.hook(HOOK, expect=fw.read(HOOK, 3), name="quantizer", literals={
        "space": fw.sym["space_amounts"],   # SPACE-menu values: +0 FREQ (val_1), +16 SPACE! (val_5)
        "nzones": float(nzones), "twelve": 12.0, "inv12": 1.0 / 12.0, "hyst": float(hyst),
        "state": STATE, "magic": 0x9A470001, "table": table_addr,
    }, body=f"""
    {{orig}}                          /* f0 = total pitch in MIDI semitones */
    l32r    a8, lit_space
    lsi     f2, a8, 0               /* val_1: SPACE-menu FREQ = scale selector */
    l32r    a9, lit_nzones
    wfr     f3, a9
    mul.s   f2, f2, f3
    trunc.s a9, f2, 0               /* zone */
    bgei    a9, 1, 2f               /* zone 0 = off */
    j       9f
2:
    movi    a11, {nzones - 1}
    min     a9, a9, a11
    lsi     f2, a8, 16              /* val_5: SPACE-menu SPACE! = root */
    l32r    a11, lit_twelve
    wfr     f3, a11                 /* f3 = 12.0 */
    mul.s   f2, f2, f3
    trunc.s a11, f2, 0
    movi    a12, 11
    min     a11, a11, a12
    movi    a12, 0
    max     a11, a11, a12
    float.s f4, a11, 0              /* f4 = root */
    l32r    a12, lit_state
    l32i    a13, a12, 4
    l32r    a15, lit_magic
    beq     a13, a15, 1f
    s32i    a15, a12, 4             /* first use after power-up */
    ssi     f0, a12, 0
1:
    lsi     f5, a12, 0              /* last output */
    sub.s   f5, f5, f0              /* d = last - P */
    l32r    a13, lit_hyst
    wfr     f6, a13
    olt.s   b0, f6, f5
    movt.s  f5, f6, b0              /* d = min(d, +h) */
    neg.s   f6, f6
    olt.s   b0, f5, f6
    movt.s  f5, f6, b0              /* d = max(d, -h) */
    add.s   f5, f0, f5              /* P biased towards the last note (hysteresis) */
    sub.s   f5, f5, f4              /* relative to root */
    l32r    a13, lit_inv12
    wfr     f6, a13
    mul.s   f6, f5, f6
    floor.s a13, f6, 0              /* octave */
    float.s f6, a13, 0
    msub.s  f5, f6, f3              /* semitone within octave, 0..12 */
    round.s a15, f5, 0
    movi    a8, 12
    min     a15, a15, a8
    movi    a8, 0
    max     a15, a15, a8            /* n = 0..12 */
    movi    a11, 13
    mull    a11, a9, a11
    add     a11, a11, a15
    l32r    a8, lit_table
    addx4   a11, a11, a8
    l32i    a11, a11, 0             /* nearest scale degree (0..12), word table */
    float.s f5, a11, 0
    madd.s  f5, f6, f3              /* degree + 12 * octave */
    add.s   f0, f5, f4              /* + root */
    ssi     f0, a12, 0              /* remember for hysteresis */
9:
""")
    fw.meta["quant_zones"] = nzones      # led_menus flashes the ring when the zone changes
    fw.tag("quant")
    return [f"zone {i + 2}: {n}" for i, n in enumerate(names)]
