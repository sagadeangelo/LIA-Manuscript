$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Ejecuta primero Iniciar-LIA-Manuscript.ps1" }
Set-Location (Join-Path $Root "backend")
& $Python -m pytest -q tests
if ($LASTEXITCODE -ne 0) { throw "Fallaron las pruebas" }