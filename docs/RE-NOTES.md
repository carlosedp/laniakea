# Laniakea firmware reverse-engineering notes

Firmware analysed: **Laniakea v3.6** (`firmware/official/laniakea/laniakea_v3.6.bin`,
sha256 `64f8ee24…e328`). Addresses below are for v3.6 only.

## Where the firmware comes from

The web updater at magerit.es/downloads (`re/webupdater/*.js`) downloads plain
merged images from the public GitHub repo `mageritsynth/binaries`
(`<product>/<product>_<version>.bin`, with `manifest.json` holding sha256s), then
writes them at 0x0 with esptool-js over Web Serial. `tools/laniakea.py fetch` mirrors that.

## Hardware / platform

- ESP32 (Xtensa LX6, dual core), 4 MB flash, CH340 USB-UART with DTR/RTS auto-reset.
- **USB powers only the CH340.** The ESP32 runs from the eurorack ±12 V rails; with USB alone esptool gets "No serial data received".
- ESP-IDF v6.0, C++, FreeRTOS. Project name `Magerit_LANIAKEA`.
- Audio: I2S at 48 kHz, 16-bit stereo (`tarea_motor`, `main/motor.cpp`).
- Pots: ESP32 internal ADC1/ADC2 oneshot (`main/drivers/adc_pot.cpp`), sampled from a gptimer.
- CV inputs: external **MCP ADC over SPI** (`MCP_ADC`, two SPI devices), with jack-detect/normalisation thresholds `th_%d`.
- LED ring: WS2812 over RMT (`led_strip`), 8 LEDs.
- No Secure Boot signature and no flash encryption (the updater writes plaintext), so modified images boot as long as checksum + SHA-256 are fixed (`tools/espimage.py`).

## Flash layout

| Offset | Size | |
| --- | --- | --- |
| 0x1000 | | 2nd-stage bootloader |
| 0x8000 | | partition table |
| 0x10000 | 0x1D0000 | `factory` app (single slot, no OTA) |
| 0x1E0000 | 0x220000 | `nvs`: settings, calibration, uploaded waves |

The official images end at 0x6C130, so flashing never touches NVS.

## NVS (namespace `storage`)

| Key | Meaning |
| --- | --- |
| `octava`, `lpg_color`, `decay`, `cant_esp`, `tabla`, `acorde`, `modores` | ORBITS-menu "extras" (floats 0..1) |
| `val_1..val_7` | SPACE! amounts per knob |
| `th_%d`, `off_%d`, `val_A`, `val_B` | CV jack thresholds/offsets, V/OCT scale/offset |
| `onda_%d` | uploaded wavetable, 8 slots (`onda_0..7`), one per row of 8 waves |

## Key code (v3.6)

| Address | What |
| --- | --- |
| `0x400dcfdc` | creates `tarea_motor` |
| `0x400de65c` | audio engine task loop (`motor`) |
| `0x400de264` | oscillator render → `0x400dd1fc` voice renderer (wavetable lookup) |
| `0x400e1f1c` | oscillator parameter setter (`osc+0x24` = X, `osc+0x20` = Y) |
| `0x400e2bf4` | **parameter mixing**: pot + CV + SPACE → engine params |
| `0x400e41a8` | wires the 7 pot objects to their normal / ORBITS / SPACE targets |
| `0x400e12c8` | LED ring task |
| `0x400e4404` / `0x400e44c0` | save / load ORBITS extras |
| `0x400e4ca0` | load default wavetable (`MAGD`) |
| `0x3ffc80c0` | settings struct (`+0x00` state, `+0x44` tabla, …) |
| `0x3ffc40c0` | wavetable RAM: `int16[64][128]` |

### Pot → parameter map (from `0x400e41a8` / `0x400e2bf4`)

| Pot | Normal | ORBITS menu | SPACE amount | CV global |
| --- | --- | --- | --- | --- |
| FREQ | `8114` | `8110` octave/range | `35d0` | V/OCT separate |
| CLUSTER | `80c4` | `8108` acorde (chord) | `35e8` | `3580` |
| COLOR | `80c8` | `80fc` lpg_color | `35d8` | `358c` |
| SHAPE | `80cc` (X) | `8104` **tabla (Y)** | `35dc` | `357c` |
| ORBITS | `80d0` | `80f8` decay | `35d4` | `3578` |
| SPACE! | `80d4` | `810c` cant_esp | `35e0` | `3584` |
| EFFECTS | `80d8` | `8134` modores | `35e4` | `3588` |

(all addresses `0x3ffcXXXX`)

In `0x400e2bf4`: `X = clamp(SHAPE + shapeCV)` (with SPACE scaling) but
`Y = tabla` with **no CV**, which is why the SHAPE CV only scans X.

## Patches (`patches/`, built with `tools/patcher.py`, API in `tools/patchlib.py`)

