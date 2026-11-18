"""xtasm - a small pure-Python Xtensa (ESP32) assembler and disassembler.

Covers the core / FPU / boolean instructions the patches in patches/ use, so patches can be
built without Espressif's GNU toolchain (e.g. in the browser, through Pyodide). Output is
byte-identical to `xtensa-esp32-elf-as` with `.begin no-transform` (no relaxation, no
auto-narrowing); tests/test_xtasm.py checks that against the real toolchain.

    assemble(src, at, defs) -> (bytes, {label: address})
    disasm(data, addr)      -> [(addr, hexbytes, text)]   (objdump-style text; unknown = "?")

Syntax: `label:`, numeric local labels (`1:` / `1f` / `1b`), `/* */` and `#` comments,
`.word`, `.byte`, `.align`, `.global` (ignored), `.begin/.end` (ignored). Operands can be
expressions of numbers and symbols joined by + and -.
"""
from __future__ import annotations

import re


class AsmError(Exception):
    pass


B4CONST = [-1, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 16, 32, 64, 128, 256]
B4CONSTU = [32768, 65536, 2, 3, 4, 5, 6, 7, 8, 10, 12, 16, 32, 64, 128, 256]


def _rrr(op2, op1, r, s, t, op0=0):
    return op2 << 20 | op1 << 16 | r << 12 | s << 8 | t << 4 | op0


# ---------------------------------------------------------------- instruction tables
# RRR "ar, as, at" (op1, op2)
RRR3 = {"and": (0, 1), "or": (0, 2), "xor": (0, 3), "add": (0, 8), "addx2": (0, 9), "addx4": (0, 10),
        "addx8": (0, 11), "sub": (0, 12), "subx2": (0, 13), "subx4": (0, 14), "subx8": (0, 15),
        "mull": (2, 8), "muluh": (2, 10), "mulsh": (2, 11), "quou": (2, 12), "quos": (2, 13),
        "remu": (2, 14), "rems": (2, 15), "min": (3, 4), "max": (3, 5), "minu": (3, 6), "maxu": (3, 7),
        "moveqz": (3, 8), "movnez": (3, 9), "movltz": (3, 10), "movgez": (3, 11)}
FP3 = {"add.s": 0, "sub.s": 1, "mul.s": 2, "madd.s": 4, "msub.s": 5}          # fr, fs, ft  (op1 10)
FP_TOINT = {"round.s": 8, "trunc.s": 9, "floor.s": 10, "ceil.s": 11, "utrunc.s": 14}   # ar, fs, imm
FP_FROMINT = {"float.s": 12, "ufloat.s": 13}                                   # fr, as, imm
FP_CMP = {"un.s": 1, "oeq.s": 2, "ueq.s": 3, "olt.s": 4, "ult.s": 5, "ole.s": 6, "ule.s": 7}  # br, fs, ft (op1 11)
FP_CMOV_A = {"moveqz.s": 8, "movnez.s": 9, "movltz.s": 10, "movgez.s": 11}     # fr, fs, at (op1 11)
FP_CMOV_B = {"movf.s": 12, "movt.s": 13}                                       # fr, fs, bt (op1 11)
INT_CMOV_B = {"movf": 12, "movt": 13}                                          # ar, as, bt (op1 3)
LS = {"l8ui": (0, 1), "l16ui": (1, 2), "l32i": (2, 4), "s8i": (4, 1), "s16i": (5, 2), "s32i": (6, 4),
      "l16si": (9, 2), "addi": (12, 1), "addmi": (13, 256)}                    # r, scale
BR_RR = {"bnone": 0, "beq": 1, "blt": 2, "bltu": 3, "ball": 4, "bbc": 5, "bany": 8, "bne": 9,
         "bge": 10, "bgeu": 11, "bnall": 12, "bbs": 13}
BR_IMM = {"beqi": (2, 0), "bnei": (2, 1), "blti": (2, 2), "bgei": (2, 3), "bltui": (3, 2), "bgeui": (3, 3)}
BR_Z = {"beqz": 0, "bnez": 1, "bltz": 2, "bgez": 3}
FIXED = {"nop": 0x0020F0, "_nop": 0x0020F0, "memw": 0x0020C0, "ret": 0x000080, "retw": 0x000090}
FIXED_N = {"nop.n": 0xF03D, "_nop.n": 0xF03D, "ret.n": 0xF00D, "retw.n": 0xF01D}


