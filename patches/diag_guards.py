"""Diagnostic: count the engine's NaN/blow-up "guard" resets and print the counts once per second.

Background (docs/RE-NOTES.md, "v3.3 -> v3.4 changes"): v3.4 added two safety resets in the
audio engine. Each fires when a block's last sample is NaN or beyond +-1e6:
  guard 1 (string model): zeroes the 16 KB string delay line + its filter states
  guard 2 (resonator):    zeroes the resonator's first mode states
Each reset is an audible discontinuity, a suspect for the menu "clacking".

This patch changes nothing audible. It:
  - counts guard-1 resets (hooks the memset calls in both engine branches)
  - counts guard-2 resets (jump hooks on both reset paths)
  - once per second (every 1000 engine blocks of 48 samples) prints, via ROM ets_printf,
    re-using an existing firmware format string:

        CV99 - jack: <guard1 total> -> <guard2 total> (errores: <seconds>/24)

Read it with `laniakea monitor`. If the numbers climb while you hear the clacking,
the guards are firing.
Counters live in RTC slow memory (0x50001F00..) behind a magic word, so they start at 0.
"""

DESCRIPTION = "Diagnostic: print NaN/blow-up guard reset counts once per second"
OPTIONS = {}
TARGETS = ["3.6"]

RTC = 0x50001F00          # magic, tick, g1, g2
ETS_PRINTF = 0x40007D54   # ROM
MEMSET = 0x4000C44C       # ROM
RENDER = 0x400DE264       # oscillator render, called once per 48-sample block
FMT = 0x3F404060          # "CV%d - jack: %d -> %d (errores: %d/24)\n"

TICK_SITES = (0x400DE855, 0x400DF075)        # call8 RENDER (engine branch 0 and 1)
G1_SITES = (0x400DEDD9, 0x400DF607)          # callx8 a8 (= memset) in guard-1 reset
G2_SITES = (0x400DEF5C, 0x400DF76D)          # l32r a9, =0x3ffc2e20 at guard-2 reset start


def apply(fw):
    lits = {"magic_addr": RTC, "tick": RTC + 4, "g1": RTC + 8, "g2": RTC + 12,
            "magic": 0xC0FFEE01, "period": 1000, "fmt": FMT, "printf": ETS_PRINTF, "render": RENDER}
    tick_fn = fw.add_code(name="diag_tick", literals=lits, body="""
    entry   a1, 48
    l32r    a8, lit_magic_addr
    l32i    a9, a8, 0
    l32r    a10, lit_magic
    beq     a9, a10, 2f
    s32i    a10, a8, 0              /* first run after power-up: zero the counters */
    movi    a9, 0
    s32i    a9, a8, 4
    s32i    a9, a8, 8
    s32i    a9, a8, 12
2:
    l32r    a8, lit_tick
    l32i    a9, a8, 0
    addi    a9, a9, 1
    s32i    a9, a8, 0
    l32r    a10, lit_period
    remu    a11, a9, a10
    bnez    a11, 1f
    quou    a14, a9, a10            /* seconds */
    l32r    a8, lit_g1
    l32i    a12, a8, 0
    l32r    a8, lit_g2
    l32i    a13, a8, 0
    movi    a11, 99
    l32r    a10, lit_fmt
    l32r    a8, lit_printf
    callx8  a8
1:
    mov     a10, a2                 /* original call: render(osc, buf, n) */
    mov     a11, a3
    mov     a12, a4
    l32r    a8, lit_render
    callx8  a8
    retw
""")
    g1_fn = fw.add_code(name="diag_g1", literals={"g1": RTC + 8, "memset": MEMSET}, body="""
    entry   a1, 32
    l32r    a8, lit_g1
    l32i    a9, a8, 0
    addi    a9, a9, 1
    s32i    a9, a8, 0
    mov     a10, a2                 /* original call: memset(dst, 0, len) */
    mov     a11, a3
    mov     a12, a4
    l32r    a8, lit_memset
    callx8  a8
    mov     a2, a10
    retw
""")
    for site in TICK_SITES:
        insn = fw.disasm(site, 3)[0][2]
        if not insn.startswith("call8") or f"{RENDER:#x}"[2:] not in insn:
            raise ValueError(f"unexpected instruction at {site:#x}: {insn}")
        code, _ = fw.asm("    call8   __t\n", site, {"__t": tick_fn})
        fw.write(site, code, expect=fw.read(site, 3))
    for site in G1_SITES:
        code, _ = fw.asm("    call8   __t\n", site, {"__t": g1_fn})
        fw.write(site, code, expect="e00800")     # callx8 a8
    for site in G2_SITES:
        if "3ffc2e20" not in fw.disasm(site, 3)[0][2] and "l32r" not in fw.disasm(site, 3)[0][2]:
            raise ValueError(f"unexpected instruction at {site:#x}")
        fw.hook(site, expect=fw.read(site, 3), name="diag_g2",
                literals={"g2": RTC + 12, "res": 0x3FFC2E20}, body="""
    l32r    a9, lit_g2              /* a9/a10 are overwritten right after: free */
    l32i    a10, a9, 0
    addi    a10, a10, 1
    s32i    a10, a9, 0
    l32r    a9, lit_res             /* original: l32r a9, =0x3ffc2e20 */
""")
    fw.tag("diag")
