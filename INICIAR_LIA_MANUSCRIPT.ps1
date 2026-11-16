# LIA Manuscript - Iniciador integral Windows
# Guardar en la raiz del proyecto como INICIAR_LIA_MANUSCRIPT.ps1
param(
    [string]$ProjectRoot = 'C:\LIA_RECUPERACION\RECUPERACIONES_REPOSITORIOS\lia_manuscript',
    [switch]$SinOllama,
    [switch]$SinFlutter,
    [switch]$AnalizarFlutter
)
$ErrorActionPreference = 'Stop'
$Backend = Join-Path $ProjectRoot 'backend'
$Frontend = Join-Path $ProjectRoot 'frontend'
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$Logs = Join-Path $ProjectRoot 'logs'
$ApiUrl = 'http://127.0.0.1:8102'
$OllamaUrl = 'http://127.0.0.1:11434/api/tags'

function Test-Http([string]$Url) {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500)
    } catch { return $false }
}
function Find-Command([string]$Name) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -ne $command) { return $command.Source }
    return $null
}
function Start-Terminal([string]$Title, [string]$Command, [string]$WorkingDirectory) {
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes(
        "`$Host.UI.RawUI.WindowTitle = '$($Title.Replace("'", "''"))'; Set-Location -LiteralPath '$($WorkingDirectory.Replace("'", "''"))'; $Command"
    ))
    Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-NoExit','-EncodedCommand',$encoded) -WorkingDirectory $WorkingDirectory | Out-Null
}

Write-Host "`n=== LIA MANUSCRIPT - INICIADOR ===" -ForegroundColor Cyan
Write-Host "Proyecto: $ProjectRoot"
foreach ($path in @($ProjectRoot, $Backend, $Frontend, $Python)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "No se encontro: $path" }
}
New-Item -ItemType Directory -Path $Logs -Force | Out-Null

# Iniciar backend solamente si el puerto no esta ocupado.
if (Test-Http "$ApiUrl/openapi.json") {
    Write-Host '[OK] FastAPI ya responde en el puerto 8102.' -ForegroundColor Green
} else {
    $listener = Get-NetTCPConnection -LocalPort 8102 -State Listen -ErrorAction SilentlyContinue
    if ($listener) { throw 'El puerto 8102 esta ocupado por otro proceso. No se iniciara un backend duplicado.' }
    Write-Host '[...] Iniciando FastAPI en una ventana independiente...' -ForegroundColor Yellow
    $pythonQuoted = '"' + $Python + '"'
    Start-Terminal 'LIA Manuscript - Backend FastAPI' "& $pythonQuoted -m uvicorn app.main:app --host 127.0.0.1 --port 8102 2>&1 | Tee-Object -FilePath '$((Join-Path $Logs 'backend.log').Replace("'", "''"))' -Append" $Backend
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Http "$ApiUrl/openapi.json") { $ready = $true; break }
    }
    if (-not $ready) { throw "FastAPI no respondio en 30 segundos. Revisa $Logs\backend.log y la ventana del backend." }
    Write-Host '[OK] FastAPI iniciado.' -ForegroundColor Green
}

if (-not $SinOllama) {
    if (Test-Http $OllamaUrl) {
        Write-Host '[OK] Ollama responde en 127.0.0.1:11434.' -ForegroundColor Green
    } else {
        $ollama = Find-Command 'ollama'
        if ($ollama) {
            Write-Host '[...] Iniciando Ollama...' -ForegroundColor Yellow
            Start-Terminal 'LIA Manuscript - Ollama' "& '$($ollama.Replace("'", "''"))' serve 2>&1 | Tee-Object -FilePath '$((Join-Path $Logs 'ollama.log').Replace("'", "''"))' -Append" $ProjectRoot
            $ollamaReady = $false
            for ($i = 0; $i -lt 15; $i++) {
                Start-Sleep -Seconds 1
                if (Test-Http $OllamaUrl) { $ollamaReady = $true; break }
            }
            if ($ollamaReady) { Write-Host '[OK] Ollama iniciado.' -ForegroundColor Green }
            else { Write-Warning 'Ollama no respondio. La interfaz podra abrirse, pero las traducciones locales podrian fallar.' }
        } else {
            Write-Warning 'No se encontro el comando ollama. La interfaz podra abrirse, pero las traducciones locales requeriran Ollama.'
        }
    }
}

if (-not $SinFlutter) {
    $flutter = Find-Command 'flutter'
    if (-not $flutter) { throw 'Flutter no esta en PATH. Abre una terminal con Flutter configurado e intenta nuevamente.' }
    if ($AnalizarFlutter) {
        Write-Host '[...] Analizando codigo Flutter...' -ForegroundColor Yellow
        Push-Location $Frontend
        try {
            & $flutter analyze
            if ($LASTEXITCODE -ne 0) { throw 'flutter analyze detecto errores. Corrigelos antes de iniciar la aplicacion.' }
        } finally { Pop-Location }
    }
    Write-Host '[...] Abriendo LIA Manuscript en Windows...' -ForegroundColor Yellow
    Start-Terminal 'LIA Manuscript - Flutter Windows' "& '$($flutter.Replace("'", "''"))' run -d windows 2>&1 | Tee-Object -FilePath '$((Join-Path $Logs 'flutter.log').Replace("'", "''"))' -Append" $Frontend
}
Write-Host "`n=== SERVICIOS ===" -ForegroundColor Cyan
Write-Host "API:       $ApiUrl/docs"
Write-Host "Ollama:    http://127.0.0.1:11434"
Write-Host "Registros: $Logs"
Write-Host 'Las ventanas independientes mantienen los servicios activos.'
Write-Host 'Para detenerlos, presiona Ctrl+C en cada ventana iniciada por el script.'
