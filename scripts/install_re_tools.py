"""Download reverse-engineering / patching tools into ./tools (Windows, Linux, macOS).

  tools/xtensa-esp-elf/ Espressif GCC toolchain (as/ld/objdump): needed to BUILD patches
  tools/jdk/            Temurin JDK 25 (portable): needed by Ghidra
  tools/ghidra/         Ghidra (Xtensa disassembler + decompiler): only for reverse engineering

Usage:  python scripts/install_re_tools.py [--only xtensa|jdk|ghidra|jdk,ghidra,xtensa]
        (run it with the venv's python: .venv\\Scripts\\python.exe or .venv/bin/python)
Re-running skips tools that are already installed.
"""
import argparse
import json
import os
import platform
import shutil
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
CACHE = TOOLS / ".downloads"
WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
ARM = platform.machine().lower() in ("arm64", "aarch64")

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
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length", 0))
        done, shown = 0, -1
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            pct = done * 100 // total if total else -1
            if pct >= 0 and pct // 10 != shown:
                shown = pct // 10
                print(f"  {pct:3d}%  ({done >> 20}/{total >> 20} MB)", flush=True)
    tmp.rename(dest)
    return dest


def extract_single_root(archive: Path, target: Path):
    """Extract a .zip/.tar.* whose content sits in one top-level folder into `target`,
    keeping Unix permissions (zipfile drops them; Ghidra's scripts need +x)."""
    tmp = target.with_name(target.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                path = Path(z.extract(info, tmp))
                mode = info.external_attr >> 16
                if not WINDOWS and mode and not info.is_dir():
                    os.chmod(path, mode & 0o777)
    else:
        with tarfile.open(archive) as t:
            if hasattr(tarfile, "tar_filter"):
                t.extractall(tmp, filter="tar")
            else:
                t.extractall(tmp)
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
        shutil.copytree(src, target, symlinks=True)
    shutil.rmtree(tmp, ignore_errors=True)


def java_home() -> Path:
    jdk = TOOLS / "jdk"
    mac_home = jdk / "Contents" / "Home"          # macOS JDK bundle layout
    return mac_home if mac_home.exists() else jdk


def install_jdk():
    home = java_home()
    if (home / "release").exists() and 'JAVA_VERSION="25' in (home / "release").read_text():
        return print("jdk: already installed")
    print("jdk:")
    os_name = "windows" if WINDOWS else "mac" if MACOS else "linux"
    arch = "aarch64" if ARM else "x64"
    url = f"https://api.adoptium.net/v3/binary/latest/25/ga/{os_name}/{arch}/jdk/hotspot/normal/eclipse"
    ext = "zip" if WINDOWS else "tar.gz"
    extract_single_root(download(url, f"temurin-jdk25-{os_name}-{arch}.{ext}"), TOOLS / "jdk")


def install_ghidra():
    target = TOOLS / "ghidra"
    if (target / "support" / ("analyzeHeadless.bat" if WINDOWS else "analyzeHeadless")).exists():
        return print("ghidra: already installed")
    print("ghidra:")
    url, name = gh_latest_asset("NationalSecurityAgency/ghidra", lambda n: n.endswith(".zip"))
    extract_single_root(download(url, name), target)
    # Point Ghidra at the local JDK so it never prompts.
    props = target / "support" / "launch.properties"
    home = java_home().as_posix()
    txt = props.read_text()
    if "JAVA_HOME_OVERRIDE=" + home not in txt:
        props.write_text(txt.replace("JAVA_HOME_OVERRIDE=", "JAVA_HOME_OVERRIDE=" + home, 1))


def xtensa_asset_suffix() -> str:
    if WINDOWS:
        return ("aarch64" if ARM else "x86_64") + "-w64-mingw32.zip"
    if MACOS:
        return ("aarch64" if ARM else "x86_64") + "-apple-darwin.tar.xz"
    return ("aarch64" if ARM else "x86_64") + "-linux-gnu.tar.xz"


def install_xtensa():
    target = TOOLS / "xtensa-esp-elf"
    if (target / "bin" / ("xtensa-esp32-elf-as" + (".exe" if WINDOWS else ""))).exists():
        return print("xtensa-esp-elf: already installed")
    print("xtensa-esp-elf:")
    suffix = xtensa_asset_suffix()
    url, name = gh_latest_asset("espressif/crosstool-NG",
                                lambda n: n.startswith("xtensa-esp-elf-") and n.endswith(suffix))
    extract_single_root(download(url, name), target)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="jdk,ghidra,xtensa")
    ap.add_argument("--keep-downloads", action="store_true")
    a = ap.parse_args()
    want = set(a.only.split(","))
    if "xtensa" in want:
        install_xtensa()
    if "jdk" in want:
        install_jdk()
    if "ghidra" in want:
        install_ghidra()
    if not a.keep_downloads:
        shutil.rmtree(CACHE, ignore_errors=True)
    print("done.")


if __name__ == "__main__":
    main()
