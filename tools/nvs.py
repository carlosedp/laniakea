"""Minimal ESP-IDF NVS (v2) reader: dump the Laniakea's saved settings from a flash image.

  python tools/nvs.py firmware/backup/laniakea_XXXX.bin      (full 4 MB dump, NVS at 0x1E0000)
  python tools/nvs.py nvs.bin --raw                          (an NVS partition dump)
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

NVS_OFFSET, NVS_SIZE = 0x1E0000, 0x220000
PAGE, ENTRY = 4096, 32
PAGE_ACTIVE, PAGE_FULL = 0xFFFFFFFE, 0xFFFFFFFC
T_U8, T_I8, T_U16, T_I16, T_U32, T_I32, T_U64, T_I64 = 0x01, 0x11, 0x02, 0x12, 0x04, 0x14, 0x08, 0x18
T_STR, T_BLOB, T_BLOB_DATA, T_BLOB_IDX = 0x21, 0x41, 0x42, 0x48


def parse(nvs: bytes):
    """Yield (namespace_index, key, type, value_bytes, seq) for every *written* entry."""
    blobs: dict[tuple, dict] = {}
    namespaces = {0: ""}
    items = []
    for p in range(0, len(nvs), PAGE):
        page = nvs[p:p + PAGE]
        state, seq = struct.unpack_from("<II", page, 0)
        if state not in (PAGE_ACTIVE, PAGE_FULL):
            continue
        bitmap = page[32:64]
        i = 0
        while i < 126:
            st = (bitmap[i // 4] >> ((i % 4) * 2)) & 3
            off = 64 + i * ENTRY
            if st != 2:                      # 2 = written, 3 = empty, 0 = erased
                i += 1
                continue
            ns, typ, span, chunk = page[off], page[off + 1], page[off + 2], page[off + 3]
            key = page[off + 8:off + 24].split(b"\0")[0].decode(errors="replace")
            data = page[off + 24:off + 32]
            if span == 0 or span > 126:
                i += 1
                continue
            if typ in (T_STR, T_BLOB_DATA, T_BLOB):
                size = struct.unpack_from("<H", data, 0)[0]
                payload = page[off + 32:off + 32 + size]
                if typ == T_BLOB_DATA:
                    blobs.setdefault((ns, key), {})[chunk] = (seq, payload)
                else:
                    items.append((ns, key, typ, payload, seq))
            elif typ == T_BLOB_IDX:
                pass
            else:
                items.append((ns, key, typ, data, seq))
                if ns == 0 and typ == T_U8:
                    namespaces[data[0]] = key
            i += span
    for (ns, key), chunks in blobs.items():
        payload = b"".join(c[1] for _, c in sorted(chunks.items()))
        items.append((ns, key, T_BLOB, payload, max(c[0] for c in chunks.values())))
    # newest write of each key wins
    latest = {}
    for ns, key, typ, val, seq in items:
        k = (ns, key)
        if k not in latest or seq >= latest[k][3]:
            latest[k] = (typ, val, namespaces.get(ns, f"ns{ns}"), seq)
    return latest


def describe(typ, val: bytes):
    if typ == T_BLOB and len(val) == 4:
        return f"{struct.unpack('<f', val)[0]:.4f}"
    if typ == T_BLOB:
        return f"<blob {len(val)} bytes>"
    if typ == T_STR:
        return val.rstrip(b"\0").decode(errors="replace")
    fmt = {T_U8: "<B", T_I8: "<b", T_U16: "<H", T_I16: "<h", T_U32: "<I", T_I32: "<i", T_U64: "<Q", T_I64: "<q"}.get(typ)
    return str(struct.unpack_from(fmt, val)[0]) if fmt else val.hex()


def dump(nvs: bytes):
    latest = parse(nvs)
    rows = sorted(((ns, k, describe(t, v)) for (nsi, k), (t, v, ns, _s) in latest.items() if nsi != 0))
    return rows


def main():
    path = Path(sys.argv[1])
    raw = path.read_bytes()
    nvs = raw if "--raw" in sys.argv else raw[NVS_OFFSET:NVS_OFFSET + NVS_SIZE]
    for ns, key, val in dump(nvs):
        print(f"{ns:10s} {key:12s} {val}")


if __name__ == "__main__":
    main()
