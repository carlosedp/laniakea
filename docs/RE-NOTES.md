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

## Reference material (not in git)

Magerit's web-updater code, which documents the flashing and wave-upload protocols, can be
re-downloaded for study into `re/webupdater/` (git-ignored):
`https://magerit.es/modules/mageritdownloads/views/js/{downloads,dl-connect,dl-flasher-esp,dl-audio-waves,dl-midi}.js`.
The Laniakea Pro desktop app is at `https://github.com/mageritsynth/laniakea-pro-downloads/releases`.
