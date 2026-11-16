param(
    [string]$Raiz = 'C:\LIA_RECUPERACION\RECUPERACIONES_REPOSITORIOS\lia_manuscript',
    [string]$LanguageTool = 'C:\LIA_RECUPERACION\RECUPERACIONES_REPOSITORIOS\lia-staylo\LanguageTool'
)

$ErrorActionPreference = 'Stop'
$Inicio = Join-Path $Raiz 'INICIAR_LIA_MANUSCRIPT.ps1'
if (-not (Test-Path -LiteralPath $Inicio -PathType Leaf)) {
    throw "No se encontro el iniciador: $Inicio"
}

$Docker = Get-Command docker.exe -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($Docker) {
    $PreferenciaAnterior = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $Motor = & $Docker.Source version --format '{{.Server.Version}}' 2>$null
        $DockerActivo = $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $PreferenciaAnterior
    }
    if ($DockerActivo) {
        Write-Host "Docker activo: $Motor"
    } else {
        Write-Host 'Docker no responde. LanguageTool funciona con Java.'
    }
} else {
    Write-Host 'Docker no esta en PATH. Continuando con Java.'
}

function Test-LanguageTool {
    try {
        $Idiomas = Invoke-RestMethod -Uri 'http://127.0.0.1:8101/v2/languages' -TimeoutSec 2
        return [bool]($Idiomas | Where-Object { $_.longCode -eq 'en-US' })
    } catch {
        return $false
    }
}

if (-not (Test-LanguageTool)) {
    if (Get-NetTCPConnection -LocalPort 8101 -State Listen -ErrorAction SilentlyContinue) {
        throw 'El puerto 8101 esta ocupado y no responde como LanguageTool con en-US.'
    }
    $Jar = Join-Path $LanguageTool 'languagetool-server.jar'
    if (-not (Test-Path -LiteralPath $Jar -PathType Leaf)) {
        throw "No se encontro el servidor de LanguageTool: $Jar"
    }
    $Java = Get-Command java.exe -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $Java) {
        throw 'java.exe no esta en PATH.'
    }

    $Logs = Join-Path $Raiz 'logs'
    New-Item -ItemType Directory -Path $Logs -Force | Out-Null
    $Sello = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
    $Salida = Join-Path $Logs "languagetool_$Sello.out.log"
    $Errores = Join-Path $Logs "languagetool_$Sello.err.log"

    $Proceso = Start-Process -FilePath $Java.Source -WorkingDirectory $LanguageTool `
        -ArgumentList @(
            '-cp', '.;languagetool-server.jar;languagetool-standalone.jar',
            'org.languagetool.server.HTTPServer', '--port', '8101'
        ) -WindowStyle Hidden -RedirectStandardOutput $Salida `
        -RedirectStandardError $Errores -PassThru

    $Limite = (Get-Date).AddSeconds(45)
    do {
        $Listo = Test-LanguageTool
        if ($Listo) { break }
        $Proceso.Refresh()
        if ($Proceso.HasExited) {
            throw "LanguageTool se detuvo. Revisa: $Errores"
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $Limite)
    if (-not $Listo) {
        throw "LanguageTool no confirmo en-US. Revisa: $Salida y $Errores"
    }
}

Write-Host 'LanguageTool listo para en-US en el puerto 8101.' -ForegroundColor Green
Push-Location -LiteralPath $Raiz
try {
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Inicio
    $Resultado = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $Resultado