def _size(mn: str) -> int:
    return 2 if mn.endswith(".n") else 3


# ---------------------------------------------------------------- source parsing
def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), src, flags=re.S)
    return "\n".join(l.split("#")[0] for l in src.splitlines())


def _split_ops(s: str) -> list[str]:
    return [o.strip() for o in s.split(",")] if s.strip() else []


class _Ctx:
    def __init__(self, symbols, locals_, index):
        self.symbols, self.locals, self.index = symbols, locals_, index

    def value(self, expr: str, required=True):
        expr = expr.replace(" ", "")
        if not expr:
            raise AsmError("missing operand")
        total, pos = 0, 0
        for m in re.finditer(r"([+-]?)([^+-]+)", expr):
            if m.start() != pos:
                raise AsmError(f"bad expression {expr!r}")
            pos = m.end()
            sign = -1 if m.group(1) == "-" else 1
            tok = m.group(2)
            if re.fullmatch(r"0[xX][0-9a-fA-F]+|\d+", tok):
                v = int(tok, 0)
            elif re.fullmatch(r"\d+[fb]", tok):
                v = self._local(tok)
            elif tok in self.symbols:
                v = self.symbols[tok]
            elif not required:
                return None
            else:
                raise AsmError(f"undefined symbol {tok!r}")
            if v is None:
                return None
            total += sign * v
        if pos != len(expr):
            raise AsmError(f"bad expression {expr!r}")
        return total

    def _local(self, tok):
        n, d = tok[:-1], tok[-1]
        defs = self.locals.get(n, [])
        if d == "f":
            nxt = [a for i, a in defs if i >= self.index]
            return nxt[0] if nxt else None
        prv = [a for i, a in defs if i < self.index]
        return prv[-1] if prv else None


def _reg(op: str, kind: str) -> int:
    m = re.fullmatch(kind + r"(\d+)", op.strip())
    if not m or int(m.group(1)) > 15:
        raise AsmError(f"expected an {kind} register, got {op!r}")
    return int(m.group(1))


def _imm(v, lo, hi, what="immediate"):
    if not lo <= v <= hi:
        raise AsmError(f"{what} {v} out of range {lo}..{hi}")
    return v


