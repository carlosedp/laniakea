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

## Quick start (fresh clone)

**Windows** (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1      # 1. Python venv with esptool, pyserial, numpy
.venv\Scripts\python.exe scripts\install_re_tools.py --only xtensa
                                                               # 2. Xtensa assembler, needed to build patches
.\laniakea backup                                               # 3. FULL flash dump incl. your calibration (keep it!)
.\laniakea patcher build recommended                          # 4. download official v3.6 + apply patches
.\laniakea flash "firmware\custom\laniakea_v3.6+usab+Y-effects+leddedupe.bin"   # 5. flash it (calibration is kept)
```

**Linux / macOS** (sh):

```sh
sh scripts/setup.sh                                   # 1. venv (uses uv, python3-venv, or downloads a local uv)
.venv/bin/python scripts/install_re_tools.py --only xtensa   # 2. Xtensa assembler for your OS/CPU
./laniakea.sh backup                                  # 3. full flash dump (keep it!)
./laniakea.sh patcher build recommended               # 4. download official v3.6 + apply patches
./laniakea.sh flash "firmware/custom/laniakea_v3.6+usab+Y-effects+leddedupe.bin"   # 5. flash it
```

- **Linux:** add yourself to the serial group once and log in again: `sudo usermod -aG dialout $USER` (Arch/Fedora: `uucp`). On Ubuntu, `brltty` can grab CH340 adapters (`sudo apt remove brltty`).
- **macOS:** the CH340 shows up as `/dev/cu.wchusbserial*` or `/dev/cu.usbserial*` and is detected automatically. Older macOS versions may need WCH's CH34x driver.
- The wavetable editor works in any browser when started with `laniakea editor` (the module is reached
  through that local server). Opened as plain files, it needs Chrome/Edge (Web Serial).

`recommended` = **usability fixes** (sane factory-reset defaults, wider wavetable rows, 12-semitone
FREQ ranges) + **EFFECTS CV jack → wavetable Y (row)** + the **fix for the v3.4+ menu
crackle**. To undo: `laniakea flash v3.6` (official), or `laniakea restore <backup> --yes`.

## Everyday use

Two launchers run `tools/laniakea.py` with the local venv. Pick the one that matches your **shell**:

- `.\laniakea` (`laniakea.cmd`): Windows **cmd / PowerShell**
- `./laniakea.sh`: **bash/zsh/sh**, i.e. Linux, macOS, WSL, and Git Bash on Windows. A `.cmd` file can't run there (`@echo: not found`).

The examples use the Windows form. Everything, including `patcher`, works the same with `./laniakea.sh`:

```powershell
.\laniakea ports                 # find the module (CH340)
.\laniakea info                  # chip, flash, eFuses (read-only)
.\laniakea backup                # full 4 MB dump -> firmware\backup\  (do this before flashing anything)
.\laniakea version               # installed firmware version + patches (read-only)
.\laniakea settings              # saved ORBITS/SPACE settings + calibration (read-only; or: settings <dump.bin>)
.\laniakea fetch [--manuals]     # all official firmware versions (+ Magerit's PDF manuals)
.\laniakea flash v3.6            # official firmware, downloaded if needed (keeps calibration/NVS)
.\laniakea flash <file.bin>      # a patched build
.\laniakea restore <dump> --yes  # put an exact flash dump back
.\laniakea editor                # wavetable editor + firmware updater at http://127.0.0.1:8765 (any browser)
.\laniakea waves upload <bank.wav> [--bank N]   |   .\laniakea waves default [--bank N]
.\laniakea waves banks 1=a.wav 2=b.wav          # fill several banks (banks patch)
.\laniakea waves current   |   .\laniakea waves read -o mine.wav   # module's bank / read it back (banks patch)
.\laniakea akwf fetch fmsynth eorgan   # AKWF single cycles (CC0) -> wavetables\akwf\
.\laniakea bank wavetables\akwf\AKWF_fmsynth -o wavetables\banks\fm.wav
.\laniakea factory-waves         # export the firmware's factory wavetable -> wavetables\banks\factory_v3.6.wav
.\laniakea monitor [--reset]     # serial console
```

## Firmware patches

Each patch is a small Python file in `patches/`. Combine them freely:

```powershell
.\laniakea patcher list
.\laniakea patcher build recommended                                # usability + cv_to_y:source=effects + led_dedupe
.\laniakea patcher build cv_to_y:source=effects chords:set=pro led_dedupe
.\laniakea patcher build cv_to_y:source=shape,gain=-0.78            # SHAPE CV scans rows (inverted)
.\laniakea patcher build chords:set=my_chords.txt                   # your own 16 chords
.\laniakea patcher build recommended quantizer                      # + scale quantizer
.\laniakea patcher build recommended banks                          # + 8 wavetable banks
```

| Patch | What it does |
| --- | --- |
| `cv_to_y` | route a CV jack (`source=effects/space/orbits/...`) to the wavetable Y axis |
| `usability` | sane factory-reset defaults (SPACE amounts 25 %, pitch 0 %; adjustable), rows spread to 88 % of ORBITS-menu SHAPE, 12-semitone FREQ ranges |
| `led_dedupe` | **fix**: refresh the LED ring only when it changes (removes the v3.4+ menu crackle) |
| `chords` | replace the 16 ORBITS-menu chords (Laniakea Pro set, or your own file) |
| `banks` | 8 wavetable banks on the module; SPACE menu → EFFECTS selects the bank (loads when leaving the menu) |
| `quantizer` | scale quantizer: SPACE-menu FREQ = scale, SPACE-menu SPACE! = root; FREQ snaps to the scale |
| `quiet` | silence serial logging |
| `diag_guards`, `diag_noled` | diagnostics used to find the crackle (see RE notes) |
| `_template` | starting point for your own patch |

Output goes to `firmware\custom\`. How patches work and how to write one:
[docs/PATCHING.md](docs/PATCHING.md). Patching needs only the Xtensa toolchain; Ghidra is optional.

## Docs

- [docs/MANUAL.md](docs/MANUAL.md): how the module really works (from the firmware): init patch, troubleshooting, all ORBITS/SPACE functions, additive oscillator and resonator
- [docs/CUSTOM-FIRMWARE.md](docs/CUSTOM-FIRMWARE.md): the custom features (Y-axis CV, chord sets, crackle fix), enabling/disabling patches, building and flashing (CLI or editor)
- [docs/PATCHING.md](docs/PATCHING.md): how patches work, how to write one
- [docs/PRO-FEATURES.md](docs/PRO-FEATURES.md): which Laniakea Pro features can be ported
- [docs/WAVETABLES.md](docs/WAVETABLES.md): formats, AKWF, upload protocol
- [docs/RE-NOTES.md](docs/RE-NOTES.md): addresses, memory map, code map, v3.4 crackle investigation

## Not in this repository (regenerate locally)

| What | How to get it |
| --- | --- |
| Official firmware (`firmware/official/`) | `.\laniakea fetch`, or automatically on `laniakea patcher build` / `laniakea flash vX.Y` |
| Patched builds (`firmware/custom/`) | `laniakea patcher build …` |
| Your flash dumps (`firmware/backup/`) | `.\laniakea backup` |
| Magerit manuals (`docs/manuals/`) | `.\laniakea fetch --manuals` |
| Ghidra project, decompiled code (`re/ghidra/`) | `scripts/install_re_tools.py` then `scripts\ghidra_analyze.ps1 -Version v3.6` (Windows) or `scripts/ghidra_analyze.sh v3.6` |
| AKWF waves, built banks (`wavetables/`) | `.\laniakea akwf fetch …`, `.\laniakea bank …` |
| Toolchains (`.venv`, `tools/jdk`, `tools/ghidra`, `tools/xtensa-esp-elf`, `tools/uv`) | `scripts/setup.ps1` or `scripts/setup.sh`, then `scripts/install_re_tools.py` |

## Layout

| Path | |
| --- | --- |
| `tools/laniakea.py` | CLI: ports, info, backup, settings, fetch, flash, restore, waves, akwf, bank, monitor, editor |
| `tools/patcher.py`, `patchlib.py`, `symbols.py` | patch CLI, patch API (hooks, code cave, assembler), version-specific addresses |
| `tools/espimage.py`, `espinfo.py`, `img2elf.py`, `nvs.py` | ESP image parsing / checksums, ELF for Ghidra, NVS settings reader |
| `patches/` | one file per patch |
| `editor/` | wavetable editor (static web app; module access via `tools/editor_bridge.py`, or Web Serial) |
| `re/` | Ghidra scripts, version-diff helpers, ESP32 ROM symbols (Espressif, Apache-2.0) |
| `scripts/` | setup (`.ps1`/`.sh`), RE-tool installer (Windows/Linux/macOS), Ghidra headless/GUI launchers (`.ps1`/`.sh`) |
| `tests/` | `node tests/editor_dsp.test.mjs` |

## Legal

Unofficial and not affiliated with Magerit. Flashing modified firmware may void your
warranty. Magerit's firmware is their copyright: patched images are built locally for your own
module and must not be redistributed. Share patch files instead. AKWF waveforms are CC0.
