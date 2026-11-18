# Laniakea wavetables

## What the module actually stores

| | |
| --- | --- |
| Bank size | **64 waves** in an **8 × 8 grid** |
| Wave length | **128 samples**, signed 16-bit (the 256-sample upload is reduced to 128) |
| Layout | row-major: `wave = Y * 8 + X` (confirmed in the firmware's voice renderer) |
| X (column) | SHAPE knob + SHAPE CV → `X = shape * 7` |
| Y (row) | SHAPE inside the ORBITS menu (`tabla`) → `Y = tabla * 9`, clamped to row 8; `tabla >= 0.95` switches to the additive oscillator |
| Interpolation | bilinear between the 4 neighbouring waves + linear between samples (no band-limiting, so very bright waves alias at high pitch) |
| Storage | RAM `0x3ffc40c0` at runtime (with the `banks` patch: 8 banks, keys `onda_*`..`ondh_*`); uploaded waves persist in NVS keys `onda_0..7` (one blob per row of 8 waves, namespace `storage`) |
| Factory bank | stored in the firmware as `int32[8][1024]` at `0x3f4119fc` (low 16 bits used); any row missing from NVS is filled from it. `laniakea factory-waves` exports it as a WAV |

## Accepted input formats

Magerit's web page only accepts the **WaveEdit format**: a mono WAV with exactly
64 × 256 = 16384 samples (8- or 16-bit). The local tools are more permissive:

| Source | Editor (`editor/`) | CLI (`tools/laniakea.py`) |
| --- | --- | --- |
| WaveEdit / Magerit bank (64 × 256) | Load bank | `waves upload file.wav` |
| Any 64-wave table (64 × N samples, 8/16/24/32-bit, float) | Load bank | `waves upload` |
| Serum / Vital tables (`clm` chunk, 2048-sample frames, any frame count) | Load bank → 64 frames picked/crossfaded | `bank file.wav -o out.wav` |
| **Single cycles: AKWF (600 samples), Serum single-cycle, anything ≤ 8192 samples** | Import single cycles (fills slots from the selected cell) or drop on a cell | `bank DIR [DIR...] -o out.wav` |

All resampling is band-limited (FFT), so 600 → 256 → 128 sample conversions
don't add aliasing. Magerit's page simply drops every other sample; pick
`decimate (Magerit)` in the editor or `--decimate` in the CLI to get identical results.

## AKWF (Adventure Kid Waveforms)

Yes: AKWF is CC0 (public domain) and works well. Each AKWF file is one cycle of
600 samples; the module needs 64 of them per bank.

```powershell
.venv\Scripts\python.exe tools\laniakea.py akwf list
.venv\Scripts\python.exe tools\laniakea.py akwf fetch fmsynth eorgan hvoice overtone bw_perfectwaves
# whole grid from one folder (64 waves spread evenly across the folder)
.venv\Scripts\python.exe tools\laniakea.py bank wavetables\akwf\AKWF_fmsynth -o wavetables\banks\fm.wav
# one folder per row anchor (2-8 folders); rows in between are crossfades
.venv\Scripts\python.exe tools\laniakea.py bank wavetables\akwf\AKWF_bw_perfectwaves wavetables\akwf\AKWF_overtone wavetables\akwf\AKWF_eorgan wavetables\akwf\AKWF_hvoice -o wavetables\banks\basic_to_voice.wav
.venv\Scripts\python.exe tools\laniakea.py waves upload wavetables\banks\fm.wav
```

Or in the editor: select a cell, **Import single cycles**, multi-select AKWF files.

Tips for this module's grid:
- Waves that are next to each other along X should be similar, because SHAPE + CV sweeps them continuously. Use **Interpolate row** to build smooth morphs between two hand-picked waves.
- Rows (Y) work well as "families". With the `shape-cv-xy` firmware patch, CV moves diagonally, so a smooth gradient on both axes sounds best.

## Upload protocol (serial, 115200 8N1)

1. Pulse reset (RTS high 150 ms with DTR low), wait 2 s for the app to boot.
2. Send `MAGW`, expect `0x06` (ACK). Retry up to 5× with a 300 ms timeout.
3. For k = 0..63 send `{"W":k,"S":[s0,...,s127]}` (int16 values, no spaces) and wait for ACK (2 s timeout; `0x15` = NACK).
4. `MAGD` + ACK restores the factory bank (of the current bank, with the `banks` patch).
5. With the `banks` patch: `MAG1` … `MAG8` selects, saves and loads that bank, then ACKs (allow up
   to ~5 s right after an upload: the module first saves the previous bank). A following `MAGW`
   uploads into it. Commands work at any time; no reset is required.
