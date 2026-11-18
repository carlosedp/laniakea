#!/bin/sh
# Shortcut (Linux/macOS): ./laniakea.sh <command> [args]   (see README.md)
# Uses the project's venv (scripts/setup.sh) when present, else the system python3.
set -e
DIR=$(cd "$(dirname "$0")" && pwd)
PY="$DIR/.venv/bin/python"
[ -x "$PY" ] || PY=python3
exec "$PY" "$DIR/tools/laniakea.py" "$@"
