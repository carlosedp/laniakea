#!/bin/sh
# Shortcut for POSIX shells (Linux, macOS, WSL, Git Bash/MSYS on Windows):
#   ./laniakea.sh <command> [args]        e.g. ./laniakea.sh patcher build recommended
# (laniakea.cmd is the equivalent for Windows cmd/PowerShell.)
# Uses the project's venv (scripts/setup.sh or setup.ps1) when present, else python3.
set -e
DIR=$(cd "$(dirname "$0")" && pwd)
if [ -x "$DIR/.venv/bin/python" ]; then
  PY="$DIR/.venv/bin/python"
elif [ -x "$DIR/.venv/Scripts/python.exe" ]; then      # venv created on Windows (Git Bash)
  PY="$DIR/.venv/Scripts/python.exe"
else
  PY=python3
fi
exec "$PY" "$DIR/tools/laniakea.py" "$@"
