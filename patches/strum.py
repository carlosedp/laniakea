"""Internal exciter ("strum", like Mutable Instruments Rings): with no cable in EXCITER, every
new note strikes the resonator and the LPG, as if a trigger had been patched into EXCITER.

- Active when nothing is plugged into EXCITER and the ORBITS-menu EFFECTS (string mode) is
  on **pluck** (> 50 %). On **bow** the module behaves as stock: no cable = open drone.
  With `mode=always`, the internal exciter is used whatever the string mode.
- A "new note" is the final pitch (V/OCT + FREQ, after the quantizer if present) moving to
  another semitone, with `hyst` semitones of hysteresis against CV noise. With the quantizer,
  each quantized step is a note.
- The strike is a `gate_ms` pulse at level `strength` into the EXCITER path, so everything
  the firmware does with a real trigger applies: LPG strike and decay (ORBITS-menu ORBITS),
  pluck burst into the string model (SHAPE > 0.7 brings in the string), brightness by level.
- A cable in EXCITER always wins: the patch then does nothing.

How (RE: docs/RE-NOTES.md): adc_task reads the CVs and the jack-detect flags, then runs the
mixer task. A wrapper around that call decides after each run whether the internal exciter is
active and publishes an "effective jack flag" and a virtual EXCITER level. The unpatched-EXCITER
path of adc_task stores the virtual level instead of 0, and the two places that read the jack
flag (the mixer's trigger logic and the audio task's LPG) read the effective flag instead.
State lives in RTC slow memory (0x50001E80).
"""

DESCRIPTION = "Internal exciter like Rings: with nothing in EXCITER and string mode = pluck, each new note strikes"
OPTIONS = {
    "mode": ("pluck", "pluck = only when ORBITS-menu EFFECTS is on pluck (bow = stock drone); always = whenever EXCITER is empty"),
    "strength": (0.8, "strike level 0.3..1.0, like the EXCITER voltage (higher = brighter strike)"),
    "gate_ms": (10, "length of the internal trigger pulse in ms"),
    "hyst": (0.3, "pitch hysteresis in semitones before a new note counts (against CV noise)"),
    "lpg": (True, "true = each note opens the LPG (whole voice plucks, silent in between, like a cable in EXCITER); "
                  "false = only the string is plucked, the oscillator keeps sounding"),
    "reset_bow": (True, "factory reset sets the string mode to bow (stock: pluck), so a reset module drones instead of waiting for notes"),
}
RANGES = {"strength": (0.3, 1.0), "gate_ms": (2, 100), "hyst": (0.05, 0.49)}
TARGETS = ["3.6", "3.7"]

STATE = 0x50001E80   # [0] effective jack flag, [4] virtual level (float), [8] note centre (float),
                     # [12] gate end (us, low word), [16] magic, [20] note valid


def _redirect_call(fw, site, expected_target, new_target):
    insn = fw.disasm(site, 3)[0][2]
    if not (insn.startswith("call8") and f"{expected_target:#x}"[2:] in insn):
        raise ValueError(f"unexpected instruction at {site:#x}: {insn}")
    code, _ = fw.asm("    call8   __t\n", site, {"__t": new_target})
    fw.write(site, code, expect=fw.read(site, 3))


