# Custom firmware: features, building and flashing

A custom build is the **official Magerit v3.6** with a set of patches applied. Nothing
else changes: same sound engine, and your calibration and settings are kept when flashing.

## Which patches are in my build?

The patches are chosen when you **build**. Each build is a complete firmware image, and
the image name and version string list its patches:

```text
laniakea_v3.6+Y-effects+leddedupe.bin      version "3.6+Y-effects+leddedupe"
```

To see what the module runs: `laniakea version` (read-only), or the `App version:` line of
`laniakea monitor --reset`.

## Enable / disable patches: build, then flash

There's no on/off switch inside the module. To change features, **build a new image with
the patches you want, then flash it**. Leaving a patch out of the build command disables it.

```powershell
$P = ".venv\Scripts\python.exe tools\patcher.py"      # Linux/macOS: .venv/bin/python tools/patcher.py
& $P list                                             # all patches + options
& $P build recommended                                # cv_to_y:source=effects + led_dedupe
& $P build led_dedupe                                 # only the crackle fix (stock Y behaviour)
& $P build cv_to_y:source=effects led_dedupe chords:set=pro
& $P build cv_to_y:source=space,gain=-0.78 led_dedupe
```

Images go to `firmware/custom/`. Flash one of three ways:

| How | Command / place |
| --- | --- |
| CLI | `.\laniakea flash "firmware\custom\<file>.bin"`  (Linux/macOS: `./laniakea.sh flash …`) |
| Wavetable editor | `.\laniakea editor` → **Firmware** panel → *Custom .bin…* → *Flash firmware* |
| Back to official | `.\laniakea flash v3.6`, the editor's *Official release* list, or Magerit's web updater |

Before the first custom flash, run `laniakea backup` (or *Backup flash…* in the editor).
`laniakea restore <dump> --yes` puts the exact old state back, including calibration.

---

## Feature: wavetable Y axis on a CV jack (`cv_to_y`)

Stock firmware: the wavetable row (Y) is set only by **SHAPE inside the ORBITS menu**; no
CV reaches it. The patch adds a CV jack to it:

**Y row = ORBITS-menu SHAPE position + gain × CV**, clamped to rows 1–8.

| Option | Default | Meaning |
| --- | --- | --- |
| `source` | (required) | which CV jack: `effects` (recommended), `space`, `orbits`, `color`, `cluster`, `shape` |
| `exclusive` | `1` | the jack stops modulating its own knob (fully repurposed) |
| `gain` | `0.778` (7/9) | CV depth. 7/9 moves rows at the same rate the SHAPE CV moves columns. Negative values invert the direction, smaller values give finer steps |

How to use it (with `source=effects`):

- **The EFFECTS knob still controls reverb and freeze.** Only the EFFECTS *jack* changes job.
- **Base row:** ORBITS menu → SHAPE. Rows 1–8 use the first ~78 % of that knob's travel. For a full CV sweep, set it fully counter-clockwise (row 1) and send positive CV.
- **Bipolar CV** (e.g. an LFO) moves around the base row: set the base to the middle (around 40 %).
- **Nothing patched** = no change: the jack reads 0.
- **Clamping:** the CV never pushes Y into the additive oscillator. If you select additive yourself (ORBITS-menu SHAPE ≥ 95 %), the CV is ignored.
- **Combined with the SHAPE CV (X)**, you get two-dimensional scanning of the 8×8 bank from two CV sources.

## Feature: chord sets (`chords`)

**Selecting a chord:** ORBITS menu → **CLUSTER**. The knob travel is split into **16 zones**,
one chord each. Back in the normal layer, turning CLUSTER right of 12 o'clock adds the chord's
voices one by one (up to 8), lowest/most important first.

| # | Stock (Magerit) | `set=pro` (Laniakea Pro chords) |
| --- | --- | --- |
| 1 | unison (detuned) | unison (detuned) |
| 2 | octaves | octaves |
| 3 | fifths | fifths |
| 4 | sus2 | fourths |
| 5 | sus4 | major |
| 6 | major | dominant 7 |
| 7 | dominant 7 | major 7 |
| 8 | major 7 | augmented |
| 9 | major 9 | minor |
| 10 | major 11 | minor 7 |
| 11 | major 13 | diminished |
| 12 | minor | sus2 |
| 13 | minor 7 | sus4 |
| 14 | minor 9 | add9 |
| 15 | minor 11 | minor 9 |
| 16 | minor 13 | major 6 |

**Your own chords:** write a text file (one chord per line, semitones above the root) and
build with `chords:set=<file>`. See [patches/chord_sets/example.txt](../patches/chord_sets/example.txt):

```text
major 7:     0 4 7 11
quartal:     0 5 10 15
unison:      0 -0.12 0.08 12 -0.1 0.1 24 12.05     <- 8 numbers = exact voicing (with detune)
```

Short chords are voiced over the 8 voices automatically, like Magerit's own: root, slightly
flat doubled root (for thin chords), the other tones, then the same an octave up. Up to 16 lines;
missing lines repeat the last chord.

## Fix: menu crackle (`led_dedupe`)

Firmware v3.4–v3.6 crackles while a menu is open, worst with ORBITS-menu SHAPE fully
clockwise. The menu display re-sends identical data to the LED ring every 8 ms, and the
transmissions leak into the audio. The patch only refreshes the ring when a pixel changes.
The ring looks the same and the crackle is gone. It's in `recommended`; see
[RE-NOTES](RE-NOTES.md#v33--v34-changes-menu-clacking-regression) for the investigation.

## Other patches

| Patch | Use |
| --- | --- |
| `quiet` | silence serial log output |
| `diag_guards`, `diag_noled` | diagnostics from the crackle investigation (not for daily use) |
| `_template` | starting point for writing your own (see [PATCHING.md](PATCHING.md)) |