How hooks, the code cave and checksums work: [PATCHING.md](PATCHING.md).

`cv_to_y` (CV jack → wavetable Y):

- Hooks `0x400e3118` (`lsi f1, a6, 0x44`, the `tabla` load). The trampoline lives at the end of `.flash.text` (`0x400fb980`+).
- `if tabla < 0.95: Y = clamp(tabla + gain * CV[source], 0, 7/9)`, then resumes at `0x400e311b`.
- Scratch registers `a8`, `f0`, `f2`, `b0` are dead at that point (checked in the disassembly).
- `exclusive=1` swaps the jack's `add.s knob, knob, cv` for `mov.s` (see `cv_add` in `tools/symbols.py`).
- The stored `tabla` setting is never modified, so NVS and the LEDs behave as stock.

`chords`: rewrites the `float[16][8]` chord-ratio table at `0x3f40ec34`.

Patched images get the app version `3.6+<tags>`, so a flash backup shows what's installed.
All builds pass `esptool image-info`. Official v3.6 was flashed and boots on the real module;
`3.6+Y-effects` was flashed and boots cleanly on the real module (no crashes; all tasks start); audible behaviour to be confirmed by ear.

## Re-running the analysis

```powershell
powershell -ExecutionPolicy Bypass -File scripts\ghidra_analyze.ps1 -Version v3.6
# -> re\ghidra\v3.6\decompiled.c, functions.txt, string_xrefs.txt
powershell -ExecutionPolicy Bypass -File scripts\ghidra_gui.ps1   # interactive
```

## v3.3 → v3.4 changes (menu "clacking" regression)

Reported symptom: in additive mode, a clacking noise while the ORBITS menu is open;
absent in v3.3, present in v3.4–v3.6. Function-level diff (`re/fndiff.py`, `re/fnpair.py`
on the Ghidra exports of both versions) shows only two audio-relevant changes:

1. **Serial logging enabled.** v3.3 has none of the app's ESP-IDF log tags
   (`motor`, `potenciometros`, `switches`, `guardado`, `MCP_ADC`); v3.4 logs at INFO
   (`esp_log` default level `0x3ffb0054` = 3) to UART0 → CH340.
2. **DSP blow-up guards** in the engine (`motor`): if the last sample of a 48-sample
   block exceeds ±1e6, the string delay line (`0x3ffbe720`, 4096 floats) and filter states
   are zeroed; the same for the first resonator mode. Each reset is an audible discontinuity.

Ruled out: additive/wavetable threshold flapping (saved `tabla` = 1.0000 at full CW),
NVS writes (only on menu exit), CPU contention (audio = core 1, prio 15; LED/pots = core 0,
prio 2), out-of-range LED index (index is `% 8`).

Diagnostic build: `patcher.py build cv_to_y:source=effects quiet` (log level 0).
If the clacking disappears, it's UART activity coupling into the audio; if not, the
blow-up guard is the next suspect.

Results on hardware (2026-11-17):

- `laniakea monitor` during the clacking: no log output → **serial logging ruled out**.
- `diag_guards` build: counters stayed `0 -> 0` while clacking (block rate confirmed at
  1000/s) → **NaN/blow-up guards ruled out**.
- Next: `diag_noled` build (LED refreshes disabled; menu display redraws the ring every 8 ms).
- `diag_noled` build: **crackle gone** → cause = LED ring refreshes. In a menu the value
  display (`FUN_400e0d44`) rewrites the WS2812 ring every 8 ms with identical data; each RMT
  transmission couples into the audio output (worst with a bright single dot, e.g. SHAPE
  fully CW in the ORBITS menu).
- Fix candidate: `led_dedupe` patch: shadow copy of the 8 pixels in RTC slow memory
  (0x50001F40); `led_strip_refresh` only transmits when a pixel actually changed.
  Build: `patcher.py build cv_to_y:source=effects led_dedupe`.
- `led_dedupe` on hardware: **ring works normally and the crackle is gone** → fix confirmed.
  Recommended daily build: `laniakea_v3.6+Y-effects+leddedupe.bin`.

## LED ring in the menus (used by `led_menus`)

- The LED task (FUN_400e12c8) sets the display state at +0x44 of the display object
  (0x3ffc37e0 in v3.6): menus 1 and 2 → 'R' (0x52), so FUN_400e0d44 (value display) redraws
  every 8 ms. Menu 0 → 0x14 (normal display).
- Display object: +0x58 knob colour code (hue 0..255, HSV sector = hue·6/256), +0x84 animated
  dot position, +0x88 target (= 1 + pot·6, so LEDs 2..8), +0xa0 animation flag, +0xb4 strip.
  The dot is two LEDs, floor/ceil of the position, cross-faded, at 20 % brightness.
