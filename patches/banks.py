"""Multiple wavetable banks stored on the module, selected from the SPACE menu.

  SPACE menu -> EFFECTS knob : bank (8 zones = banks 1..8, fully CCW = bank 1).
  The bank is loaded when you LEAVE the SPACE menu, and restored at power-up.

- Bank 1 is the stock storage (NVS keys onda_0..7), so existing uploads stay as they are.
  Banks 2..8 use keys ondb_*..ondh_*.
- An empty bank (or row) plays the factory waves built into the firmware: every bank
  starts out as the factory bank.
- Wave uploads (editor / `laniakea waves upload`, protocol MAGW) are saved to the bank
  currently loaded on the module; "restore factory waves" (MAGD) resets that bank.
- SPACE! no longer reduces the reverb (the SPACE-menu EFFECTS slot is the bank now).
- Factory reset: the EFFECTS slot resets to 0 (= bank 1), also when combined with `usability`.

How: the storage functions build keys with snprintf("onda_%d"); the three format loads are
redirected to a per-bank format string (stored over never-printed WiFi error names in rodata,
which snprintf can read byte-wise). The current bank lives in RTC slow memory (0x50001FC0).
"""

DESCRIPTION = "8 wavetable banks on the module; SPACE menu -> EFFECTS selects the bank"
OPTIONS = {"banks": (8, "number of banks (2..8)")}
TARGETS = ["3.6"]
ORDER = 5            # before usability, which must keep the EFFECTS slot's reset default at 0

STATE = 0x50001FC0   # [0] bank currently loaded in RAM (0-based)


def apply(fw, banks):
    s = fw.sym
    if not 2 <= banks <= 8:
        raise ValueError("banks must be 2..8")

    # 1) per-bank key format strings in unused, byte-readable rodata
    addr, size, orig = s["unused_rodata"]
    if fw.read(addr, len(orig)) != orig:
        raise ValueError("unexpected rodata at the key-name area")
    names = b"".join(f"ond{chr(ord('a') + i)}_%d".encode() + b"\0" for i in range(1, banks))
    if len(names) > size:
        raise ValueError("too many banks for the key-name area")
    fw.write(addr, names)
    ptrs = [s["wave_key_fmt"]] + [addr + 8 * (i - 1) for i in range(1, banks)]
    ptr_table = fw.add_code(name="bank_key_ptrs", body="    .word " + ",".join(f"{p:#x}" for p in ptrs) + "\n")

    # 2) the three snprintf format loads: reg = ptrs[current bank]  (a8 is free at all sites)
    for site, reg in s["wave_key_loads"]:
        insn = fw.disasm(site, 3)[0][2]
        if not insn.startswith(f"l32r\t{reg},"):
            raise ValueError(f"unexpected instruction at {site:#x}: {insn}")
        fw.hook(site, expect=fw.read(site, 3), name="bank_key", literals={"state": STATE, "ptrs": ptr_table},
                body=f"""
    l32r    a8, lit_state
    l32i    a8, a8, 0               /* current bank */
    bltui   a8, {banks}, 1f
    movi    a8, 0                   /* out of range (e.g. garbage before boot init) -> bank 1 */
1:
    l32r    {reg}, lit_ptrs
    addx4   {reg}, a8, {reg}
    l32i    {reg}, {reg}, 0         /* "onda_%d" / "ondb_%d" / ... */
""")

    # 3) bank_sync(): bank = int(SPACE-menu EFFECTS * banks); if changed -> reload the 8 rows
    sync = fw.add_code(name="bank_sync", literals={
        "amounts": s["space_amounts"], "n": float(banks), "state": STATE, "loader": s["wave_loader"]}, body=f"""
    entry   a1, 32
    l32r    a8, lit_amounts
    lsi     f0, a8, 20              /* val_6 = SPACE-menu EFFECTS */
    l32r    a9, lit_n
    wfr     f1, a9
    mul.s   f0, f0, f1
    trunc.s a9, f0, 0
    movi    a10, {banks - 1}
    min     a9, a9, a10
    movi    a10, 0
    max     a9, a9, a10
    l32r    a8, lit_state
    l32i    a10, a8, 0
    beq     a9, a10, 1f
    s32i    a9, a8, 0
    l32r    a8, lit_loader
    callx8  a8                      /* firmware loader: rows from NVS, missing rows = factory */
1:
    retw
""")

    # 4) boot: the first wave load (before settings exist) is always bank 1
    boot = fw.add_code(name="bank_boot", literals={"state": STATE, "loader": s["wave_loader"]}, body="""
    entry   a1, 32
    l32r    a8, lit_state
    movi    a9, 0
    s32i    a9, a8, 0
    l32r    a8, lit_loader
    callx8  a8
    retw
""")
    _redirect_call(fw, s["wave_boot_load_call"], s["wave_loader"], boot)

    # 5) after loading (boot) / saving (SPACE-menu exit) the SPACE amounts: sync the bank
    def wrapper(fn, name):
        return fw.add_code(name=name, literals={"fn": fn, "sync": sync}, body="""
    entry   a1, 32
    l32r    a8, lit_fn
    callx8  a8                      /* original function */
    mov     a6, a10                 /* keep its return value */
    l32r    a8, lit_sync
    callx8  a8
    mov     a2, a6
    retw
""")
    w_load = wrapper(s["space_load"], "space_load_sync")
    for site in s["space_load_calls"]:
        _redirect_call(fw, site, s["space_load"], w_load)
    w_save = wrapper(s["space_save"], "space_save_sync")
    for site in s["space_save_calls"]:
        _redirect_call(fw, site, s["space_save"], w_save)

    # 6) SPACE! no longer reduces EFFECTS (its SPACE slot is the bank): drop the msub
    msub = s["effects_space_msub"]
    if not fw.disasm(msub, 3)[0][2].startswith("msub.s\tf1, f13, f8"):
        raise ValueError("unexpected code at the EFFECTS SPACE scaling")
    fw.nop(msub, expect=fw.read(msub, 3))

    # 7) factory-reset default of the EFFECTS slot = 0 (bank 1)
    if "usability" in fw.meta.get("patches", []):
        fw.meta.setdefault("space_zero_slots", set()).add(20)       # usability writes the defaults
    else:
        start, end = s["space_default_stores"]
        fw.hook(start, expect=fw.read(start, end - start), resume=end, name="bank_defaults", body="""
    s32i    a8, a2, 0
    s32i    a8, a2, 4
    s32i    a8, a2, 8
    s32i    a8, a2, 12
    s32i    a8, a2, 16
    movi    a9, 0
    s32i    a9, a2, 20              /* EFFECTS slot = bank 1 */
    s32i    a8, a2, 24
""")
    fw.tag(f"banks{banks}")


def _redirect_call(fw, site, expected_target, new_target):
    insn = fw.disasm(site, 3)[0][2]
    if not (insn.startswith("call8") and f"{expected_target:#x}"[2:] in insn):
        raise ValueError(f"unexpected instruction at {site:#x}: {insn}")
    code, _ = fw.asm("    call8   __t\n", site, {"__t": new_target})
    fw.write(site, code, expect=fw.read(site, 3))