def apply(fw, mode, strength, gate_ms, hyst, lpg, reset_bow):
    if mode not in ("pluck", "always"):
        raise ValueError("mode must be pluck or always")
    if not 0.3 <= strength <= 1.0:
        raise ValueError("strength must be 0.3..1.0 (the trigger needs > 0.24)")
    if not 0.05 <= hyst < 0.5:
        raise ValueError("hyst must be 0.05..0.49 semitones")
    s = fw.sym

    # 1) wrapper around the mixer task: run it, then decide the internal exciter for the next pass
    mode_check = "" if mode == "always" else """
    l32r    a4, lit_modores
    lsi     f0, a4, 0
    l32r    a4, lit_half
    wfr     f1, a4
    olt.s   b0, f1, f0              /* pluck: string mode > 0.5 */
    bf      b0, .Lset
"""
    tick = fw.add_code(name="strum_tick", literals={
        "mixer": s["mixer_task_fn"], "state": STATE, "magic": 0x57A0C0DE, "jack": s["exciter_jack_flag"],
        "modores": s["secondary"]["modores"], "half": 0.5, "pitch": s["pitch_out"], "k108": 108.0,
        "thresh": 0.5 + hyst, "gate": int(gate_ms * 1000), "level": float(strength),
        "timer": s["esp_timer_get_time"]}, body=f"""
    entry   a1, 48
    l32r    a8, lit_mixer
    callx8  a8                      /* original: pots, menus, param_mix */
    l32r    a2, lit_state
    l32i    a3, a2, 16
    l32r    a4, lit_magic
    beq     a3, a4, .Linit
    s32i    a4, a2, 16              /* first run since power-up */
    movi    a3, 0
    s32i    a3, a2, 20              /* no note yet */
    s32i    a3, a2, 4
.Linit:
    l32r    a3, lit_jack
    l8ui    a3, a3, 0               /* real jack flag: 1 = cable in EXCITER */
    movi    a5, 0                   /* internal exciter active? */
    bnez    a3, .Lset{mode_check}
    movi    a5, 1
.Lset:
    or      a6, a3, a5
    s32i    a6, a2, 0               /* effective flag for the mixer and the audio task */
    bnez    a5, .Lactive
    movi    a6, 0
    s32i    a6, a2, 4               /* virtual level 0 */
    s32i    a6, a2, 20              /* forget the note: no strike when it becomes active */
    retw
.Lactive:
    l32r    a8, lit_timer
    callx8  a8                      /* esp_timer_get_time: a10 = low word (us) */
    mov     a7, a10
    l32r    a4, lit_pitch
    lsi     f0, a4, 0
    l32r    a4, lit_k108
    wfr     f1, a4
    mul.s   f0, f0, f1              /* pitch in semitones */
    l32i    a6, a2, 20
    bnez    a6, .Lcmp
    round.s a6, f0, 0               /* first note: remember it, no strike */
    float.s f2, a6, 0
    ssi     f2, a2, 8
    movi    a6, 1
    s32i    a6, a2, 20
    s32i    a7, a2, 12
    j       .Llevel
.Lcmp:
    lsi     f2, a2, 8               /* current note centre */
    sub.s   f3, f0, f2
    abs.s   f3, f3
    l32r    a4, lit_thresh
    wfr     f4, a4
    olt.s   b0, f4, f3              /* moved more than 0.5 + hyst semitones? */
    bf      b0, .Llevel
    round.s a6, f0, 0               /* new note: strike */
    float.s f2, a6, 0
    ssi     f2, a2, 8
    l32r    a6, lit_gate
    add     a6, a7, a6
    s32i    a6, a2, 12
.Llevel:
    l32i    a6, a2, 12
    sub     a6, a7, a6              /* now - gate end (wraps safely) */
    movi    a8, 0
    bgez    a6, .Lstore
    l32r    a8, lit_level
.Lstore:
    s32i    a8, a2, 4               /* virtual EXCITER level */
    retw
""")
    _redirect_call(fw, s["adc_mixer_call"], s["mixer_task_fn"], tick)

    # 2) adc_task, EXCITER unpatched: store the virtual level instead of 0
    site = s["adc_exc_unpatched"]
    insns = [t for _a, _h, t in fw.disasm(site, 5)]
    if insns != ["movi.n\ta11, 0", "wfr\tf0, a11"]:
        raise ValueError(f"unexpected code at adc_exc_unpatched {site:#x}: {insns}")
    fw.hook(site, expect=fw.read(site, 5), name="strum_level", literals={"state": STATE}, body="""
    l32r    a11, lit_state
    lsi     f0, a11, 4              /* virtual level (a11 is overwritten right after) */
""")

    # 3) the jack-flag reads: mixer (trigger logic) and audio task (LPG)
    #    lpg=false: only the mixer (trigger -> string pluck) sees the virtual cable; the audio task
    #    still sees "no cable" and holds the LPG open, so the oscillator keeps sounding.
    sites = [("mixer_jack_load", "a4")] + ([("motor_jack_load", "a8")] if lpg else [])
    for key, reg in sites:
        site = s[key]
        if fw.disasm(site, 3)[0][2] != f"l8ui\t{reg}, a8, 1":
            raise ValueError(f"unexpected code at {key} {site:#x}")
        fw.hook(site, expect=fw.read(site, 3), name=f"strum_{key}", literals={"state": STATE}, body=f"""
    l32r    {reg}, lit_state
    l32i    {reg}, {reg}, 0         /* effective jack flag */
""")
    # 4) factory-reset default of the string mode: bow (0.25) instead of pluck (0.9). The 0.9
    #    literal is shared, so only this load is redirected.
    if reset_bow:
        site, reg = s["modores_default_load"]
        insn = fw.disasm(site, 3)[0][2]
        if not insn.startswith(f"l32r\t{reg},"):
            raise ValueError(f"unexpected instruction at modores_default_load {site:#x}: {insn}")
        fw.hook(site, expect=fw.read(site, 3), name="strum_reset_bow", literals={"v": 0.25},
                body=f"    l32r    {reg}, lit_v               /* string mode default: bow */\n")
    fw.tag(("strum" if mode == "pluck" else "strum-always") + ("" if lpg else "-string"))
