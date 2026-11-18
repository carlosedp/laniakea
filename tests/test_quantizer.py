"""Mirror of the quantizer trampoline (patches/quantizer.py) to check the musical logic.
Run: .venv/Scripts/python.exe tests/test_quantizer.py   (or .venv/bin/python)"""
import importlib.util
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("q", ROOT / "patches" / "quantizer.py")
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)


def quantize(p, scale, root, last, hyst=0.12):
    """Same steps as the Xtensa code: bias towards last, split octave/semitone, table lookup."""
    table = q.nearest_table(q.LIBRARY[scale])
    d = max(-hyst, min(hyst, last - p))
    rel = p + d - root
    octave = math.floor(rel / 12)
    semi = rel - 12 * octave
    n = max(0, min(12, round(semi)))
    return root + 12 * octave + table[n]


def check(p, scale, root, expect, last=None):
    got = quantize(p, scale, root, p if last is None else last)
    assert got == expect, f"{scale} root {root}: {p} -> {got}, expected {expect}"


# C major (root 0): C#+0.3 -> C (tie goes down), D#+0.6 -> E, B+0.4 stays B, B+0.6 -> next C
check(61.3, "major", 0, 60)
check(63.6, "major", 0, 64)
check(71.4, "major", 0, 71)
check(71.6, "major", 0, 72)
# negative / low pitches wrap octaves correctly
check(-5.0, "major", 0, -5)
check(-4.6, "minor_pentatonic", 0, -5)
# other keys: A minor pentatonic (root 9): 70 (A#) -> 69 (A)
check(70.0, "minor_pentatonic", 9, 69)
# chromatic = nearest semitone
check(64.49, "chromatic", 0, 64)
check(64.51, "chromatic", 0, 65)
# hysteresis: just past the boundary, the previous note is kept
check(64.55, "chromatic", 0, 64, last=64)
check(64.70, "chromatic", 0, 65, last=64)
# every table maps 0..12 onto scale degrees (or 12 = next root)
for name, deg in q.LIBRARY.items():
    t = q.nearest_table(deg)
    assert len(t) == 13 and all(x in deg or x == 12 for x in t), name
print("quantizer logic tests: OK")
sys.exit(0)
