#!/usr/bin/env sh
# Set up the local Laniakea environment (Linux / macOS / Git Bash):
#   .venv/  Python venv with esptool, pyserial, numpy
# Uses uv if available, else python3 -m venv, else downloads a local uv into tools/uv/
# (no sudo needed; useful on Ubuntu where python3-venv isn't installed).
set -e
cd "$(dirname "$0")/.."

fetch_uv() {
  case "$(uname -s)-$(uname -m)" in
    Linux-x86_64)            T=x86_64-unknown-linux-gnu ;;
    Linux-aarch64|Linux-arm64) T=aarch64-unknown-linux-gnu ;;
    Darwin-arm64)            T=aarch64-apple-darwin ;;
    Darwin-x86_64)           T=x86_64-apple-darwin ;;
    *) echo "unsupported platform for automatic uv download; install python3-venv or uv"; exit 1 ;;
  esac
  echo "python3 venv/ensurepip not available - downloading a local uv into tools/uv/ ..."
  mkdir -p tools/uv
  curl -LsSf "https://github.com/astral-sh/uv/releases/latest/download/uv-$T.tar.gz" | tar xz -C tools/uv --strip-components=1
  UV=tools/uv/uv
}

if command -v uv >/dev/null 2>&1; then
  UV=uv
elif [ -x tools/uv/uv ]; then
  UV=tools/uv/uv
elif python3 -c "import venv, ensurepip" >/dev/null 2>&1; then
  UV=
else
  fetch_uv
fi

if [ -n "$UV" ]; then
  "$UV" venv .venv --allow-existing
  if [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe; else PY=.venv/bin/python; fi
  "$UV" pip install --python "$PY" -r requirements.txt
else
  python3 -m venv .venv
  if [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe; else PY=.venv/bin/python; fi
  "$PY" -m pip install -r requirements.txt
fi
"$PY" -m esptool version
chmod +x laniakea.sh scripts/*.sh 2>/dev/null || true
echo "Done. Next: ./laniakea.sh ports   (Linux: you may need 'sudo usermod -aG dialout \$USER')"
