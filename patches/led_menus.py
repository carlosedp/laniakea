"""Clearer LED ring in the SPACE and ORBITS menus.

Stock: in both menus, turning a knob shows one dim dot in the knob's colour; nothing tells the
two menus apart, and the bank selector, bow/pluck switch and stepped values look the same.

With this patch (only while a menu is open; the normal display is untouched):
- Menu tint: unlit LEDs glow faintly, blue in the SPACE menu, amber in the ORBITS menu.
- SPACE menu, macro amounts (FREQ, ORBITS, COLOR, SHAPE, EFFECTS, CLUSTER): a filled bar in
  the knob's colour, LED 1 .. LED 8 = 0 .. 100 %.
- SPACE menu, EFFECTS with the `banks` patch: bank selector, all LEDs dim white, the selected
  bank's LED (LED 1 = bank 1) bright white.
- ORBITS menu, EFFECTS (string mode): LEDs 1-4 = bow, LEDs 5-8 = pluck.
- Step cues: one LED (`flash_led`, default LED 5 = top) flashes white briefly when a stepped
  value changes: the quantizer scale (SPACE-menu FREQ) and root (SPACE-menu SPACE!), and the
  chord (ORBITS-menu CLUSTER, 16 chords). The rest of the ring keeps showing the dot.
- Other knobs: the stock dot on the menu tint.

How: the menu value display (FUN_400e0d44 in v3.6) redraws the ring every 8 ms. A hook just
before its `led_strip_refresh` call redraws the pixels. Knobs are recognised by the colour code
the LED task stores (+0x58 of the display object); the ORBITS-menu EFFECTS codes are nudged by
one hue step (192 -> 193, 230 -> 231, invisible) so they don't collide with ORBITS-menu FREQ.
Step-cue state lives in RTC slow memory (0x50001FA0).
"""
import colorsys
import struct

DESCRIPTION = "LED ring: menu tint (SPACE blue / ORBITS amber), bars for amounts, bank / bow-pluck cues, scale/root/chord step cue"
OPTIONS = {
    "tint": (6, "brightness of the menu tint on unlit LEDs (0-255, 0 = off)"),
    "bright": (50, "brightness of bars / the bank LED (stock dot is ~50)"),
    "flash": (70, "brightness of the step-cue LED (scale / root / chord change; 0 = off)"),
    "flash_ms": (150, "length of the step cue in ms"),
    "flash_led": (5, "which LED flashes for a step cue (1-8; 5 = top of the ring)"),
}
TARGETS = ["3.6", "3.7"]
RANGES = {"tint": (0, 255), "bright": (0, 255), "flash": (0, 255), "flash_ms": (10, 2000), "flash_led": (1, 8)}   # web patcher UI limits (apply() still validates)
ORDER = 60           # after banks / quantizer, whose settings it reads from fw.meta

STATE = 0x50001FA0   # [0..8] last step per watch slot (-1 = not seen), [12] cue end (us), [16] magic
DOT, BAR, BANK, SWITCH, ROWS = 0, 1, 2, 3, 4
SPACE_MENU, ORBITS_MENU = 1, 2

# knob colour codes (hue 0..255) the LED task uses, per menu (RE: docs/RE-NOTES.md)
SPACE_HUES = {"freq": 0x4A, "orbits": 0xA0, "color": 0x74, "shape": 0xAE, "space": 0x80,
              "effects": 0xC0, "cluster": 0x60}
BOW_HUE, PLUCK_HUE = 0xC1, 0xE7   # after nudging the stock 0xC0 / 0xE6
ORBITS_CLUSTER_HUE = 0x34
ORBITS_SHAPE_HUE = 0x56          # ORBITS-menu SHAPE = wavetable row (Y) / additive
ADDITIVE_FROM = 0.95             # the mixer switches to the additive oscillator at Y >= 0.95


def rgb(r, g, b):
    return (int(r) << 16) | (int(g) << 8) | int(b)


def float_bits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def hue_rgb(hue, v):
    r, g, b = colorsys.hsv_to_rgb(hue / 256.0, 1.0, 1.0)
    return rgb(round(r * v), round(g * v), round(b * v))


