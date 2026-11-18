"""Fix for the v3.4+ "clacking/crackling" in menus: only refresh the LED ring when it changed.

Diagnosis (docs/RE-NOTES.md): the crackle disappears when LED refreshes are disabled
(diag_noled). In a menu the value display redraws the WS2812 ring every 8 ms with the
same data; each RMT transmission couples into the audio path.

This patch keeps a shadow copy of the 8 pixel colours:
  - led_strip_set_pixel wrapper (v3.6: 0x400e58a8): compares the new colour with the shadow;
    if different, stores it and sets a "dirty" flag. The real set_pixel is always called.
  - led_strip_refresh wrapper   (v3.6: 0x400e58e0): transmits only if dirty, then clears it.
The ring looks exactly the same, but a static display sends nothing.

State lives in RTC slow memory (0x50001F40..0x50001F67): 8 shadow words, dirty, magic.
On first use after power-up the shadow is invalidated so every pixel is sent once.
"""

DESCRIPTION = "Fix menu crackle: refresh the LED ring only when pixels change"
OPTIONS = {}
TARGETS = ["3.6", "3.7"]

BASE = 0x50001F40           # [0..28] shadow (0x00RRGGBB), [32] dirty, [36] magic


def apply(fw):
    for a in (fw.sym["led_set_pixel_fn"], fw.sym["led_refresh_fn"]):
        if not fw.disasm(a, 3)[0][2].startswith("entry"):
            raise ValueError(f"unexpected code at {a:#x}")
    SET_PIXEL_BODY = fw.sym["led_set_pixel_fn"] + 3   # after `entry a1, 48`
    REFRESH_BODY = fw.sym["led_refresh_fn"] + 3

    # --- set_pixel(strip=a2, index=a3, r=a4, g=a5, b=a6)
    fw.hook(SET_PIXEL_BODY, expect=fw.read(SET_PIXEL_BODY, 4), name="led_set_pixel",
            literals={"base": BASE, "magic": 0x1ED0DEDE}, body="""
    beqz    a2, 9f
    l32r    a8, lit_base
    l32i    a9, a8, 36
    l32r    a10, lit_magic
    beq     a9, a10, 1f
    movi    a9, -1                  /* first call since power-up: invalidate shadow */
    s32i    a9, a8, 0
    s32i    a9, a8, 4
    s32i    a9, a8, 8
    s32i    a9, a8, 12
    s32i    a9, a8, 16
    s32i    a9, a8, 20
    s32i    a9, a8, 24
    s32i    a9, a8, 28
    movi    a9, 1
    s32i    a9, a8, 32
    s32i    a10, a8, 36
1:
    movi    a9, 8
    bgeu    a3, a9, 3f              /* out-of-range index: let the driver report it */
    extui   a9, a4, 0, 8
    slli    a9, a9, 16
    extui   a10, a5, 0, 8
    slli    a10, a10, 8
    or      a9, a9, a10
    extui   a10, a6, 0, 8
    or      a9, a9, a10             /* a9 = 0x00RRGGBB */
    addx4   a10, a3, a8             /* &shadow[index] */
    l32i    a11, a10, 0
    beq     a11, a9, 2f             /* unchanged */
    s32i    a9, a10, 0
3:
    movi    a9, 1
    s32i    a9, a8, 32              /* dirty */
2:
    l32i    a8, a2, 0               /* strip->set_pixel(strip, i, r, g, b) */
    mov     a10, a2
    mov     a11, a3
    mov     a12, a4
    mov     a13, a5
    mov     a14, a6
    callx8  a8
    mov     a2, a10
    retw
9:
    movi    a2, 0x102               /* ESP_ERR_INVALID_ARG, as the original */
    retw
""")

    # --- refresh(strip=a2)
    fw.hook(REFRESH_BODY, expect=fw.read(REFRESH_BODY, 4), name="led_refresh",
            literals={"dirty": BASE + 32}, body="""
    beqz    a2, 9f
    l32r    a8, lit_dirty
    l32i    a9, a8, 0
    beqz    a9, 8f                  /* nothing changed: skip the RMT transmission */
    movi    a9, 0
    s32i    a9, a8, 0
    l32i    a8, a2, 8               /* strip->refresh(strip) */
    mov     a10, a2
    callx8  a8
    mov     a2, a10
    retw
8:
    movi    a2, 0                   /* ESP_OK */
    retw
9:
    movi    a2, 0x102
    retw
""")
    fw.tag("leddedupe")
