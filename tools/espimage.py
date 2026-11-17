"""Minimal ESP32 firmware image helpers (merged-bin aware).

An ESP-IDF app image is:  24-byte header | N x (8-byte seg header + data) |
padding so (len+1) % 16 == 0 | 1-byte XOR checksum | optional 32-byte SHA-256.
The bootloader validates both checksum and SHA-256 on every boot, so any
binary patch must call `fix_image()` afterwards.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field

IMAGE_MAGIC = 0xE9
CHECKSUM_SEED = 0xEF
CHIP_IDS = {0: "esp32", 2: "esp32s2", 5: "esp32c3", 9: "esp32s3"}

APP_OFFSET = 0x10000          # factory app in Magerit partition tables
PARTITION_TABLE_OFFSET = 0x8000


@dataclass
class Segment:
    load_addr: int
    file_offset: int          # absolute offset of segment *data* in the buffer
    length: int


@dataclass
class Image:
    offset: int
    chip: str
    entry: int
    segments: list[Segment] = field(default_factory=list)
    checksum_offset: int = 0
    hash_offset: int | None = None
    end: int = 0

    def addr_to_offset(self, addr: int) -> int | None:
        for s in self.segments:
            if s.load_addr <= addr < s.load_addr + s.length:
                return s.file_offset + (addr - s.load_addr)
        return None

    def offset_to_addr(self, off: int) -> int | None:
        for s in self.segments:
            if s.file_offset <= off < s.file_offset + s.length:
                return s.load_addr + (off - s.file_offset)
        return None


def parse_image(buf: bytes | bytearray, offset: int) -> Image:
    magic, nseg, _mode, _sf, entry = struct.unpack_from("<BBBBI", buf, offset)
    if magic != IMAGE_MAGIC:
        raise ValueError(f"no ESP image at {offset:#x}")
    chip_id, = struct.unpack_from("<H", buf, offset + 12)
    hash_appended = buf[offset + 23] == 1
    img = Image(offset, CHIP_IDS.get(chip_id, f"chip{chip_id}"), entry)
    p = offset + 24
    for _ in range(nseg):
        addr, ln = struct.unpack_from("<II", buf, p)
        img.segments.append(Segment(addr, p + 8, ln))
        p += 8 + ln
    p += (15 - ((p - offset) % 16))  # pad so checksum lands on 16-byte boundary - 1
    img.checksum_offset = p
    p += 1
    if hash_appended:
        img.hash_offset = p
        p += 32
    img.end = p
    return img


def compute_checksum(buf, img: Image) -> int:
    c = CHECKSUM_SEED
    for s in img.segments:
        for b in buf[s.file_offset:s.file_offset + s.length]:
            c ^= b
    return c


def verify_image(buf, img: Image) -> tuple[bool, bool]:
    """Return (checksum_ok, sha256_ok)."""
    cs_ok = buf[img.checksum_offset] == compute_checksum(buf, img)
    sha_ok = True
    if img.hash_offset is not None:
        h = hashlib.sha256(buf[img.offset:img.hash_offset]).digest()
        sha_ok = bytes(buf[img.hash_offset:img.hash_offset + 32]) == h
    return cs_ok, sha_ok


def fix_image(buf: bytearray, img: Image) -> None:
    buf[img.checksum_offset] = compute_checksum(buf, img)
    if img.hash_offset is not None:
        buf[img.hash_offset:img.hash_offset + 32] = hashlib.sha256(buf[img.offset:img.hash_offset]).digest()


def bootloader_offset(buf) -> int:
    # ESP32 classic: bootloader at 0x1000; S2/S3/C3: 0x0
    return 0x1000 if len(buf) > 0x1000 and buf[0x1000] == IMAGE_MAGIC else 0x0


def app_desc(buf, img: Image) -> dict:
    """esp_app_desc_t lives at the start of the first DROM segment."""
    s = img.segments[0]
    i = s.file_offset
    if struct.unpack_from("<I", buf, i)[0] != 0xABCD5432:
        return {}
    cstr = lambda a, b: bytes(buf[i + a:i + b]).split(b"\0")[0].decode(errors="replace")
    return {"version": cstr(16, 48), "project": cstr(48, 80), "time": cstr(80, 96),
            "date": cstr(96, 112), "idf": cstr(112, 144)}


def describe_merged(buf) -> dict:
    """Summarise a merged (0x0-based) firmware file."""
    out = {"size": len(buf)}
    bl = parse_image(buf, bootloader_offset(buf))
    out["chip"] = bl.chip
    out["bootloader_ok"] = all(verify_image(buf, bl))
    app = parse_image(buf, APP_OFFSET)
    out["app_ok"] = all(verify_image(buf, app))
    out["app"] = app_desc(buf, app)
    out["app_end"] = app.end
    return out