def apply(fw, tint, bright, flash, flash_ms, flash_led):
    for name, v in (("tint", tint), ("bright", bright), ("flash", flash)):
        if not 0 <= v <= 255:
            raise ValueError(f"{name} must be 0..255")
    if not 1 <= flash_led <= 8:
        raise ValueError("flash_led must be 1..8")
    s = fw.sym

    # 1) unique colour codes for ORBITS-menu EFFECTS (bow / pluck)
    for key, old, new in (("led_hue_orbits_bow", 192, BOW_HUE), ("led_hue_orbits_pluck", 230, PLUCK_HUE)):
        a = s[key]
        if fw.disasm(a, 3)[0][2] != f"movi\ta3, {old}":
            raise ValueError(f"unexpected code at {key} {a:#x}")
        fw.replace(a, f"    movi    a3, {new}\n", expect=fw.read(a, 3))

    # 2) per-knob table (8 words): key = menu << 8 | hue, mode, colour, aux, and an optional step
    #    watch (value address, number of steps, state slot): a step change flashes one LED
    banks = fw.meta.get("banks")
    zones = fw.meta.get("quant_zones")
    amounts = s["space_amounts"]
    rows = []
    for knob, hue in SPACE_HUES.items():
        mode, colour, aux, watch = BAR, hue_rgb(hue, bright), 0, (0, 0, 0)
        if knob == "space":
            mode = DOT                                   # SPACE! amount is unused (quantizer: root)
            if zones:
                watch = (amounts + 16, 12, 1)            # quantizer root, 12 notes
        elif knob == "effects" and banks:
            mode, colour, aux = BANK, rgb(bright, bright, bright), banks
        elif knob == "freq" and zones:
            mode, watch = DOT, (amounts + 0, zones, 0)    # quantizer scale zone
        if mode != DOT or watch[0]:
            rows.append((SPACE_MENU << 8 | hue, mode, colour, aux, *watch))
    rows.append((ORBITS_MENU << 8 | BOW_HUE, SWITCH, hue_rgb(192, bright), 0, 0, 0, 0))
    rows.append((ORBITS_MENU << 8 | PLUCK_HUE, SWITCH, hue_rgb(230, bright), 1, 0, 0, 0))
    rows.append((ORBITS_MENU << 8 | ORBITS_CLUSTER_HUE, DOT, 0, 0, s["secondary"]["acorde"], 16, 2))  # chord
    # ORBITS-menu SHAPE: one LED per wavetable row (row = Y * k, as the renderer), whole ring gold
    # once Y reaches the additive oscillator. aux = k (float bits); the 8th word = tabla address.
    k = float(fw.meta.get("y_scale", 9.0))
    rows.append((ORBITS_MENU << 8 | ORBITS_SHAPE_HUE, ROWS, hue_rgb(ORBITS_SHAPE_HUE, bright),
                 float_bits(k), 0, 0, 0, s["secondary"]["tabla"]))
    table = fw.add_code(name="led_menus_table", body="".join(
        f"    .word {r[0]:#x}, {r[1]}, {r[2]:#x}, {r[3]}, {r[4]:#x}, {r[5]}, {r[6] * 4}, {(r[7] if len(r) > 7 else 0):#x}\n"
        for r in rows))

    t = max(0, min(255, tint))
    lits = {
        "menu": s["menu_state"], "table": table, "amounts": amounts,
        "tint_space": rgb(0, 0, t), "tint_orbits": rgb(t, round(t * 0.45), 0),
        "bank_bg": rgb(t, t, t), "state": STATE, "magic": 0x1ED5CA1F,
        "flash_us": int(flash_ms * 1000) if flash else 0, "flash_rgb": rgb(flash, flash, flash),
        "timer": s["esp_timer_get_time"], "setpix": s["led_set_pixel_fn"],
        "one": 1.0, "k": 8.0 / 6.0, "half": 0.5,
        "add_from": ADDITIVE_FROM, "add_rgb": rgb(bright, round(bright * 0.6), round(bright * 0.1)),
    }
    overlay = fw.add_code(name="led_menus", literals=lits, body=f"""
    entry   a1, 96
    l32r    a8, lit_menu
    l32i    a3, a8, 0
    l32r    a4, lit_tint_space
    beqi    a3, 1, .Lmenu
    l32r    a4, lit_tint_orbits
    beqi    a3, 2, .Lmenu
    retw                            /* not in a menu: stock display */
.Lmenu:
    l32i    a5, a2, 88              /* knob colour code */
    extui   a5, a5, 0, 16
    slli    a3, a3, 8
    or      a5, a5, a3              /* key = menu << 8 | hue */
    l32r    a6, lit_table
    movi    a7, {len(rows)}
.Lfind:
    l32i    a8, a6, 0
    beq     a8, a5, .Lfound
    addi    a6, a6, 32
    addi    a7, a7, -1
    bnez    a7, .Lfind
    movi    a8, 0
    s32i    a8, a1, 72              /* no table entry */
    j       .Ldot
.Lfound:
    s32i    a6, a1, 72              /* entry, for the step watch */
    l32i    a5, a6, 4               /* mode */
    l32i    a7, a6, 12              /* aux */
    l32i    a6, a6, 8               /* colour */
    bnei    a5, {BAR}, 1f           /* (short branches only reach +-128 bytes) */
    j       .Lbar
1:  bnei    a5, {BANK}, 2f
    j       .Lbank
2:  bnei    a5, {SWITCH}, 3f
    j       .Lswitch
3:  bnei    a5, {ROWS}, .Ldot
    j       .Lrows

.Ldot:                              /* tint everywhere except the stock dot's two LEDs */
    addi    a8, a1, 32
    movi    a9, 8
.Ldot1:
    s32i    a4, a8, 0
    addi    a8, a8, 4
    addi    a9, a9, -1
    bnez    a9, .Ldot1
    lsi     f0, a2, 132             /* dot position */
    trunc.s a8, f0, 0
    float.s f1, a8, 0
    sub.s   f1, f0, f1              /* fraction */
    movi    a9, -1                  /* -1 = leave this pixel as drawn */
    extui   a10, a8, 0, 3
    addx4   a10, a10, a1
    s32i    a9, a10, 32
    movi    a10, 0
    wfr     f2, a10
    olt.s   b0, f2, f1
    bt      b0, 4f
    j       .Lwatch
4:  addi    a10, a8, 1
    extui   a10, a10, 0, 3
    addx4   a10, a10, a1
    s32i    a9, a10, 32
    j       .Lwatch

.Lbar:                              /* n = round((target - 1) / 6 * 8) LEDs in the knob colour */
    lsi     f0, a2, 136
    l32r    a8, lit_one
    wfr     f1, a8
    sub.s   f0, f0, f1
    l32r    a8, lit_k
    wfr     f1, a8
    mul.s   f0, f0, f1
    l32r    a8, lit_half
    wfr     f1, a8
    add.s   f0, f0, f1
    trunc.s a8, f0, 0
    movi    a9, 8
    min     a8, a8, a9
    movi    a9, 0
    max     a8, a8, a9
    addi    a9, a1, 32
    movi    a10, 0
.Lbar1:
    mov     a11, a4
    bge     a10, a8, .Lbar2
    mov     a11, a6
.Lbar2:
    s32i    a11, a9, 0
    addi    a9, a9, 4
    addi    a10, a10, 1
    bnei    a10, 8, .Lbar1
    j       .Lwatch

.Lbank:                             /* bank = clamp(int(EFFECTS amount * banks)), as the banks patch */
    l32r    a8, lit_amounts
    lsi     f0, a8, 20
    float.s f1, a7, 0
    mul.s   f0, f0, f1
    trunc.s a8, f0, 0
    addi    a9, a7, -1
    min     a8, a8, a9
    movi    a9, 0
    max     a8, a8, a9
    l32r    a9, lit_bank_bg
    addi    a10, a1, 32
    movi    a11, 8
.Lbank1:
    s32i    a9, a10, 0
    addi    a10, a10, 4
    addi    a11, a11, -1
    bnez    a11, .Lbank1
    addx4   a10, a8, a1
    s32i    a6, a10, 32
    j       .Lwatch

.Lswitch:                           /* LEDs 1-4 (aux 0, bow) or 5-8 (aux 1, pluck) */
    addi    a9, a1, 32
    movi    a10, 0
.Lsw1:
    mov     a11, a4
    srli    a12, a10, 2
    bne     a12, a7, .Lsw2
    mov     a11, a6
.Lsw2:
    s32i    a11, a9, 0
    addi    a9, a9, 4
    addi    a10, a10, 1
    bnei    a10, 8, .Lsw1
    j       .Lwatch

.Lrows:                             /* wavetable row as one LED; additive = whole ring gold */
    l32i    a8, a1, 72
    l32i    a8, a8, 28              /* &tabla (ORBITS-menu SHAPE value) */
    lsi     f0, a8, 0
    l32r    a8, lit_add_from
    wfr     f1, a8
    olt.s   b0, f0, f1
    bt      b0, .Lrow
    l32r    a9, lit_add_rgb
    addi    a10, a1, 32
    movi    a11, 8
.Lrows1:
    s32i    a9, a10, 0
    addi    a10, a10, 4
    addi    a11, a11, -1
    bnez    a11, .Lrows1
    j       .Lwatch
.Lrow:
    wfr     f1, a7                  /* k: row = Y * k */
    mul.s   f0, f0, f1
    trunc.s a8, f0, 0
    movi    a9, 7
    min     a8, a8, a9
    movi    a9, 0
    max     a8, a8, a9
    addi    a10, a1, 32
    movi    a11, 8
.Lrow1:
    s32i    a4, a10, 0
    addi    a10, a10, 4
    addi    a11, a11, -1
    bnez    a11, .Lrow1
    addx4   a10, a8, a1
    s32i    a6, a10, 32
    j       .Lwatch

.Lwatch:                            /* step cue: flash one LED when the watched step changes */
    l32i    a5, a1, 72
    beqz    a5, .Lout
    l32i    a8, a5, 16              /* watched value (float 0..1) */
    beqz    a8, .Lout
    lsi     f0, a8, 0
    l32i    a7, a5, 20              /* steps */
    float.s f1, a7, 0
    mul.s   f0, f0, f1
    trunc.s a3, f0, 0
    addi    a9, a7, -1
    min     a3, a3, a9
    movi    a9, 0
    max     a3, a3, a9              /* a3 = step */
    l32r    a8, lit_timer
    callx8  a8                      /* esp_timer_get_time: a10 = low word (us) */
    mov     a7, a10
    l32r    a8, lit_state
    l32i    a9, a8, 16
    l32r    a10, lit_magic
    beq     a9, a10, .Lw1
    s32i    a10, a8, 16             /* first use since power-up: nothing seen yet */
    movi    a9, -1
    s32i    a9, a8, 0
    s32i    a9, a8, 4
    s32i    a9, a8, 8
    s32i    a7, a8, 12
.Lw1:
    l32i    a9, a5, 24              /* slot offset */
    add     a9, a8, a9
    l32i    a10, a9, 0              /* last step */
    beq     a10, a3, .Lw2
    s32i    a3, a9, 0
    bltz    a10, .Lw2               /* first time this value is seen: no cue */
    l32r    a10, lit_flash_us
    add     a10, a7, a10
    s32i    a10, a8, 12
.Lw2:
    l32i    a9, a8, 12
    sub     a9, a7, a9              /* now - end (wraps safely) */
    bgez    a9, .Lout
    l32r    a9, lit_flash_rgb
    s32i    a9, a1, {32 + 4 * (flash_led - 1)}

.Lout:                              /* send the 8 pixels (skip -1) through led_strip_set_pixel */
    movi    a3, 0
    addi    a5, a1, 32
.Lpix:
    l32i    a8, a5, 0
    addi    a9, a8, 1
    beqz    a9, .Lskip
    extui   a12, a8, 16, 8
    extui   a13, a8, 8, 8
    extui   a14, a8, 0, 8
    l32i    a10, a2, 180            /* strip handle */
    mov     a11, a3
    l32r    a8, lit_setpix
    callx8  a8
.Lskip:
    addi    a5, a5, 4
    addi    a3, a3, 1
    bnei    a3, 8, .Lpix
    retw
""")

    # 3) call it right before the display's led_strip_refresh
    site = s["led_display_hook"]
    insns = fw.disasm(site, 6)
    if insns[0][2] != "l32i\ta10, a7, 180" or not insns[1][2].startswith("call8"):
        raise ValueError(f"unexpected code at led_display_hook {site:#x}: {insns}")
    fw.hook(site, expect=fw.read(site, 3), name="led_menus_call", literals={"fn": overlay}, body="""
    mov     a10, a7                 /* display object */
    l32r    a8, lit_fn
    callx8  a8
    {orig}
""")
    fw.tag("ledmenus")
