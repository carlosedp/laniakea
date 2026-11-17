# Magerit Laniakea: open toolkit

Unofficial tools for the Magerit **Laniakea** eurorack module (ESP32):

- firmware backup, flash and restore
- a wavetable editor and AKWF bank building
- a patch framework that adds features to the **official** firmware without touching its sound engine

> This repository contains **no Magerit firmware, manuals or code**. Official firmware is
> downloaded from Magerit's public GitHub when you build. It is SHA-256 checked against their
> manifest, and patched locally on your machine.
>
> **Power:** the module must be powered from the rack. USB alone only powers the
> USB-serial chip, so the ESP32 stays off (no LEDs, esptool can't connect).
> Connect USB, then switch the rack on.

## Quick start (fresh clone, Windows)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1      # 1. Python venv with esptool, pyserial, numpy
.venv\Scripts\python.exe scripts\install_re_tools.py --only xtensa
                                                               # 2. Xtensa assembler, needed to build patches (~240 MB)
.\laniakea backup                                               # 3. FULL flash dump incl. your calibration (keep it!)
.venv\Scripts\python.exe tools\patcher.py build recommended     # 4. download official v3.6 + apply patches
.\laniakea flash "firmware\custom\laniakea_v3.6+Y-effects+leddedupe.bin"   # 5. flash it (calibration is kept)
```

`recommended` = **EFFECTS CV jack → wavetable Y (row)** plus the **fix for the v3.4+ menu
crackle**. To undo: `.\laniakea flash v3.6` (official), or `.\laniakea restore <backup> --yes`.

## Everyday use

`laniakea.cmd` runs `tools\laniakea.py` with the local venv:

```powershell
.\laniakea ports                 # find the module (CH340)
.\laniakea info                  # chip, flash, eFuses (read-only)
.\laniakea backup                # full 4 MB dump -> firmware\backup\  (do this before flashing anything)
.\laniakea settings              # saved ORBITS/SPACE settings + calibration (read-only; or: settings <dump.bin>)
.\laniakea fetch [--manuals]     # all official firmware versions (+ Magerit's PDF manuals)
.\laniakea flash v3.6            # official firmware, downloaded if needed (keeps calibration/NVS)
.\laniakea flash <file.bin>      # a patched build
.\laniakea restore <dump> --yes  # put an exact flash dump back
.\laniakea editor                # wavetable editor at http://127.0.0.1:8765 (Chrome/Edge)
.\laniakea waves upload <bank.wav>   |   .\laniakea waves default
.\laniakea akwf fetch fmsynth eorgan   # AKWF single cycles (CC0) -> wavetables\akwf\
.\laniakea bank wavetables\akwf\AKWF_fmsynth -o wavetables\banks\fm.wav
.\laniakea monitor [--reset]     # serial console
```

## Firmware patches

Each patch is a small Python file in `patches/`. Combine them freely:

```powershell
$P = ".venv\Scripts\python.exe tools\patcher.py"
& $P list
& $P build recommended                                # cv_to_y:source=effects + led_dedupe
& $P build cv_to_y:source=effects chords:set=pro led_dedupe
& $P build cv_to_y:source=shape,gain=-0.78            # SHAPE CV scans rows (inverted)
& $P build chords:set=my_chords.txt                   # your own 16 chords
```

| Patch | What it does |
| --- | --- |
| `cv_to_y` | route a CV jack (`source=effects/space/orbits/...`) to the wavetable Y axis |
| `led_dedupe` | **fix**: refresh the LED ring only when it changes (removes the v3.4+ menu crackle) |
| `chords` | replace the 16 ORBITS-menu chords (Laniakea Pro set, or your own file) |
| `quiet` | silence serial logging |
| `diag_guards`, `diag_noled` | diagnostics used to find the crackle (see RE notes) |
| `_template` | starting point for your own patch |

Output goes to `firmware\custom\`. How patches work and how to write one:
[docs/PATCHING.md](docs/PATCHING.md). Patching needs only the Xtensa toolchain; Ghidra is optional.

## Docs

- [docs/MANUAL.md](docs/MANUAL.md): how the module really works (from the firmware): init patch, troubleshooting, all ORBITS/SPACE functions, additive oscillator and resonator
- [docs/PATCHING.md](docs/PATCHING.md): how patches work, how to write one
- [docs/PRO-FEATURES.md](docs/PRO-FEATURES.md): which Laniakea Pro features can be ported
- [docs/WAVETABLES.md](docs/WAVETABLES.md): formats, AKWF, upload protocol
- [docs/RE-NOTES.md](docs/RE-NOTES.md): addresses, memory map, code map, v3.4 crackle investigation

## Not in this repository (regenerate locally)

| What | How to get it |
| --- | --- |
| Official firmware (`firmware/official/`) | `.\laniakea fetch`, or automatically on `patcher.py build` / `flash vX.Y` |
| Patched builds (`firmware/custom/`) | `tools\patcher.py build …` |
| Your flash dumps (`firmware/backup/`) | `.\laniakea backup` |
| Magerit manuals (`docs/manuals/`) | `.\laniakea fetch --manuals` |
| Ghidra project, decompiled code (`re/ghidra/`) | `scripts\install_re_tools.py` then `scripts\ghidra_analyze.ps1 -Version v3.6` |
| AKWF waves, built banks (`wavetables/`) | `.\laniakea akwf fetch …`, `.\laniakea bank …` |
| Toolchains (`.venv`, `tools/jdk`, `tools/ghidra`, `tools/xtensa-esp-elf`) | `scripts\setup.ps1`, `scripts\install_re_tools.py` |

## Layout

| Path | |
| --- | --- |
| `tools/laniakea.py` | CLI: ports, info, backup, settings, fetch, flash, restore, waves, akwf, bank, monitor, editor |
| `tools/patcher.py`, `patchlib.py`, `symbols.py` | patch CLI, patch API (hooks, code cave, assembler), version-specific addresses |
| `tools/espimage.py`, `espinfo.py`, `img2elf.py`, `nvs.py` | ESP image parsing / checksums, ELF for Ghidra, NVS settings reader |
| `patches/` | one file per patch |
| `editor/` | wavetable editor (static web app, Web Serial upload) |
| `re/` | Ghidra scripts, version-diff helpers, ESP32 ROM symbols (Espressif, Apache-2.0) |
| `scripts/` | setup, RE-tool installer, Ghidra headless/GUI launchers |
| `tests/` | `node tests/editor_dsp.test.mjs` |

## Legal

Unofficial and not affiliated with Magerit. Flashing modified firmware may void your
warranty. Magerit's firmware is their copyright: patched images are built locally for your own
module and must not be redistributed. Share patch files instead. AKWF waveforms are CC0.
