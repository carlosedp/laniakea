# Import a Laniakea firmware into a Ghidra project and export decompiled C.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\ghidra_analyze.ps1 [-Version v3.6]
# Output: re\ghidra\<version>\  (decompiled.c, functions.txt, string_xrefs.txt)
#         re\ghidra\project\Laniakea.gpr  (open in Ghidra GUI: scripts\ghidra_gui.ps1)
#
# Ghidra rejects paths containing '#' (this folder lives under "#Music"), so the
# project root is temporarily mapped to a free drive letter with `subst`.
param([string]$Version = "v3.6")
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

$used = (Get-PSDrive -PSProvider FileSystem).Name
$letter = @('L','K','J','Q','R','T','U','V','W') | Where-Object { $used -notcontains $_ } | Select-Object -First 1
subst "${letter}:" "$root"
try {
    $r = "${letter}:"
    $env:JAVA_HOME = "$r\tools\jdk"   # Ghidra 12 needs JDK 25 (scripts\install_re_tools.py)
    Set-Location "$r\"
    $bin = "$r\firmware\official\laniakea\laniakea_$Version.bin"
    if (-not (Test-Path $bin)) {
        # official images are downloaded from Magerit (sha256-checked), not stored in git
        & "$r\.venv\Scripts\python.exe" "$r\tools\laniakea.py" fetch
    }
    $elf = "$r\re\ghidra\laniakea_$Version.elf"
    $out = "$r\re\ghidra\$Version"
    & "$r\.venv\Scripts\python.exe" "$r\tools\img2elf.py" $bin $elf
    New-Item -ItemType Directory -Force "$r\re\ghidra\project" | Out-Null

    & "$r\tools\ghidra\support\analyzeHeadless.bat" "$r\re\ghidra\project" Laniakea `
        -import $elf -overwrite `
        -processor "Xtensa:LE:32:default" `
        -scriptPath "$r\re\ghidra_scripts" `
        -preScript ImportSymbols.java "$elf.symbols.txt" `
        -postScript ExportAll.java "$out" `
        -analysisTimeoutPerFile 3600
}
finally {
    Set-Location $root
    subst "${letter}:" /d
}
