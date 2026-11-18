"""Bank backup file round trip (tools/laniakea.py save_banks_json / load_banks_json)."""
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import laniakea as L  # noqa: E402

d = Path(tempfile.mkdtemp())
w = (np.arange(64 * 128).reshape(64, 128) % 30000 - 15000).astype(np.int16)
L.save_banks_json(d / "b.json", {1: {"name": "A", "waves": w}, 3: {"name": "F", "factory": True}}, 128, "test")
jobs = L.load_banks_json(d / "b.json")
assert [n for n, _w, _name in jobs] == [1, 3]
assert np.array_equal(np.array(jobs[0][1]), w), "128-sample data must round-trip exactly"
assert jobs[1][1] is None and jobs[1][2] == "F", "factory banks have no data"
# 256-sample (editor export) data is resampled to the module's 128
sine = np.round(np.sin(2 * np.pi * np.arange(256) / 256) * 30000).astype(np.int16)
L.save_banks_json(d / "c.json", {2: {"name": "S", "waves": np.tile(sine, (64, 1))}}, 256, "editor")
(n, x, _), = L.load_banks_json(d / "c.json")
x = np.array(x)
assert n == 2 and x.shape == (64, 128)
assert abs(x[0, 32] - 30000) < 300 and abs(x[0, 96] + 30000) < 300
print("bank backup file tests: OK")
