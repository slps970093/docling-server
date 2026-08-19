[CmdletBinding()]
param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root
$python = Get-Command py -ErrorAction SilentlyContinue
if ($null -eq $python) {
    throw "Python Launcher is required. Install Python 3.12 from python.org."
}
& $python.Source -3.12 --version
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.12 is required. Install it from python.org."
}

if ($Clean) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist, .venv-build
}

& $python.Source -3.12 -m venv .venv-build
& .venv-build\Scripts\python.exe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }

& .venv-build\Scripts\python.exe -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "pip install requirements failed" }

& .venv-build\Scripts\python.exe -m PyInstaller --clean --noconfirm docling-serve.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host "Built dist\docling-serve.exe"
