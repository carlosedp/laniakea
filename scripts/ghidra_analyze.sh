#!/usr/bin/env sh
# Import a Laniakea firmware into a Ghidra project and export decompiled C (Linux/macOS).
# Usage: scripts/ghidra_analyze.sh [v3.6]
# Output: re/ghidra/<version>/ (decompiled.c, functions.txt, string_xrefs.txt)
#         re/ghidra/project/Laniakea.gpr  (open with scripts/ghidra_gui.sh)
set -e
VERSION=${1:-v3.6}
ROOT=$(cd "$(dirname "$0")/.." && pwd)

# Ghidra rejects project paths containing '#': work through a symlink if needed.
case "$ROOT" in
  *'#'*) LINK=$(mktemp -d)/laniakea; ln -s "$ROOT" "$LINK"; R=$LINK ;;
  *) R=$ROOT ;;
esac

if [ -d "$R/tools/jdk/Contents/Home" ]; then export JAVA_HOME="$R/tools/jdk/Contents/Home"; else export JAVA_HOME="$R/tools/jdk"; fi
PY="$R/.venv/bin/python"
BIN="$R/firmware/official/laniakea/laniakea_$VERSION.bin"
[ -f "$BIN" ] || "$PY" "$R/tools/laniakea.py" fetch    # official images are downloaded, not in git
ELF="$R/re/ghidra/laniakea_$VERSION.elf"
OUT="$R/re/ghidra/$VERSION"
"$PY" "$R/tools/img2elf.py" "$BIN" "$ELF"
mkdir -p "$R/re/ghidra/project"

"$R/tools/ghidra/support/analyzeHeadless" "$R/re/ghidra/project" Laniakea \
  -import "$ELF" -overwrite \
  -processor "Xtensa:LE:32:default" \
  -scriptPath "$R/re/ghidra_scripts" \
  -preScript ImportSymbols.java "$ELF.symbols.txt" \
  -postScript ExportAll.java "$OUT" \
  -analysisTimeoutPerFile 3600

[ -n "$LINK" ] && rm -f "$LINK"
echo "exported to re/ghidra/$VERSION"
