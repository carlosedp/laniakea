import sys, struct, hashlib, re

CHIP = {0: "ESP32", 9: "ESP32-S3", 2: "ESP32-S2", 5: "ESP32-C3"}
PTYPES = {0: "app", 1: "data"}


def parse_image(d, off, label):
    magic, nseg, mode, sizefreq, entry = struct.unpack_from("<BBBBI", d, off)
    if magic != 0xE9:
        print(f"  [{label}] no image at {off:#x}")
        return
    wp, dpin, *_ = struct.unpack_from("<BB", d, off + 8)
    chip_id, = struct.unpack_from("<H", d, off + 12)
    hash_appended = d[off + 23]
    print(f"  [{label}] @ {off:#x}: segs={nseg} entry={entry:#x} chip={CHIP.get(chip_id, chip_id)} "
          f"flash_mode={mode} size/freq={sizefreq:#x} hash_appended={hash_appended}")
    p = off + 24
    for i in range(nseg):
        addr, ln = struct.unpack_from("<II", d, p)
        p += 8
        region = "?"
        if 0x3F400000 <= addr < 0x3F800000 or 0x3C000000 <= addr < 0x3E000000: region = "DROM (rodata)"
        elif 0x400D0000 <= addr < 0x40400000 or 0x42000000 <= addr < 0x44000000: region = "IROM (code in flash)"
        elif 0x40080000 <= addr < 0x400A0000 or 0x40370000 <= addr < 0x403E0000: region = "IRAM"
        elif 0x3FF80000 <= addr < 0x3FF82000 or 0x50000000 <= addr < 0x50002000: region = "RTC"
        elif 0x3FFB0000 <= addr < 0x40000000 or 0x3FC80000 <= addr < 0x3FD00000: region = "DRAM"
        print(f"     seg{i}: load={addr:#010x} len={ln:#8x}  {region}")
        p += ln
    pad = (16 - ((p - off + 1) % 16)) % 16
    p += pad + 1  # checksum byte
    if hash_appended:
        p += 32
    end = p
    print(f"     image ends at {end:#x} (size {end - off:#x})")
    # Secure boot v2 signature block: magic 0xE7 at next 4K-aligned offset
    sig = (end + 0xFFF) & ~0xFFF
    if sig + 4 <= len(d) and d[sig] == 0xE7 and d[sig + 1] == 0x02:
        print(f"     ** Secure Boot v2 signature block found at {sig:#x}")
    else:
        print(f"     no Secure Boot v2 signature block after image")
    return end


def esp_app_desc(d, off):
    # esp_app_desc_t lives at start of first DROM segment: magic 0xABCD5432
    i = d.find(struct.pack("<I", 0xABCD5432), off, off + 0x200)
    if i < 0:
        return
    ver = d[i + 16:i + 48].split(b"\0")[0].decode(errors="replace")
    proj = d[i + 48:i + 80].split(b"\0")[0].decode(errors="replace")
    tm = d[i + 80:i + 96].split(b"\0")[0].decode(errors="replace")
    dt = d[i + 96:i + 112].split(b"\0")[0].decode(errors="replace")
    idf = d[i + 112:i + 144].split(b"\0")[0].decode(errors="replace")
    print(f"     app_desc: project='{proj}' version='{ver}' built='{dt} {tm}' idf='{idf}'")


def main(path):
    d = open(path, "rb").read()
    print(f"== {path} ({len(d)} bytes)")
    boot_off = 0x1000 if d[0x1000:0x1001] == b"\xe9" else 0x0
    parse_image(d, boot_off, "bootloader")
    apps = []
    for pt in (0x8000, 0x9000):
        if d[pt:pt + 2] == b"\xaa\x50":
            print(f"  partition table @ {pt:#x}:")
            p = pt
            while d[p:p + 2] == b"\xaa\x50":
                t, st, o, sz = struct.unpack_from("<BBII", d, p + 2)
                name = d[p + 12:p + 28].split(b"\0")[0].decode()
                flags, = struct.unpack_from("<I", d, p + 28)
                print(f"     {name:12s} {PTYPES.get(t, t)}/{st:#04x} off={o:#08x} size={sz:#08x} flags={flags}")
                if t == 0:
                    apps.append((name, o))
                p += 32
            if d[p:p + 2] == b"\xeb\xeb":
                print("     (MD5 of table present)")
            break
    for name, o in apps:
        if o < len(d):
            end = parse_image(d, o, f"app:{name}")
            esp_app_desc(d, o + 24 + 8)
    # Heuristic strings
    s = re.findall(rb"[\x20-\x7e]{6,}", d)
    keys = [b"arduino", b"Arduino", b"esp-idf", b"ESP-IDF", b"FreeRTOS", b"SECURE", b"secure_boot", b"flash_encrypt",
            b".cpp", b".c\x00", b"I2S", b"i2s", b"ssd1306", b"SSD1306", b"Adafruit", b"MIDI", b"BLE", b"WiFi", b"LVGL", b"lvgl"]
    hits = {}
    for x in s:
        for k in keys:
            if k in x:
                hits.setdefault(k.decode(errors='replace'), []).append(x.decode(errors='replace'))
    for k, v in hits.items():
        print(f"  strings~'{k}' ({len(v)}): {v[:6]}")
    print(f"  total printable strings: {len(s)}")


if __name__ == "__main__":
    for a in sys.argv[1:]:
        main(a)
