# Laniakea Pro features: what can move to the original Laniakea?

Hardware limits of the original:
- **ESP32-PICO-D4**: 2 cores at 240 MHz, 520 KB RAM, **no PSRAM**. Roughly 280 KB of heap is free at boot.
- USB goes through a **CH340 serial bridge**, so no native USB MIDI or audio.
- 7 knobs, 2 buttons, 8 RGB LEDs, 6 CV inputs + V/OCT + EXCITER.
- 2.1 MB of NVS, so storage is not a problem.

| Pro feature | On Laniakea | Effort | Status |
| --- | --- | --- | --- |
| **Custom chords** | Chord table is data in flash: 16 chords × 8 voices | easy | ✅ `chords` patch (Pro set or your own file) |
| **ASSIGN CV input** (CV → secondary parameter) | Hook the parameter mixer and add a CV to any ORBITS-menu value | easy–medium | ✅ for Y (`cv_to_y`); same technique for chord, decay, LPG colour, octave… |
| **Chord CV in whole volts** | CV → `acorde` (×16) | easy | next candidate (`cv_to_param`) |
| **Scale quantizer + root** | Hook pitch (semitone value before the clamp), snap to a scale table in the cave | medium | feasible; needs a control (CV, an ORBITS-menu knob, or a fixed scale per build) |
| **Volume control** | Already exists: ORBITS menu + SPACE! knob | n/a | ✅ stock (undocumented) |
| **Attack time** on the envelope | Engine only has decay; needs DSP change | medium–hard | possible with compiled C in the cave |
| **Bigger wavetable (16 × 16)** | 4× RAM (64 KB), engine index math, NVS layout, upload protocol | hard | probably not worth it |
| **Multiple wavetable banks** | NVS could hold many banks; switching needs a UI gesture | medium | host-side bank library already easy (editor/CLI upload) |
| **Presets / banks** | Snapshot settings to NVS; needs a UI (e.g. button + knob) | medium–hard | feasible |
| **New generators** (FM, analog/chiptune, Infinite Keys) | New DSP code; CPU budget unknown | hard | possible via compiled C, risky |
| **Textures** (multifilter, waveshaper, LO-FI) | New DSP per voice | hard | LO-FI (bit-crush / downsample) is the cheapest |
| **Tape delay** | 1 s mono at 48 kHz/16-bit = 96 KB RAM | hard | maybe a short (≤ 1 s) version; no PSRAM |
| **Reverb types** (Hall/FDN/Shimmer) | New DSP | hard | n/a |
| **USB MIDI / polyphony** | No native USB; serial MIDI via the CH340 + a host bridge | hard | the UART task already parses JSON commands, so it could be extended |
| **USB audio, battery / standalone** | Hardware | impossible | n/a |

## Which CV jack to repurpose for Y?

All 6 CV jacks can be the Y source (`cv_to_y:source=<jack>`). With `exclusive=1` they
stop modulating their own knob:

| Jack | What you give up | Suggestion |
| --- | --- | --- |
| **EFFECTS** | CV over reverb time | **best candidate**: rarely modulated, and the knob still works |
| SPACE! | CV over the macro | good if you don't sequence SPACE! |
| ORBITS | CV over oscillator ↔ resonator mix | expressive, so you'd lose a nice one |
| COLOR | CV filter/drive | usually too useful to lose |
| CLUSTER | CV voice count | useful for builds and swells |
| SHAPE | CV over X | gives "CV scans rows, knob picks column" |

Knobs: there's no free knob in normal mode. In the ORBITS menu, EFFECTS (string
bow/pluck) is a binary switch spread over a whole knob, so half of its travel could
host another parameter.

## Going further: compiled C in the cave

The Xtensa GCC toolchain is installed, so new features don't have to be hand-written
assembly. A C function can be compiled (`-mlongcalls -Os`), linked at a cave address
and called from a hook (`call8 my_func`). This is the path for anything DSP-sized:
quantizer, LO-FI, attack envelope. The main risk is CPU time inside the audio task.
