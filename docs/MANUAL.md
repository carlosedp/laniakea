# Laniakea: the missing manual

Based on reverse engineering firmware **v3.6** plus Magerit's manual. Statements marked
**(code)** come from the firmware itself. They're exact behaviour and sometimes differ
from the official manual.

- [Laniakea: the missing manual](#laniakea-the-missing-manual)
  - [The confusing names, first](#the-confusing-names-first)
  - [Starting point: the simplest sound ("init patch")](#starting-point-the-simplest-sound-init-patch)
    - [Why it "acts weird" or goes silent](#why-it-acts-weird-or-goes-silent)
  - [Signal flow](#signal-flow)
  - [Knobs: all three layers](#knobs-all-three-layers)
    - [FREQ.](#freq)
    - [CLUSTER](#cluster)
    - [SHAPE: the 8 × 8 wavetable](#shape-the-8--8-wavetable)
    - [ORBITS (knob)](#orbits-knob)
    - [SPACE! (the macro)](#space-the-macro)
    - [EFFECTS](#effects)
  - [The additive oscillator: what it is and how to use it](#the-additive-oscillator-what-it-is-and-how-to-use-it)
    - [What it is (code)](#what-it-is-code)
    - [How to get there](#how-to-get-there)
    - [What the knobs do in additive mode](#what-the-knobs-do-in-additive-mode)
    - [Recipes](#recipes)
  - [The resonator: what it is and how to use it](#the-resonator-what-it-is-and-how-to-use-it)
    - [What it is (code)](#what-it-is-code-1)
    - [The knobs that control it](#the-knobs-that-control-it)
    - [Recipes (start from the init patch, then:)](#recipes-start-from-the-init-patch-then)
    - [Gotchas](#gotchas)
  - [Menus and knob pickup (code)](#menus-and-knob-pickup-code)
  - [Inputs](#inputs)
  - [Button gestures (Magerit manual; consistent with code)](#button-gestures-magerit-manual-consistent-with-code)
  - [With the patched firmware (`firmware/custom/`)](#with-the-patched-firmware-firmwarecustom)

## The confusing names, first

| Name                  | What it actually is                                                                                                                    |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| **ORBITS button**     | A _menu/shift_ button. Press once to enter the ORBITS menu, where every knob edits a hidden secondary parameter. Press again to leave. |
| **ORBITS knob**       | Has nothing to do with the menu. It's the **resonator mix**: oscillator on the left, modal resonator / strings on the right.           |
| **SPACE! knob** (big) | A **macro** that scales every parameter at once (formula below).                                                                       |
| **SPACE! button**     | Enters the SPACE menu, where each knob sets _how much_ SPACE! affects that parameter.                                                  |
| **EFFECTS knob**      | Reverb time, with freeze at the end of its travel.                                                                                     |

## Starting point: the simplest sound ("init patch")

One clean voice of the top-left wave (X1, Y1), no chord, no filter, no drive, no
resonator, no reverb, no SPACE! macro. Knob positions come from the code.

**0. Unplug every jack.** Especially EXCITER: with a cable in it, you only hear sound while it sends an envelope.

**1. Normal layer** (no menu active):

| Knob             | Position                | Why (code)                                                                                                         |
| ---------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------ |
| **SPACE!** (big) | **fully clockwise**     | at max, every parameter = its knob. Anywhere else, parameters are pulled down (see below)                          |
| FREQ.            | 12 o'clock              | middle of the 4-octave range, clearly audible                                                                      |
| CLUSTER          | exactly 12 o'clock      | one voice. Off-centre adds voices (right = chord, left = detuned chaos), so fine-tune until any beating disappears |
| COLOR            | 12 o'clock              | neutral: no low-pass (left), no overdrive (right)                                                                  |
| SHAPE            | fully counter-clockwise | column X1                                                                                                          |
| ORBITS (knob)    | fully counter-clockwise | below ~14 % the resonator is completely out                                                                        |
| EFFECTS          | fully counter-clockwise | below ~10 % the reverb is off                                                                                      |

**2. ORBITS menu.** Press ORBITS, set these, press ORBITS again to leave:

| Knob   | Position                | Why (code)                                                                                              |
| ------ | ----------------------- | ------------------------------------------------------------------------------------------------------- |
| SHAPE  | fully counter-clockwise | row Y1 (rows fill the first ~78 % of travel; ≥ 95 % = additive oscillator)                              |
| FREQ.  | fully counter-clockwise | full-range mode (the first ~11 % of travel)                                                             |
| SPACE! | about 2 o'clock         | output volume: gain = 2 × v², so v ≈ 0.71 (≈ 2 o'clock) is unity, fully counter-clockwise is **silent** |

The other ORBITS-menu values (chord, EXCITER decay, LPG colour, bow/pluck) don't
matter with one voice and no EXCITER cable.

**3. Re-sync the knobs.** After leaving a menu, knobs use scaled pickup. Sweep each
knob you touched in the menu to an end stop and back to its position, so the normal
parameter is locked to the knob again.

You now hear a plain, dry wave. Build up from here one knob at a time: CLUSTER right
for chords, SHAPE for X, the EFFECTS jack (patched firmware) or ORBITS-menu SHAPE for Y,
ORBITS for the resonator, EFFECTS for reverb, then SPACE! last.

### Why it "acts weird" or goes silent

| Symptom                                                        | Likely cause (from the code)                                                                                                                                                                                                                         | Fix                                                                              |
| -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| No sound, or very low rumble, especially after a factory reset | **SPACE! turned down.** Factory SPACE amounts are **75 % for every parameter, including FREQ**: with SPACE! at minimum each parameter runs at 25 % of its knob, so the pitch drops several octaves (often inaudible) and everything else shrinks too | SPACE! fully clockwise, or lower the amounts in the SPACE menu (especially FREQ) |
| No sound at all                                                | Cable in **EXCITER** without an envelope or gate: the LPG/VCA stays closed                                                                                                                                                                           | unplug EXCITER, or send it a gate/envelope                                       |
| No sound at all                                                | **Volume** (ORBITS menu → SPACE! knob) near minimum                                                                                                                                                                                                  | ORBITS menu, SPACE! to ~2 o'clock                                                |
| Knobs "do the wrong thing"                                     | **Still inside a menu** (ORBITS or SPACE), so knobs edit hidden values                                                                                                                                                                               | press that button again to leave                                                 |
| A knob does nothing after leaving a menu                       | scaled pickup: the parameter is catching up                                                                                                                                                                                                          | sweep the knob to an end stop                                                    |
| Sound stuck on one timbre while turning ORBITS-menu SHAPE      | Y between ~78 % and 95 % stays on row 8; ≥ 95 % switches to additive                                                                                                                                                                                 | keep ORBITS-menu SHAPE below ~75 % for the wavetable                             |
| Hiss / noise                                                   | CLUSTER fully left + COLOR fully right = white-noise mode                                                                                                                                                                                            | move CLUSTER back to 12 o'clock                                                  |
| Muffled / dull                                                 | COLOR left of 12 = low-pass; ORBITS right = resonator; SPACE! amounts on COLOR                                                                                                                                                                       | COLOR 12 o'clock, ORBITS fully left                                              |
| Pitch off / jumps                                              | something in V/OCT, or factory reset erased the V/OCT calibration                                                                                                                                                                                    | unplug V/OCT, or recalibrate (both buttons 2 s)                                  |
| Crackling/clacking while a menu is open (firmware v3.4–v3.6) | LED ring interference: the menu display re-sends the LED data every 8 ms (v3.3 didn't). Worst with ORBITS-menu SHAPE fully CW | flash a build with the `led_dedupe` patch, or leave the menu |
| Endless drone that won't stop                                  | EFFECTS ≥ 95 % = reverb freeze                                                                                                                                                                                                                       | turn EFFECTS down                                                                |

A factory reset also erases **calibration** (jack detection thresholds and V/OCT).
Run the calibration after every factory reset, or restore your flash backup.

## Signal flow

```text
 FREQ, V/OCT ─► OSCILLATOR (wavetable 8×8  |  additive  |  noise)  × 1–8 voices (CLUSTER, chord)
                    │
                    ├─► COLOR: low-pass ◄─ 12 o'clock ─► overdrive (+ limiter)
                    │
                    ├─► RESONATOR / STRINGS (modal, 32 modes)      ◄─ ORBITS knob = mix
                    │
                    ├─► LPG / VCA  ◄─ EXCITER (decay, filter amount: ORBITS menu)
                    │
                    ├─► VOLUME (ORBITS menu: SPACE! knob)
                    │
                    └─► STEREO REVERB (EFFECTS, freeze ≥ 95 %)  ─► OUT L/R  (48 kHz, 16-bit)
```

## Knobs: all three layers

| Knob        | Normal                                 | ORBITS menu                        | SPACE menu   | CV jack             |
| ----------- | -------------------------------------- | ---------------------------------- | ------------ | ------------------- |
| **FREQ.**   | pitch                                  | range mode                         | SPACE amount | (V/OCT is separate) |
| **CLUSTER** | voices: ← chaos · 1 voice · harmonic → | chord (16)                         | SPACE amount | yes                 |
| **COLOR**   | ← LPF · neutral · overdrive →          | EXCITER filter amount (LPG colour) | SPACE amount | yes                 |
| **SHAPE**   | wavetable X (column)                   | wavetable Y (row) / additive       | SPACE amount | yes (X only)        |
| **ORBITS**  | oscillator ↔ resonator mix             | EXCITER decay                      | SPACE amount | yes                 |
| **SPACE!**  | macro amount                           | output volume                      | (n/a)        | yes                 |
| **EFFECTS** | reverb time / freeze                   | string mode: bow ≤ 50 % < pluck    | SPACE amount | yes                 |

### FREQ

- **(code)** Full-range mode: the knob covers **48 semitones (4 octaves)**. V/OCT adds on top, up to the engine's pitch limit (about 9 octaves in total).
- **ORBITS menu (code)**: the knob travel is split into 9 zones. Zone 1 (the first ~11 %) selects full range. Zones 2–9 fix the octave (8 octaves), and in those modes FREQ. covers **7 semitones** above that octave's C. The official manual says 12.
- V/OCT is only applied when a jack is detected in the V/OCT input.

### CLUSTER

- 12 o'clock = one voice. Clockwise adds up to 8 voices in the selected chord, in voicing order. Counter-clockwise adds up to 8 detuned "chaos" voices; COLOR also sets the chaos speed.
- Trick: CLUSTER fully left + COLOR fully right gives white noise, and SHAPE then morphs its resonant filter LP → BP → HP.
- **ORBITS menu (code)**: 16 chords in this order (from the chord table in flash):
  1 unison (detuned) · 2 octaves · 3 fifths · 4 sus2 · 5 sus4 · 6 major · 7 dominant 7 · 8 major 7 · 9 major 9 · 10 major 11 · 11 major 13 · 12 minor · 13 minor 7 · 14 minor 9 · 15 minor 11 · 16 minor 13.
  (The official manual lists "M + 7m" twice; number 8 is actually major 7.)

### SHAPE: the 8 × 8 wavetable

- **(code)** X = SHAPE × 7, so the full knob travel crosses all 8 columns. SHAPE CV adds to X.
- **ORBITS menu (code)**: Y row = value × 9, clamped to row 8:
  - **0 % → ~78 %** of travel: rows 1 → 8 (interpolated)
  - **~78 % → 95 %**: stays on row 8 (dead zone)
  - **≥ 95 %**: switches to the **additive oscillator**. SHAPE then sets its texture, CLUSTER the number of partials, and COLOR clips the spectrum.
- Rows of the factory bank: 1 Basic · 2 Drone · 3 Envelopes · 4 Basic fusion · 5 Ambient · 6 Organ A · 7 Organ B · 8 Harmonics.
- Both axes are bilinearly interpolated. Waves are 128 samples, read without band-limiting, so very bright waves alias at high pitches.

### ORBITS (knob)

- **(code)** mix = clamp(1.4 × knob − 0.2): pure oscillator below ~14 %, pure resonator above ~86 %.
- COLOR sets resonator brightness/decay and SHAPE its structure (plastic, tube, bell, string).
- **ORBITS menu**: EXCITER decay time.

### SPACE! (the macro)

- **(code)** For each parameter: **effective = knob × (1 − amount × (1 − SPACE!))**.
  - SPACE! fully clockwise: every parameter is exactly where its knob is.
  - Turning SPACE! down pulls each parameter towards zero by its _amount_ (set in the SPACE menu). Amount 0 means SPACE! doesn't touch that parameter.
  - For CLUSTER, "towards zero" means towards one voice. For FREQ it lowers the pitch, so give FREQ a small amount unless you want big pitch dives.
- **ORBITS menu (code)**: output volume, gain = 2 × value² (default 0.5 → ×0.5; fully clockwise → ×2, +6 dB).

### EFFECTS

- Reverb time. **(code)** At ≥ 95 % the reverb freezes into an endless drone, and new sound plays on top.
- **ORBITS menu (code)**: string behaviour on EXCITER: ≤ 50 % = bowed (no pluck), > 50 % = plucked.

## The additive oscillator: what it is and how to use it

### What it is (code)

A separate _single-voice_ engine that builds the sound from
harmonic partials: a sum of sines locked to the fundamental. When it's active, the
whole wavetable engine is switched off, including the 8-voice cluster loop. So:

- **No chords and no chaos voices.** CLUSTER changes meaning (below).
- **No COLOR overdrive and no white-noise mode.** Those stages are bypassed in this mode.
- Everything after the oscillator still works: resonator (ORBITS), EXCITER/LPG, volume, reverb, SPACE!.
- Always harmonic and clean: no aliasing, very stable pitch. Organ-, flute- and vowel-like.

### How to get there

ORBITS menu → SHAPE fully clockwise (≥ 95 %) → leave the menu.
To go back, put ORBITS-menu SHAPE below ~75 % (rows). With the `Y-effects` firmware,
the EFFECTS CV has no effect in additive mode (rows only).

### What the knobs do in additive mode

From the code; the mapping is approximate:

| Knob / CV    | Additive function                                                                                                                                       |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CLUSTER      | **which partials are emphasised**, sweeping from low/dark to high/bright. The whole travel is a spectral sweep: no voices, and 12 o'clock isn't special |
| SHAPE        | **texture**: soft, classic (smooth spectrum) → gritty (sharper, buzzier spectrum)                                                                       |
| COLOR        | **carves the spectrum** (clips/removes partials) instead of filtering or driving                                                                        |
| FREQ / V/OCT | pitch as usual                                                                                                                                          |

### Recipes

- _Pure organ / flute drone_: CLUSTER left of centre, SHAPE left, COLOR 12 o'clock, EFFECTS ~11 o'clock.
- _Talking / vowel sweeps_: an LFO or envelope into **CLUSTER CV** sweeps the emphasised partials like a formant. Add a little SHAPE CV for grit.
- _Bass_: FREQ low, CLUSTER fully left (fundamental-heavy), SHAPE slightly right for bite.
- _Bowed organ body_: additive into the resonator with ORBITS at ~12 o'clock, SHAPE (resonator structure) around 2 o'clock (harmonic).

## The resonator: what it is and how to use it

### What it is (code)

A **32-mode modal resonator** (a bank of tuned resonant filters,
like the body of an instrument) with a **string model** built in. It's tuned to the
oscillator's pitch and always fed by the oscillator. EXCITER additionally _strikes_ it.

### The knobs that control it

| Control                       | Resonator function (code)                                                                              |
| ----------------------------- | ------------------------------------------------------------------------------------------------------ |
| **ORBITS knob**               | mix: < ~14 % pure oscillator, ~14–86 % blend, > ~86 % pure resonator                                   |
| **SHAPE**                     | **material**, i.e. the spacing of the 32 modes (measured from the firmware's mode tables):             |
|                               | fully left: very stretched, sparse, inharmonic (stiff bar / plate / plastic, and lower-pitched)        |
|                               | ~9–10 o'clock: bell-like (1 : 2.6 : 4.8 …)                                                             |
|                               | 12 o'clock: slightly stretched (tube / piano-like)                                                     |
|                               | ~2 o'clock: **perfectly harmonic** (string)                                                            |
|                               | fully right: compressed (hollow, membrane-like)                                                        |
| **COLOR**                     | brightness and length of the ring: right = brighter, longer                                            |
| **EXCITER** level             | rising edge = strike. A **higher voltage strikes brighter** (it adds to the brightness), like velocity |
| ORBITS menu → **ORBITS knob** | EXCITER decay: how long the LPG/strike stays open                                                      |
| ORBITS menu → **COLOR**       | how much the LPG filters as it closes (VCA → low-pass gate)                                            |
| ORBITS menu → **EFFECTS**     | string response: ≤ 50 % = **bowed** (no pluck, smooth), > 50 % = **plucked** on each trigger           |

**Without anything in EXCITER** the resonator acts as a _body_ on the continuous
oscillator: a resonant, metallic or woody colouring of the drone. **With EXCITER** it
becomes percussive or plucked, and the LPG makes notes.

### Recipes (start from the init patch, then:)

- _Plucked string_: ORBITS fully right, SHAPE ~2 o'clock (harmonic), COLOR ~1 o'clock. ORBITS menu: EFFECTS > 50 % (pluck), ORBITS knob ~10 o'clock (short decay). Triggers into EXCITER, sequence V/OCT.
- _Bell / mallet_: same, but SHAPE ~9–10 o'clock (bell spacing) and COLOR further right for a long shimmer. Accents: a louder trigger voltage = brighter strike.
- _Bowed string pad_: ORBITS menu: EFFECTS < 50 % (bow), ORBITS knob ~2 o'clock (long). A slow AD/ADSR into EXCITER. SHAPE ~2 o'clock, some EFFECTS (reverb).
- _Metal / plate hits_: SHAPE fully left, COLOR right, short triggers. Try CLUSTER right for chordal excitation.
- _Resonant drone body_: nothing in EXCITER, ORBITS ~12 o'clock, CLUSTER right (a chord rings the modes sympathetically), slow LFO on SHAPE CV to morph the material.

### Gotchas

- The resonator follows FREQ / V/OCT. Moving the pitch retunes the "instrument".
- ORBITS right of ~86 % removes the dry oscillator completely. If you hear nothing with EXCITER patched, the strike may be too weak: raise COLOR or the trigger voltage.
- In the ORBITS menu, EFFECTS is a two-way switch (bow/pluck); intermediate positions do nothing more.

## Menus and knob pickup (code)

- In a menu, a knob's secondary value **only changes once you move the knob more than 5 %**, so entering a menu never changes anything by itself. The LED ring shows the value you're editing.
- When you leave a menu, parameters you touched **don't jump**. The normal value converges proportionally as you turn the knob ("scaled pickup") and locks back on when they meet.
- Menu settings and SPACE amounts are saved to NVS automatically.

## Inputs

- 8 jacks with **jack detection** (code): V/OCT, EXCITER and 6 CVs (CLUSTER, COLOR, SHAPE, ORBITS, SPACE!, EFFECTS). Unpatched jacks are ignored, and detection thresholds are calibrated per jack (`th_1..8`).
- CV range −4 V … +4 V (added to the knob). V/OCT −2.5 V … +5 V. EXCITER 0 … +7 V.
- **EXCITER**: an envelope or trigger here fires new "particles", excites the resonator/strings, and drives the LPG/VCA. Decay is set by the ORBITS knob in the ORBITS menu, and filtering amount by COLOR in the ORBITS menu.

## Button gestures (Magerit manual; consistent with code)

| Gesture                                              | Action                                                                                              |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| ORBITS short press                                   | enter/leave ORBITS menu                                                                             |
| SPACE! short press                                   | enter/leave SPACE menu                                                                              |
| one button held 2 s                                  | show firmware version (top half blinks = major, bottom half = minor)                                |
| both buttons 2 s, all jacks unplugged                | calibration: then ORBITS = jack sensitivity only, SPACE! = also V/OCT (feed 1 V, press; 3 V, press) |
| ORBITS held at power-on until the ring is blue-white | factory reset (erases calibration and settings)                                                     |

## With the patched firmware (`firmware/custom/`)

- `Y-<jack>`: that CV jack now moves the **wavetable row (Y)** instead of its knob. The ORBITS-menu SHAPE position is the starting row and the CV moves around it. Rows are clamped to 1–8, so the CV never switches to the additive oscillator.
- `chords-pro`: the 16 chords become the Laniakea Pro set: unison, octaves, fifths, fourths, major, dom7, maj7, augmented, minor, min7, diminished, sus2, sus4, add9, min9, maj6.
- `leddedupe`: fixes the v3.4+ menu crackle.
- `quant`: scale quantizer. In the SPACE menu, FREQ picks the scale and SPACE! the root. FREQ snaps to the scale, and SPACE! no longer bends pitch.

Details, options, custom chord files, and how to build and flash: [CUSTOM-FIRMWARE.md](CUSTOM-FIRMWARE.md).
