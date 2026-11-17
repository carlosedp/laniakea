# Open the Laniakea Ghidra project in the GUI.
# Ghidra rejects paths with '#' (this folder is under "#Music"), so the project
# root is mapped to a drive letter first. Open  L:\re\ghidra\project\Laniakea.gpr
# When finished:  subst L: /d
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path "L:\re\ghidra")) { subst L: "$root" }
$env:JAVA_HOME = "L:\tools\jdk"
& "L:\tools\ghidra\ghidraRun.bat"
Write-Output "Project: L:\re\ghidra\project\Laniakea.gpr   (remove mapping later with: subst L: /d)"
