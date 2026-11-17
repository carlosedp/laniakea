# Sets up the local Laniakea dev environment inside this folder.
#   .venv\           Python venv with esptool, pyserial, numpy
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (Get-Command uv -ErrorAction SilentlyContinue) {
    uv venv .venv --allow-existing
    uv pip install --python .venv\Scripts\python.exe -r requirements.txt
} else {
    python -m venv .venv
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r requirements.txt
}

.venv\Scripts\python.exe -m esptool version
Write-Output "`nDone. Activate with:  .venv\Scripts\Activate.ps1"
