"""Replace the 16 chords selected by CLUSTER in the ORBITS menu.

The firmware keeps a table of 16 chords x 8 voice frequency ratios in flash. CLUSTER
(right of 12 o'clock) adds voices in order 1..8, so put the most important notes first.

set=pro    the Laniakea Pro's 11 default chords + sus2, sus4, add9, min9, maj6
set=stock  unchanged (useful to test the tooling)
set=FILE   a text file with up to 16 lines, e.g.
               major: 0 4 7
               my voicing: 0 -0.12 7 12 16 19 24 31     <- exactly 8 numbers = used verbatim
           Numbers are semitones above the root (fractions allowed for detune).
           Shorter lists are expanded the way Magerit voices its chords:
           root, detuned root, other tones, octave, tones + 12, two octaves.
"""
from pathlib import Path

DESCRIPTION = "Custom chord table (16 chords x 8 voices) for the ORBITS-menu CLUSTER"
OPTIONS = {"set": ("pro", "pro | stock | path to a chord text file")}
TARGETS = ["3.6", "3.7"]

DETUNE = -0.12  # semitones; Magerit thickens chords with a slightly flat doubled root

PRO = [
    ("unison", None), ("octaves", None), ("fifths", None),          # keep Magerit's voicings
    ("fourths", [0, 5]), ("major", [0, 4, 7]), ("dom7", [0, 4, 7, 10]), ("maj7", [0, 4, 7, 11]),
    ("augmented", [0, 4, 8]), ("minor", [0, 3, 7]), ("min7", [0, 3, 7, 10]), ("diminished", [0, 3, 6]),
    ("sus2", [0, 2, 7]), ("sus4", [0, 5, 7]), ("add9", [0, 4, 7, 14]), ("min9", [0, 3, 7, 10, 14]),
    ("maj6", [0, 4, 7, 9]),
]


def voices(tones):
    """Stack chord tones over octaves, lowest first (CLUSTER adds voices in this order).
    Thin chords (<= 3 tones) get a slightly flat doubled root, like Magerit's stock voicings
    (this rule reproduces the stock fifths / triad / 7th rows exactly)."""
    if len(tones) == 8:
        return list(tones)
    t = sorted(set(tones))
    stack = sorted({x + 12 * k for x in t for k in range(4)})
    if len(t) <= 3:
        stack = [0, DETUNE] + [s for s in stack if s != 0]
    v = stack[:8]
    base = list(v)
    i = 0
    while len(v) < 8:              # few distinct notes (e.g. octaves): double them, slightly detuned
        v.append(base[1 + i % (len(base) - 1)] + 0.05 * (1 + i // (len(base) - 1)))
        i += 1
    return v


def parse_file(path):
    chords = []
    for line in Path(path).read_text().splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        name, _, nums = line.rpartition(":")
        chords.append((name.strip() or f"chord{len(chords) + 1}", [float(x) for x in nums.split()]))
    if not 1 <= len(chords) <= 16:
        raise ValueError("chord file needs 1..16 lines")
    return chords


def apply(fw, set):
    addr = fw.sym["chord_table"]
    stock = [list(__import__("struct").unpack("<8f", fw.read(addr + 32 * i, 32))) for i in range(16)]
    if set == "stock":
        chords = [(f"stock{i}", None) for i in range(16)]
    elif set == "pro":
        chords = PRO
    else:
        chords = parse_file(set)
    table = []
    for i in range(16):
        name, tones = chords[i] if i < len(chords) else chords[-1]
        table.append(stock[i] if tones is None else [2 ** (s / 12) for s in voices(tones)])
    fw.write_floats(addr, [r for row in table for r in row], expect_len=128)
    fw.tag(f"chords-{Path(set).stem if set not in ('pro', 'stock') else set}")
    return [n for n, _ in chords[:16]]
