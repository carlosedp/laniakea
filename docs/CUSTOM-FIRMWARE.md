# Custom firmware: features, building and flashing

A custom build is the **official Magerit v3.6** with a set of patches applied. Nothing
else changes: same sound engine, and your calibration and settings are kept when flashing.

## Which patches are in my build?

The patches are chosen when you **build**. Each build is a complete firmware image, and
the image name and version string list its patches:

```text
laniakea_v3.6+usab+Y-effects+leddedupe.bin      version "3.6+usab+Y-effects+leddedupe"
```

To see what the module runs: `laniakea version` (read-only), or the `App version:` line of
`laniakea monitor --reset`.

## Enable / disable patches: build, then flash

There's no on/off switch inside the module. To change features, **build a new image with
the patches you want, then flash it**. Leaving a patch out of the build command disables it.

```powershell
# Windows: .\laniakea patcher ...      Linux/macOS/WSL/Git Bash: ./laniakea.sh patcher ...
.\laniakea patcher list                                             # all patches + options
.\laniakea patcher build recommended                                # usability + cv_to_y:source=effects + led_dedupe
.\laniakea patcher build led_dedupe                                 # only the crackle fix (stock Y behaviour)
.\laniakea patcher build cv_to_y:source=effects led_dedupe chords:set=pro
.\laniakea patcher build cv_to_y:source=space,gain=-0.78 led_dedupe
.\laniakea patcher build recommended quantizer                      # + scale quantizer
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
- **Base row:** ORBITS menu → SHAPE. Rows 1–8 use the first ~88 % of that knob's travel with the `usability` patch (~78 % stock). For a full CV sweep, set it fully counter-clockwise (row 1) and send positive CV.
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

## Feature: scale quantizer (`quantizer`)

The total pitch (FREQ knob + V/OCT) snaps to a scale. Turning FREQ steps through the scale,
so small bumps stay in key, and V/OCT sequences land in key. Pitches are absolute (A = 440 Hz),
so the key is a real musical key.

**Setting it up** (everything is saved automatically):

1. Press **SPACE!** (button) to enter the SPACE menu.
2. Turn **FREQ** to pick the **scale**.
3. Turn the **SPACE!** knob to pick the **root / key**.
4. Press **SPACE!** again to leave.

| FREQ in SPACE menu (travel) | Scale |   | SPACE! in SPACE menu (travel) | Root |
| --- | --- | --- | --- | --- |
| 0–8 % (fully CCW) | **off** (stock behaviour) | | 0–8 % | C |
| 8–17 % | chromatic | | 8–17 % | C# |
| 17–25 % | major | | 17–25 % | D |
| 25–33 % | natural minor | | 25–33 % | D# |
| 33–42 % | harmonic minor | | 33–42 % | E |
| 42–50 % | major pentatonic | | 42–50 % | F |
| 50–58 % | minor pentatonic | | 50–58 % | F# |
| 58–67 % | dorian | | 58–67 % | G |
| 67–75 % | mixolydian | | 67–75 % | G# |
| 75–83 % | spanish (phrygian dominant) | | 75–83 % | A |
| 83–92 % | blues | | 83–92 % | A# |
| 92–100 % | whole tone | | 92–100 % | B |

Notes:

- **SPACE! no longer bends pitch**: the SPACE-menu FREQ slot now selects the scale. The SPACE-menu
  SPACE! slot was unused by the stock firmware and is now the root.
- **After a factory reset** the quantizer is off with the `usability` patch (SPACE amounts default
  to 0). Without it, SPACE-menu FREQ defaults to 75 % (spanish): turn it fully counter-clockwise.
- **Hysteresis:** 0.12 semitone keeps CV noise from flickering between notes (`hyst=` option).
- **Your own scale list:** `quantizer:scales=major,minor,dorian,blues` (up to 15; zone 1 is
  always off). Available scales: chromatic, major, minor, harmonic_minor, melodic_minor,
  major_pentatonic, minor_pentatonic, dorian, phrygian, lydian, mixolydian, locrian, spanish,
  blues, whole_tone, iwato, hirajoshi, fourths, fifths, octaves. Fewer scales give wider zones.
- **Chords** (CLUSTER voices) are built on top of the quantized root note, so pick chords that
  fit the scale.

Build: `laniakea patcher build recommended quantizer`.

## Feature: 8 wavetable banks (`banks`)

The module stores **8 wavetable banks** (64 waves each) instead of one.

**Selecting a bank:**

1. Press **SPACE!** to enter the SPACE menu.
2. Turn **EFFECTS**: 8 zones of 12.5 % each = banks 1–8 (fully CCW = bank 1).
3. Press **SPACE!** again to leave. The bank loads when you leave the menu, and is restored at power-up.

**Filling a bank:** select it on the module, then upload from the editor (*Upload to module*) or
`laniakea waves upload <bank.wav>`. Uploads always go to the **bank currently loaded on the module**,
and *Restore factory waves* resets that bank.

| | |
| --- | --- |
| Bank 1 | the stock storage: anything you uploaded before keeps working |
| Empty banks | play the **factory waves** built into the firmware (`laniakea factory-waves` exports them as a .wav to edit) |
| Storage | 16 KB per bank in the settings flash (2.1 MB available) |
| Side effect | SPACE! no longer shortens the reverb (that SPACE-menu slot is the bank selector now) |
| Factory reset | back to bank 1 (with or without `usability`); the banks' waves are erased like all settings |

If you'd set a SPACE amount for EFFECTS before installing this patch, you may start in another
bank: set SPACE-menu EFFECTS fully counter-clockwise for bank 1.

Build: `laniakea patcher build recommended banks` (option `banks:banks=4` for fewer, wider zones).

## Usability fixes (`usability`)

Three small changes that remove most of the "why is it silent / weird" moments, especially after a
factory reset. Each can be turned off on its own.

| Option | Default | Stock behaviour → patched |
| --- | --- | --- |
| `space_default` | 25 | After a reset all 7 SPACE amounts were 75 %: with SPACE! down, every parameter (pitch too) ran at 25 %, so the module seemed silent or played sub-bass. Now ORBITS, COLOR, SHAPE, EFFECTS and CLUSTER default to **25 %**, so SPACE! still does something but gently. |
| `space_default_freq` | 0 | The pitch slot defaults to **0 %**, so SPACE! never drops the pitch after a reset (25 % would be about two octaves at SPACE! minimum). With the quantizer this slot is the scale, so 0 = off. |
| `y_top` | 0.88 | ORBITS-menu SHAPE reached row 8 at ~78 %, then nothing changed until the additive oscillator at 95 %. Now the 8 rows spread to **88 %**, leaving a small dead zone before additive. |
| `freq_semis` | 12 | In the fixed-octave FREQ ranges (ORBITS menu → FREQ), the knob covered only **7** semitones, although the manual says 12. Now it covers **12**. |

The SPACE! knob's own slot always resets to 0 (unused by stock firmware; with the quantizer it's the root, so C).
These only apply on a factory reset / first boot. Values you set in the SPACE menu are saved as usual.

Examples: `usability:space_default=10` (gentler SPACE!), `usability:space_default=75,space_default_freq=75`
(stock defaults), `usability:y_top=0.92` (smaller dead zone).
`usability` always runs first, and `cv_to_y` follows its row spread automatically.

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
