"""Download reverse-engineering / patching tools into ./tools (Windows x64).

  tools/jdk/            Temurin JDK 25 (portable, needed by Ghidra)
  tools/ghidra/         Ghidra (Xtensa disassembler + decompiler)
  tools/xtensa-esp-elf/ Espressif GCC toolchain (as/objdump/ld for patches)

Usage: .venv\\Scripts\\python.exe scripts\\install_re_tools.py [--only jdk,ghidra,xtensa]
Re-running skips tools that are already installed.
"""
import argparse
import json
import shutil
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
CACHE = TOOLS / ".downloads"

# Some CDNs (Adoptium) reject urllib's default User-Agent.
_opener = urllib.request.build_opener()
_opener.addheaders = [("User-Agent", "laniakea-tools-installer/1.0")]
urllib.request.install_opener(_opener)


def gh_latest_asset(repo, predicate):
    with urllib.request.urlopen(f"https://api.github.com/repos/{repo}/releases/latest") as r:
        rel = json.load(r)
    for a in rel["assets"]:
        if predicate(a["name"]):
            return a["browser_download_url"], a["name"]
    raise SystemExit(f"no matching asset in {repo} {rel['tag_name']}")


def download(url, name):
    CACHE.mkdir(parents=True, exist_ok=True)
    dest = CACHE / name
    if dest.exists():
        print(f"  cached {dest.name}")
        return dest
    print(f"  downloading {url}")
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length", 0))
        done = 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done >> 20}/{total >> 20} MB", end="", flush=True)
    print()
    tmp.rename(dest)
    return dest


def unzip_single_root(zpath, target):
    """Extract a zip whose content sits in one top-level folder into `target`."""
    tmp = target.with_name(target.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(tmp)
    entries = list(tmp.iterdir())
    src = entries[0] if len(entries) == 1 and entries[0].is_dir() else tmp
    shutil.rmtree(target, ignore_errors=True)
    # Antivirus often locks freshly-extracted files on Windows: retry, then fall back to copying.
    for _ in range(10):
        try:
            src.rename(target)
            break
        except PermissionError:
            time.sleep(3)
    else:
        shutil.copytree(src, target)
    shutil.rmtree(tmp, ignore_errors=True)


def install_jdk():
    target = TOOLS / "jdk"
    if (target / "release").exists() and 'JAVA_VERSION="25' in (target / "release").read_text():
        return print("jdk: already installed")
    print("jdk:")
    url = "https://api.adoptium.net/v3/binary/latest/25/ga/windows/x64/jdk/hotspot/normal/eclipse"
    unzip_single_root(download(url, "temurin-jdk25-windows-x64.zip"), target)


def install_ghidra():
    target = TOOLS / "ghidra"
    if (target / "support" / "analyzeHeadless.bat").exists():
        return print("ghidra: already installed")
    print("ghidra:")
    url, name = gh_latest_asset("NationalSecurityAgency/ghidra", lambda n: n.endswith(".zip"))
    unzip_single_root(download(url, name), target)
    # Point Ghidra at the local JDK so it never prompts.
    props = target / "support" / "launch.properties"
    jdk = (TOOLS / "jdk").as_posix()
    txt = props.read_text()
    if "JAVA_HOME_OVERRIDE=" + jdk not in txt:
        props.write_text(txt.replace("JAVA_HOME_OVERRIDE=", "JAVA_HOME_OVERRIDE=" + jdk, 1))


def install_xtensa():
    target = TOOLS / "xtensa-esp-elf"
    if (target / "bin" / "xtensa-esp32-elf-objdump.exe").exists() or (target / "bin" / "xtensa-esp-elf-objdump.exe").exists():
        return print("xtensa-esp-elf: already installed")
    print("xtensa-esp-elf:")
    url, name = gh_latest_asset("espressif/crosstool-NG",
                                lambda n: n.startswith("xtensa-esp-elf") and "x86_64-w64-mingw32" in n and n.endswith(".zip"))
    unzip_single_root(download(url, name), target)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="jdk,ghidra,xtensa")
    ap.add_argument("--keep-downloads", action="store_true")
    a = ap.parse_args()
    if sys.platform != "win32":
        raise SystemExit("This installer fetches Windows builds; on Linux/macOS install Ghidra + xtensa-esp-elf manually.")
    want = set(a.only.split(","))
    if "jdk" in want: install_jdk()
    if "ghidra" in want: install_ghidra()
    if "xtensa" in want: install_xtensa()
    if not a.keep_downloads:
        shutil.rmtree(CACHE, ignore_errors=True)
    print("done.")


if __name__ == "__main__":
    main()
