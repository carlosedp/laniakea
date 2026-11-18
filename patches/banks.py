"""Multiple wavetable banks stored on the module, selected from the SPACE menu.

  SPACE menu -> EFFECTS knob : bank (8 zones = banks 1..8, fully CCW = bank 1).
  The bank is loaded when you LEAVE the SPACE menu, and restored at power-up.

- Bank 1 is the stock storage (NVS keys onda_0..7), so existing uploads stay as they are.
  Banks 2..8 use keys ondb_*..ondh_*.
- An empty bank (or row) plays the factory waves built into the firmware: every bank
  starts out as the factory bank.
- Wave uploads (editor / `laniakea waves upload`, protocol MAGW) are saved to the bank
  currently loaded on the module; "restore factory waves" (MAGD) resets that bank.
- Protocol: "MAG1".."MAG8" selects a bank, "MAGB" asks which bank is playing, "MAGR" reads
  the playing bank's waves back (see docs/WAVETABLES.md).
- SPACE! no longer reduces the reverb (the SPACE-menu EFFECTS slot is the bank now).
- Factory reset: the EFFECTS slot resets to 0 (= bank 1), also when combined with `usability`.

How: the storage functions build keys with snprintf("onda_%d"); the three format loads are
redirected to a per-bank format string (stored over never-printed WiFi error names in rodata,
which snprintf can read byte-wise). The current bank lives in RTC slow memory (0x50001FC0).
"""

