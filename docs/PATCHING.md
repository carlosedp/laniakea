# Writing your own firmware patches

There's no source code, so features are added by **patching the compiled binary**.
The tools take care of the error-prone parts: the assembler, the code cave,
checksums and SHA-256. You write a short Python file plus a few lines of Xtensa assembly.

## How a patch works

```text
 original code                          code cave (appended to .flash.text)
 ─────────────                          ───────────────────────────────────
 0x400e3115  beqi a4, 1, …              0x400fb980  lit_thr:  .word 0.95
 0x400e3118  j    0x400fb990  ──────►   0x400fb984  lit_max:  .word 7/9
 0x400e311b  j    0x400e3127  ◄──┐      …           lit_cv / lit_gain
   (was: lsi f1, a6, 0x44)       │      0x400fb990  lsi   f1, a6, 0x44   ← {orig}
                                 │                  … your instructions …
                                 └───────────────── j     0x400e311b
```

1. **Hook**: one instruction of 3 bytes or more is overwritten with `j trampoline`.
2. **Trampoline**: your code runs in the cave. Use `{orig}` to run the overwritten instruction where you want it. The trampoline then jumps back to the next original instruction.
3. **Literals**: Xtensa loads 32-bit constants with `l32r` from a pool that must sit *before* the code. `literals={...}` builds that pool for you, and you refer to entries as `lit_<name>`.
4. **Save**: the cave is appended to the `.flash.text` segment (just past its old end, still within `j` range of the whole function), and the segment length, image checksum and SHA-256 are recomputed. The bootloader rejects an image whose hash doesn't match.

Other operations:
- `fw.replace(addr, "asm", expect=...)` swaps one instruction for another of the same size. Example: `mov.s f8, f2` instead of `add.s f8, f2, f1` drops a CV from a knob.
- `fw.write_floats(addr, [...])` overwrites tables in flash, such as the chord table.
- `fw.nop(addr, expect=...)` removes instructions.

Every write takes `expect=<original bytes>`, so a patch refuses to apply to the wrong firmware or on top of a conflicting patch.

## Commands

The examples use Windows syntax. On Linux/macOS use `.venv/bin/python` instead of
`.venv\Scripts\python.exe` and `./laniakea.sh` instead of `.\laniakea`; everything else is the same.

```powershell
.\laniakea patcher list                                      # patches and options
.\laniakea patcher build cv_to_y:source=effects chords:set=pro
.\laniakea patcher disasm 0x400e3118 --before 6 --bytes 16   # look at code (shows the enclosing function)
.\laniakea patcher find tabla                                # string -> functions that use it
.\laniakea patcher verify firmware\custom\<file>.bin
.\laniakea flash firmware\custom\<file>.bin    # backup first!
```

## Writing a patch: walkthrough

Copy [patches/_template.py](../patches/_template.py) to `patches/my_patch.py`:

```python
DESCRIPTION = "What it does"
OPTIONS = {"amount": (0.5, "help text")}     # default value's type = parser type
TARGETS = ["3.6", "3.7"]

def apply(fw, amount):
    addr, orig, _ = fw.sym["cv_add"]["shape"]          # add.s f6, f6, f5
    fw.hook(addr, expect=orig, literals={"amount": float(amount)}, body="""
    l32r    a8, lit_amount
    wfr     f7, a8
    madd.s  f6, f5, f7          /* f6 = knob + CV * amount */
""")
    fw.tag("myfeature")
```

### 1. Find the code
- [docs/RE-NOTES.md](RE-NOTES.md): the important functions, globals and the knob/CV table.
- `re/ghidra/v3.6/decompiled.c`: C-like decompiled code for all 1,363 functions.
- `laniakea patcher find <text>`: log strings and NVS keys lead you to their functions.
- `scripts\ghidra_gui.ps1`: open the project in Ghidra, follow cross-references, rename things.

### 2. Pick a hook point
- It must be **≥ 3 bytes** and cover whole instructions; extend `expect` over 2 instructions if needed.
- If you use `{orig}`, the overwritten instructions must not be PC-relative (`l32r`, `j`, `call*`, branches). The tool refuses those.
- Nothing may branch *into* the middle of the overwritten bytes. Hooking a single 3-byte instruction is the safe default.
- Only hook **flash code** (`0x400D0000` and up). The cave is in flash, and code in IRAM (`0x4008xxxx`) can run while the flash cache is off (during settings saves), so a jump from there into the cave would crash. `fw.hook` refuses such addresses.
- Constants loaded with `l32r` often come from a **shared literal pool**: don't change the pool value (other code uses it). Redirect that one load instead, as `patches/usability.py` does.

### 3. Pick scratch registers
A register is free if, after the hook point, it is **written before it is read** on every path.
Check with `laniakea patcher disasm ADDR --bytes 200`. In the routines patched so far, `a8`, `f0`, `f2` and `f7` are free (noted in `tools/symbols.py`). Windowed-ABI note: don't touch `a0`/`a1` (return address and stack pointer).

### 4. Useful Xtensa (ESP32 FPU) instructions

| | |
| --- | --- |
| `l32r aN, lit_x` | load a literal (address or float bits) |
| `lsi fN, aM, off` / `ssi` | load/store float at `aM + off` |
| `l32i` / `s32i` | load/store 32-bit int |
| `wfr fN, aM` / `rfr aM, fN` | move int bits ↔ float register |
| `add.s` `sub.s` `mul.s` `madd.s fr, fs, ft` (fr += fs·ft) `msub.s` | float math |
| `olt.s bN, fa, fb` / `ole.s` / `oeq.s` | float compare into boolean register |
| `movt.s fr, fs, bN` / `movf.s` | conditional move (clamping without branches) |
| `bt bN, label` / `bf` | branch on boolean |
| `trunc.s aN, fM, 0` / `float.s fM, aN, 0` | float ↔ int |
| `beqi` `bnei` `blti` `bgei` `beqz` `bnez` | integer branches |

The [Xtensa ISA reference](https://www.cadence.com/content/dam/cadence-www/global/en_US/documents/tools/silicon-solutions/compute-ip/isa-summary.pdf) has the full instruction list.

### 5. Test safely
1. `.\laniakea backup` (once), then `laniakea patcher build …` and `.\laniakea flash <file>`.
2. Check the boot log: `.\laniakea monitor --reset`. A crash prints `Guru Meditation Error` with a PC address; disassemble around it.
3. Something wrong? `.\laniakea flash v3.7` (keeps your calibration) or `.\laniakea restore <backup> --yes`.

The ESP32 ROM bootloader can't be overwritten, so a bad patch can always be reflashed over USB.

## Porting to a new Magerit firmware
Addresses are only valid for the exact image in `tools/symbols.py` (keyed by sha256).
For a new release:
1. `.\laniakea fetch`
2. `scripts\ghidra_analyze.ps1 -Version vX.Y`
3. Find the same instructions (the strings and NVS keys rarely change).
4. Add a new entry to `symbols.py`.
