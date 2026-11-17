#!/usr/bin/env sh
# Sets up the local Laniakea dev environment inside this folder (Linux/macOS/Git Bash).
set -e
cd "$(dirname "$0")/.."
if command -v uv >/dev/null 2>&1; then
  uv venv .venv --allow-existing
  if [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe; else PY=.venv/bin/python; fi
  uv pip install --python "$PY" -r requirements.txt
else
  python3 -m venv .venv
  if [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe; else PY=.venv/bin/python; fi
  "$PY" -m pip install -r requirements.txt
fi
"$PY" -m esptool version
echo "Done."