DESCRIPTION = "8 wavetable banks on the module; SPACE menu -> EFFECTS selects the bank"
OPTIONS = {"banks": (8, "number of banks (2..8)")}
TARGETS = ["3.6", "3.7"]
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
    # 8) LED ring: in the SPACE menu, turning EFFECTS puts the dot on LED <bank> (bank 1 = LED 1)
    #    instead of the knob position (stock: 1 + value*6, i.e. LEDs 2..8 only)
    fw.hook(s["led_value_store"], expect=fw.read(s["led_value_store"], 3), name="bank_led", literals={
        "menu": s["menu_state"], "amounts": s["space_amounts"], "n": float(banks), "half": 0.5}, body=f"""
    l32r    a8, lit_menu
    l32i    a8, a8, 0
    bnei    a8, 1, 1f               /* only in the SPACE menu */
    movi    a8, {s["led_knob_id_effects"]}
    bne     a3, a8, 1f              /* only for the EFFECTS knob */
    l32r    a8, lit_amounts
    lsi     f2, a8, 20              /* the value the bank will be loaded from */
    l32r    a8, lit_n
    wfr     f3, a8
    mul.s   f2, f2, f3
    trunc.s a8, f2, 0
    movi    a9, {banks - 1}
    min     a8, a8, a9
    movi    a9, 0
    max     a8, a8, a9
    float.s f1, a8, 0
    l32r    a8, lit_half
    wfr     f3, a8
    add.s   f1, f1, f3              /* dot target = bank + 0.5 -> LED <bank> */
1:
    {{orig}}                          /* store the dot target */
""")

    # 9) protocol: "MAG1".."MAG8" selects the bank remotely (saved + loaded), answered with ACK
    select = fw.add_code(name="bank_select", literals={
        "amounts": s["space_amounts"], "invn": 1.0 / banks, "half": 0.5,
        "save": s["space_save"], "sync": sync, "uartw": s["uart_write_bytes"]}, body="""
    entry   a1, 48
    float.s f0, a2, 0               /* idx (0-based) */
    l32r    a8, lit_half
    wfr     f1, a8
    add.s   f0, f0, f1
    l32r    a8, lit_invn
    wfr     f1, a8
    mul.s   f0, f0, f1              /* centre of the bank's zone */
    l32r    a8, lit_amounts
    ssi     f0, a8, 20              /* SPACE-menu EFFECTS = bank */
    l32r    a8, lit_save
    callx8  a8                      /* persist SPACE amounts (also restored at boot) */
    l32r    a8, lit_sync
    callx8  a8                      /* load the bank */
    addi    a11, a1, 32
    movi    a8, 6
    s8i     a8, a11, 0
    movi    a10, 0
    movi    a12, 1
    l32r    a8, lit_uartw
    callx8  a8                      /* ACK */
    retw
""")
    # 9b) "MAGB" -> replies 'B', '1'..'8', ACK : the bank currently loaded (lets tools follow the module)
    query = fw.add_code(name="bank_query", literals={"state": STATE, "uartw": s["uart_write_bytes"]}, body=f"""
    entry   a1, 48
    l32r    a8, lit_state
    l32i    a9, a8, 0
    bltui   a9, {banks}, 1f
    movi    a9, 0
1:
    addi    a9, a9, 49              /* '1' + bank */
    addi    a11, a1, 32
    movi    a8, 66                  /* 'B' */
    s8i     a8, a11, 0
    s8i     a9, a11, 1
    movi    a8, 6
    s8i     a8, a11, 2              /* ACK */
    movi    a10, 0
    movi    a12, 3
    l32r    a8, lit_uartw
    callx8  a8
    retw
""")
    # 9c) "MAGR" -> replies "WAVS" + the playing wavetable (int16[64][128] little-endian, 16 KiB) + ACK
    dump = fw.add_code(name="bank_dump", literals={
        "magic": int.from_bytes(b"WAVS", "little"), "ram": s["wavetable_ram"], "size": 64 * 128 * 2,
        "uartw": s["uart_write_bytes"]}, body="""
    entry   a1, 48
    addi    a11, a1, 32
    l32r    a8, lit_magic
    s32i    a8, a11, 0
    movi    a10, 0
    movi    a12, 4
    l32r    a8, lit_uartw
    callx8  a8                      /* "WAVS" */
    movi    a10, 0
    l32r    a11, lit_ram
    l32r    a12, lit_size
    l32r    a8, lit_uartw
    callx8  a8                      /* the waves, straight from RAM */
    addi    a11, a1, 32
    movi    a8, 6
    s8i     a8, a11, 0
    movi    a10, 0
    movi    a12, 1
    l32r    a8, lit_uartw
    callx8  a8                      /* ACK */
    retw
""")
    site = s["uart_cmd_d_check"]
    if not fw.disasm(site, 3)[0][2].startswith("movi\ta8, 68"):
        raise ValueError("unexpected code at the MAG command dispatch")
    fw.hook(site, expect=fw.read(site, 3), name="bank_cmd", literals={"select": select, "query": query, "dump": dump},
            defs={"__done": s["uart_cmd_done"]}, body=f"""
    addi    a8, a4, -49             /* a4 = 4th char after "MAG"; '1' -> 0 */
    bgeui   a8, {banks}, 1f         /* not a bank digit */
    mov     a10, a8
    l32r    a8, lit_select
    callx8  a8
    j       __done                  /* same tail as the 'D' command */
1:
    movi    a8, 66                  /* 'B': which bank? */
    bne     a4, a8, 2f
    l32r    a8, lit_query
    callx8  a8
    j       __done
2:
    movi    a8, 82                  /* 'R': read the waves */
    bne     a4, a8, 3f
    l32r    a8, lit_dump
    callx8  a8
    j       __done
3:
    {{orig}}                          /* movi a8, 'D' : original 'D' check */
""")

    # 10) MAGD: reload the (now empty) bank right away, so factory waves play without a reboot
    w_erase = fw.add_code(name="bank_erase_reload", literals={"erase": s["wave_erase"], "loader": s["wave_loader"]},
                          body="""
    entry   a1, 32
    l32r    a8, lit_erase
    callx8  a8
    l32r    a8, lit_loader
    callx8  a8
    retw
""")
    _redirect_call(fw, s["uart_magd_erase_call"], s["wave_erase"], w_erase)
    fw.tag(f"banks{banks}")


def _redirect_call(fw, site, expected_target, new_target):
    insn = fw.disasm(site, 3)[0][2]
    if not (insn.startswith("call8") and f"{expected_target:#x}"[2:] in insn):
        raise ValueError(f"unexpected instruction at {site:#x}: {insn}")
    code, _ = fw.asm("    call8   __t\n", site, {"__t": new_target})
    fw.write(site, code, expect=fw.read(site, 3))
