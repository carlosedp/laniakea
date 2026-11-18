#!/usr/bin/env sh
# Open the Laniakea Ghidra project in the GUI (Linux/macOS).
ROOT=$(cd "$(dirname "$0")/.." && pwd)
case "$ROOT" in
  *'#'*) LINK="${TMPDIR:-/tmp}/laniakea-ghidra"; ln -sfn "$ROOT" "$LINK"; R=$LINK ;;
  *) R=$ROOT ;;
esac
if [ -d "$R/tools/jdk/Contents/Home" ]; then export JAVA_HOME="$R/tools/jdk/Contents/Home"; else export JAVA_HOME="$R/tools/jdk"; fi
echo "Open project: $R/re/ghidra/project/Laniakea.gpr"
exec "$R/tools/ghidra/ghidraRun"
