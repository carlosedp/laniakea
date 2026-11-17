"""Diagnostic: stop all LED ring updates (the ring freezes after this patch takes effect).

Purpose: test whether the v3.4+ menu "clacking" is interference from LED refreshes.
In a menu the value display (FUN_400e0d44) redraws the WS2812 ring every 8 ms; normal
mode doesn't. If the clacking disappears with this build, the LED activity is the cause.

How: led_strip_refresh's wrapper (0x400e58e0) returns ESP_OK right after `entry`,
so pixel colours are still computed but never transmitted over RMT.
The ring stays dark/frozen (you lose visual feedback, including menu indication).
"""

DESCRIPTION = "Diagnostic: freeze the LED ring (no RMT refreshes)"
OPTIONS = {}
TARGETS = ["3.6"]

REFRESH_WRAPPER_BODY = 0x400E58E3   # right after `entry a1, 48` of led_strip_refresh wrapper


def apply(fw):
    if not fw.disasm(0x400E58E0, 3)[0][2].startswith("entry"):
        raise ValueError("unexpected code at led_strip_refresh wrapper")
    fw.replace(REFRESH_WRAPPER_BODY, "    movi.n  a2, 0\n    retw.n\n", expect=fw.read(REFRESH_WRAPPER_BODY, 4))
    fw.tag("noled")