- Colour codes. SPACE menu: FREQ 0x4a, ORBITS 0xa0, COLOR 0x74, SHAPE 0xae, SPACE! 0x80,
  EFFECTS 0xc0, CLUSTER 0x60. ORBITS menu: FREQ 0xe6, ORBITS 0x44, COLOR 0x20, SHAPE 0x56,
  SPACE! 0x00, EFFECTS 0xc0 (≤ 50 %, bow) / 0xe6 (> 50 %, pluck). That last one collides with
  FREQ, so `led_menus` nudges the EFFECTS codes to 0xc1 / 0xe7.
- Pot objects (0x3ffc3600.., 0x30 each) hold pointers to the knob's normal value, its raw
  position (0x3ffc8118..8130, what the display shows), its ORBITS-menu value and its SPACE amount.
- Bow/pluck (`modores`): a pluck is struck only when the EXCITER jack is patched (jack-detect
  flag 0x3ffc3529), on a rising edge, with `modores` > 0.5. Without a cable the EXCITER level is
  forced to 0, and in pluck mode the string's continuous drive is scaled by that level.

## EXCITER, string model and jack detection (used by `strum`)

- `adc_task` (FUN_400dfcf0, priority 24) reads the CVs, runs jack detection, then calls the
  pot/menu/mixer task body (FUN_400e3800 → param_mix FUN_400e2bf4) at the end of every loop. CV
  processing and the mixer therefore never race.
- Jack detection: a pseudo-random bit is driven onto the jack normalling (GPIO 0x3ff44014/18);
  per jack a mismatch counter (EXCITER: byte 0x3ffc3528) is turned every 24 samples into the
  flag byte (+1): < 2 mismatches → 0 (no cable), ≥ 13 → 1, in between unchanged. That's the
  `CV%d - jack: a -> b` log line.
- EXCITER CV (0x3ffc3574): 0 when unpatched, else (raw − offset)·−2, clamped 0..1.
- Trigger (param_mix): gate state 0x3ffc37cc; rising when level > 0.24 and up > 0.01 since the
  last pass, re-armed below 0.12; only with the jack flag set. On the trigger the pluck flag is
  raised (if `modores` > 0.5) and the LPG engine (FUN_400e1f1c) gets state 3; no cable → state 8.
- Audio task: with the jack flag 0 the LPG parameters are held "open" (1.0 / 0.5 / 0.25); with 1
  they follow the LPG envelope.
- String model (state 0x3ffbe6e0, set by FUN_400e258c): pluck = a noise burst of +0x38 samples
  per trigger; bow = continuous thresholded noise scaled by +0x14 (8 − 6·damping). Output mix:
  `out = osc + ((body + (string − body)·S) − osc)·M`, with M = ORBITS mix (1.4·knob − 0.2) and
  S = clamp((SHAPE − 0.7)·4) (0x3ffc37c0). So the string, and bow/pluck, are only heard with
  the effective SHAPE above 0.7.
- Final pitch: settings + 0x1c (0x3ffc80dc in v3.6) = semitones / 108, after the quantizer hook.

## v3.6 → v3.7 (additive oscillator fix) and porting the patches

Magerit's v3.7 ("improved additive oscillator", 2026-11-18) fixes the additive-mode clacking
and the noise when leaving additive mode. The changes are in the voice engine (FUN_400de65c
and its helpers). The LED code is unchanged, so the fix is in the engine. Rodata grew by ~1 KB,
`.flash.text` by ~5 KB, and `.data`/`.bss` moved, so nearly every address changed. The factory
wavetable, the chord table and the `onda_%d` key stay at the same addresses.

`re/port_syms.py OLD.bin NEW.bin` ports `tools/symbols.py`. It aligns normalised instruction
streams (95 % of 67k instructions matched), maps code addresses through the alignment, and maps
data addresses through the literals that aligned `l32r`s load. Fixed by hand for v3.7:

- `space_load`, `space_save`: function entries, taken from their call sites.
- `led_refresh_fn`: the linear disassembly is out of step there.
- `y_scale_load`: the renderer function is byte-identical; found through its 9.0 literal.
- `unused_rodata`: string search.

The additive thresholds (0.94 renderer, 0.95 mixer) are unchanged, so `usability`'s Y spread
still fits.

Checks:

- Every v3.6 build is byte-identical after moving the patches' hard-coded addresses into
  `symbols.py`.
- The same patch set built on v3.6 and v3.7 gives code caves of identical size. Their 42
  differing words are all mapped literals or jumps back to the mapped hook sites.

## Reference material (not in git)

Magerit's web-updater code, which documents the flashing and wave-upload protocols, can be
re-downloaded for study into `re/webupdater/` (git-ignored):
`https://magerit.es/modules/mageritdownloads/views/js/{downloads,dl-connect,dl-flasher-esp,dl-audio-waves,dl-midi}.js`.
The Laniakea Pro desktop app is at `https://github.com/mageritsynth/laniakea-pro-downloads/releases`.
