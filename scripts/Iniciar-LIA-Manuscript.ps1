$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $Python)) {
    python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el entorno virtual" }
}
& $Python -m pip install -r (Join-Path $Backend "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "FallÃ³ la instalaciÃ³n de dependencias" }
Set-Location $Backend
Write-Host "API: http://127.0.0.1:8102/docs" -ForegroundColor Green
& $Python -m uvicorn app.main:app --host 127.0.0.1 --port 8102