def _encode(mn: str, ops: list[str], pc: int, ctx: _Ctx) -> int:
    A = lambda i: _reg(ops[i], "a")
    F = lambda i: _reg(ops[i], "f")
    Bb = lambda i: _reg(ops[i], "b")
    V = lambda i: ctx.value(ops[i])

    def need(n):
        if len(ops) != n:
            raise AsmError(f"{mn} takes {n} operands")

    if mn in FIXED:
        need(0); return FIXED[mn]
    if mn in FIXED_N:
        need(0); return FIXED_N[mn]
    if mn in RRR3:
        need(3); op1, op2 = RRR3[mn]; return _rrr(op2, op1, A(0), A(1), A(2))
    if mn == "mov":
        need(2); return _rrr(2, 0, A(0), A(1), A(1))
    if mn in ("neg", "abs"):
        need(2); return _rrr(6, 0, A(0), 0 if mn == "neg" else 1, A(1))
    if mn in FP3:
        need(3); return _rrr(FP3[mn], 10, F(0), F(1), F(2))
    if mn in FP_TOINT:
        need(3); return _rrr(FP_TOINT[mn], 10, A(0), F(1), _imm(V(2), 0, 15))
    if mn in FP_FROMINT:
        need(3); return _rrr(FP_FROMINT[mn], 10, F(0), A(1), _imm(V(2), 0, 15))
    if mn in ("mov.s", "abs.s", "neg.s"):
        need(2); return _rrr(15, 10, F(0), F(1), {"mov.s": 0, "abs.s": 1, "neg.s": 6}[mn])
    if mn == "rfr":
        need(2); return _rrr(15, 10, A(0), F(1), 4)
    if mn == "wfr":
        need(2); return _rrr(15, 10, F(0), A(1), 5)
    if mn in FP_CMP:
        need(3); return _rrr(FP_CMP[mn], 11, Bb(0), F(1), F(2))
    if mn in FP_CMOV_A:
        need(3); return _rrr(FP_CMOV_A[mn], 11, F(0), F(1), A(2))
    if mn in FP_CMOV_B:
        need(3); return _rrr(FP_CMOV_B[mn], 11, F(0), F(1), Bb(2))
    if mn in INT_CMOV_B:
        need(3); return _rrr(INT_CMOV_B[mn], 3, A(0), A(1), Bb(2))
    if mn == "slli":
        need(3); sh = 32 - _imm(V(2), 1, 31, "shift"); return _rrr(sh >> 4, 1, A(0), A(1), sh & 15)
    if mn == "srli":
        need(3); return _rrr(4, 1, A(0), _imm(V(2), 0, 15, "shift"), A(1))
    if mn == "srai":
        need(3); sa = _imm(V(2), 0, 31, "shift"); return _rrr(2 | sa >> 4, 1, A(0), sa & 15, A(1))
    if mn == "extui":
        need(4); sh = _imm(V(2), 0, 31, "shift"); mk = _imm(V(3), 1, 16, "mask width")
        return _rrr(mk - 1, 4 | sh >> 4, A(0), sh & 15, A(1))
    if mn in LS:
        need(3); r, sc = LS[mn]; v = V(2)
        if v % sc:
            raise AsmError(f"{mn} offset {v} not a multiple of {sc}")
        v //= sc
        _imm(v, -128, 127, f"{mn} offset") if mn in ("addi", "addmi") else _imm(v, 0, 255, f"{mn} offset")
        return (v & 0xFF) << 16 | r << 12 | A(1) << 8 | A(0) << 4 | 2
    if mn in ("lsi", "ssi"):
        need(3); v = V(2)
        if v % 4:
            raise AsmError(f"{mn} offset {v} not a multiple of 4")
        return _imm(v // 4, 0, 255, f"{mn} offset") << 16 | (0 if mn == "lsi" else 4) << 12 | A(1) << 8 | F(0) << 4 | 3
    if mn == "movi":
        need(2); v = _imm(V(1), -2048, 2047, "movi immediate")
        return (v & 0xFF) << 16 | 10 << 12 | ((v >> 8) & 15) << 8 | A(0) << 4 | 2
    if mn == "movi.n":
        need(2); v = _imm(V(1), -32, 95, "movi.n immediate") & 0x7F
        return (v & 15) << 12 | A(0) << 8 | (v >> 4) << 4 | 12
    if mn == "mov.n":
        need(2); return A(1) << 8 | A(0) << 4 | 13
    if mn == "l32r":
        need(2); tgt = V(1); base = (pc + 3) & ~3
        off = tgt - base
        if off % 4 or not -(1 << 18) <= off < 0:
            raise AsmError(f"l32r target {tgt:#x} out of range from {pc:#x} (literal must be before the code)")
        return ((off >> 2) & 0xFFFF) << 8 | A(0) << 4 | 1
    if mn == "j":
        need(1); off = _imm(V(0) - (pc + 4), -(1 << 17), (1 << 17) - 1, "jump offset")
        return (off & 0x3FFFF) << 6 | 6
    if mn in ("call0", "call4", "call8", "call12"):
        need(1); n = int(mn[4:]) // 4; tgt = V(0)
        if tgt % 4:
            raise AsmError(f"call target {tgt:#x} not 4-byte aligned")
        off = _imm((tgt - ((pc & ~3) + 4)) >> 2, -(1 << 17), (1 << 17) - 1, "call offset")
        return (off & 0x3FFFF) << 6 | n << 4 | 5
    if mn in ("callx0", "callx4", "callx8", "callx12"):
        need(1); n = int(mn[5:]) // 4; return _rrr(0, 0, 0, A(0), 12 | n)
    if mn == "jx":
        need(1); return _rrr(0, 0, 0, A(0), 10)
    if mn == "entry":
        need(2); v = V(1)
        if v % 8:
            raise AsmError("entry frame size must be a multiple of 8")
        return _imm(v // 8, 0, 4095, "entry size") << 12 | A(0) << 8 | 3 << 4 | 6
    if mn in BR_RR:
        need(3); off = _imm(V(2) - (pc + 4), -128, 127, "branch offset")
        return (off & 0xFF) << 16 | BR_RR[mn] << 12 | A(0) << 8 | A(1) << 4 | 7
    if mn in ("bbci", "bbsi"):
        need(3); bit = _imm(V(1), 0, 31, "bit"); off = _imm(V(2) - (pc + 4), -128, 127, "branch offset")
        return (off & 0xFF) << 16 | ((6 if mn == "bbci" else 14) | bit >> 4) << 12 | A(0) << 8 | (bit & 15) << 4 | 7
    if mn in BR_IMM:
        need(3); n, m = BR_IMM[mn]; table = B4CONSTU if n == 3 else B4CONST
        c = V(1)
        if c not in table:
            raise AsmError(f"{mn}: constant {c} not encodable (allowed: {table})")
        off = _imm(V(2) - (pc + 4), -128, 127, "branch offset")
        return (off & 0xFF) << 16 | table.index(c) << 12 | A(0) << 8 | m << 6 | n << 4 | 6
    if mn in BR_Z:
        need(2); off = _imm(V(1) - (pc + 4), -2048, 2047, "branch offset")
        return (off & 0xFFF) << 12 | A(0) << 8 | BR_Z[mn] << 6 | 1 << 4 | 6
    if mn in ("bf", "bt"):
        need(2); off = _imm(V(1) - (pc + 4), -128, 127, "branch offset")
        return (off & 0xFF) << 16 | (0 if mn == "bf" else 1) << 12 | Bb(0) << 8 | 1 << 6 | 3 << 4 | 6
    raise AsmError(f"unsupported instruction {mn!r} (tools/xtasm.py)")


def assemble(src: str, at: int, defs: dict[str, int] | None = None) -> tuple[bytes, dict[str, int]]:
    """Assemble `src` placed at absolute address `at`."""
    stmts = []          # (kind, label/mnemonic, operands, lineno)
    for no, line in enumerate(_strip_comments(src).splitlines(), 1):
        line = line.strip()
        while True:
            m = re.match(r"([A-Za-z_.$][\w.$]*|\d+):\s*", line)
            if not m:
                break
            stmts.append(("label", m.group(1), None, no))
            line = line[m.end():]
        for part in filter(None, (p.strip() for p in line.split(";"))):
            mn, rest = re.match(r"(\S+)\s*(.*)", part).groups()
            stmts.append(("op", mn.lower(), rest.strip(), no))

    def layout(symbols, locals_, final):
        pc, out, labels, loc = at, bytearray(), {}, {}
        for i, (kind, name, rest, no) in enumerate(stmts):
            try:
                if kind == "label":
                    if name.isdigit():
                        loc.setdefault(name, []).append((i, pc))
                    elif name in labels:
                        raise AsmError(f"label {name!r} defined twice")
                    else:
                        labels[name] = pc
                    continue
                ctx = _Ctx({**symbols, **labels} if final else symbols, locals_, i)
                if name in (".global", ".globl", ".begin", ".end", ".section", ".text", ".literal_position"):
                    continue
                if name == ".align":
                    n = ctx.value(rest)
                    pad = -(pc - 0) % n
                    out += b"\0" * pad
                    pc += pad
                elif name in (".word", ".long", ".4byte", ".byte"):
                    size = 1 if name == ".byte" else 4
                    for op in _split_ops(rest):
                        v = ctx.value(op) if final else 0
                        out += (v & ((1 << 8 * size) - 1)).to_bytes(size, "little")
                        pc += size
                elif name.startswith("."):
                    raise AsmError(f"unsupported directive {name}")
                else:
                    size = _size(name)
                    word = _encode(name, _split_ops(rest), pc, ctx) if final else 0
                    out += word.to_bytes(size, "little")
                    pc += size
            except AsmError as e:
                raise AsmError(f"line {no}: {e}") from None
        return bytes(out), labels, loc

    base = dict(defs or {})
    _, labels, loc = layout(base, {}, final=False)          # sizes don't depend on values
    code, labels, _ = layout({**base, **labels}, loc, final=True)
    return code, {**base, **labels}


# ---------------------------------------------------------------- disassembler
def _num(v: int) -> str:
    return str(v) if -256 < v < 256 else f"0x{v & 0xFFFFFFFF:x}"


def _sext(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


def _inv(d):
    return {v: k for k, v in d.items()}


_RRR3_INV = _inv(RRR3)
_FP3_INV, _TOINT_INV, _FROMINT_INV = _inv(FP3), _inv(FP_TOINT), _inv(FP_FROMINT)
_CMP_INV, _CMOVA_INV, _CMOVB_INV, _ICMOVB_INV = _inv(FP_CMP), _inv(FP_CMOV_A), _inv(FP_CMOV_B), _inv(INT_CMOV_B)
_LS_INV = {r: (k, sc) for k, (r, sc) in LS.items()}
_BRRR_INV, _BRZ_INV = _inv(BR_RR), _inv(BR_Z)
_BRIMM_INV = _inv(BR_IMM)


def _decode(w: int, pc: int, size: int) -> str:
    op0, t, s, r = w & 15, (w >> 4) & 15, (w >> 8) & 15, (w >> 12) & 15
    if size == 2:
        if w in _inv(FIXED_N):
            return {0xF03D: "nop.n", 0xF00D: "ret.n", 0xF01D: "retw.n"}[w]
        if op0 == 12 and not t & 8:
            imm = (t & 7) << 4 | r
            return f"movi.n\ta{s}, {imm - 128 if imm >= 96 else imm}"
        if op0 == 12:
            return f"{'beqz.n' if not t & 4 else 'bnez.n'}\ta{s}, 0x{pc + 4 + ((t & 3) << 4 | r):x}"
        if op0 == 13 and r == 0:
            return f"mov.n\ta{t}, a{s}"
        if op0 in (8, 9):
            return f"{'l32i.n' if op0 == 8 else 's32i.n'}\ta{t}, a{s}, {r * 4}"
        if op0 == 10:
            return f"add.n\ta{r}, a{s}, a{t}"
        if op0 == 11:
            return f"addi.n\ta{r}, a{s}, {t or -1}"
        return "?"
    op1, op2, imm8 = (w >> 16) & 15, (w >> 20) & 15, (w >> 16) & 0xFF
    if op0 == 0:
        if w in (0x0020F0,):
            return "nop"
        if w == 0x0020C0:
            return "memw"
        if op1 == 0 and op2 == 0 and r == 0:
            if t == 8 and s == 0:
                return "ret"
            if t == 9 and s == 0:
                return "retw"
            if t == 10:
                return f"jx\ta{s}"
            if t >= 12:
                return f"callx{(t & 3) * 4}\ta{s}"
            return "?"
        if op1 == 0 and op2 == 6 and s in (0, 1):
            return f"{'neg' if s == 0 else 'abs'}\ta{r}, a{t}"
        if op1 == 0 and op2 == 2 and s == t:
            return f"or\ta{r}, a{s}, a{t}"
        if (op1, op2) in _RRR3_INV:
            return f"{_RRR3_INV[(op1, op2)]}\ta{r}, a{s}, a{t}"
        if op1 == 1:
            if op2 in (0, 1):
                return f"slli\ta{r}, a{s}, {32 - (op2 << 4 | t)}"
            if op2 in (2, 3):
                return f"srai\ta{r}, a{t}, {(op2 & 1) << 4 | s}"
            if op2 == 4:
                return f"srli\ta{r}, a{t}, {s}"
            return "?"
        if op1 in (4, 5):
            return f"extui\ta{r}, a{t}, {(op1 & 1) << 4 | s}, {op2 + 1}"
        if op1 == 3 and op2 in _ICMOVB_INV:
            return f"{_ICMOVB_INV[op2]}\ta{r}, a{s}, b{t}"
        if op1 == 10:
            if op2 in _FP3_INV:
                return f"{_FP3_INV[op2]}\tf{r}, f{s}, f{t}"
            if op2 in _TOINT_INV:
                return f"{_TOINT_INV[op2]}\ta{r}, f{s}, {t}"
            if op2 in _FROMINT_INV:
                return f"{_FROMINT_INV[op2]}\tf{r}, a{s}, {t}"
            if op2 == 15:
                return {0: f"mov.s\tf{r}, f{s}", 1: f"abs.s\tf{r}, f{s}", 4: f"rfr\ta{r}, f{s}",
                        5: f"wfr\tf{r}, a{s}", 6: f"neg.s\tf{r}, f{s}"}.get(t, "?")
            return "?"
        if op1 == 11:
            if op2 in _CMP_INV:
                return f"{_CMP_INV[op2]}\tb{r}, f{s}, f{t}"
            if op2 in _CMOVA_INV:
                return f"{_CMOVA_INV[op2]}\tf{r}, f{s}, a{t}"
            if op2 in _CMOVB_INV:
                return f"{_CMOVB_INV[op2]}\tf{r}, f{s}, b{t}"
        return "?"
    if op0 == 1:
        return f"l32r\ta{t}, 0x{((pc + 3) & ~3) + ((w >> 8 | 0xFFFF0000) - (1 << 32)) * 4:x}"
    if op0 == 2:
        if r == 10:
            return f"movi\ta{t}, {_num(_sext(s << 8 | imm8, 12))}"
        if r in _LS_INV:
            name, sc = _LS_INV[r]
            v = _sext(imm8, 8) * sc if name in ("addi", "addmi") else imm8 * sc
            return f"{name}\ta{t}, a{s}, {_num(v)}"
        return "?"
    if op0 == 3:
        if r in (0, 4):
            return f"{'lsi' if r == 0 else 'ssi'}\tf{t}, a{s}, {_num(imm8 * 4)}"
        return "?"
    n, m = t & 3, t >> 2
    if op0 == 5:
        off = _sext(w >> 6, 18)
        return f"call{n * 4}\t0x{(pc & ~3) + (off << 2) + 4:x}"
    if op0 == 6:
        if n == 0:
            return f"j\t0x{pc + 4 + _sext(w >> 6, 18):x}"
        if n == 1:
            return f"{_BRZ_INV[m]}\ta{s}, 0x{pc + 4 + _sext(w >> 12, 12):x}"
        tgt = f"0x{pc + 4 + _sext(imm8, 8):x}"
        if n == 2 or m >= 2:
            name = _BRIMM_INV[(n, m)]
            c = (B4CONSTU if n == 3 else B4CONST)[r]
            return f"{name}\ta{s}, {_num(c)}, {tgt}"
        if m == 0:
            return f"entry\ta{s}, {_num((w >> 12) * 8)}"
        if m == 1:
            if r in (0, 1):
                return f"{'bf' if r == 0 else 'bt'}\tb{s}, {tgt}"
            if r in (8, 9, 10):
                return f"{['loop', 'loopnez', 'loopgtz'][r - 8]}\ta{s}, 0x{pc + 4 + imm8:x}"   # unsigned
        return "?"
    if op0 == 7:
        tgt = f"0x{pc + 4 + _sext(imm8, 8):x}"
        if r in (6, 7, 14, 15):
            return f"{'bbci' if r < 8 else 'bbsi'}\ta{s}, {(r & 1) << 4 | t}, {tgt}"
        return f"{_BRRR_INV[r]}\ta{s}, a{t}, {tgt}"
    return "?"


def insn_size(b0: int) -> int:
    op0 = b0 & 15
    return 3 if op0 < 8 else 2 if op0 < 14 else 1


def disasm(data: bytes, addr: int) -> list[tuple[int, str, str]]:
    """Linear-sweep disassembly. Lengths are exact; text is objdump-style for the supported
    instructions and "?" otherwise (op0 14/15 bytes come out as `.byte`)."""
    res, i = [], 0
    while i < len(data):
        n = insn_size(data[i])
        if n == 1 or i + n > len(data):
            res.append((addr + i, f"{data[i]:02x}", f".byte\t0x{data[i]:02x}"))
            i += 1
            continue
        chunk = data[i:i + n]
        res.append((addr + i, chunk.hex(), _decode(int.from_bytes(chunk, "little"), addr + i, n)))
        i += n
    return res
