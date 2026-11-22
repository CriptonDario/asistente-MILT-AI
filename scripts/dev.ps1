<#
.SYNOPSIS
    Arranca MILT AI en modo desarrollo (Windows): backend y, opcionalmente, frontend.
.PARAMETER Fake
    Usa el proveedor de IA simulado (no necesita Ollama).
.PARAMETER BackendOnly
    Arranca solo el backend.
.PARAMETER Port
    Puerto local del backend (por defecto 8765).
.EXAMPLE
    .\scripts\dev.ps1            # backend + interfaz en http://localhost:5173
    .\scripts\dev.ps1 -Fake      # sin Ollama
#>
param(
    [switch]$Fake,
    [switch]$BackendOnly,
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'

function Find-Uv {
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidate = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Filter 'astral-sh.uv*' -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName 'uv.exe' } | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $candidate) { throw 'No se encontró uv. Instálalo con: winget install astral-sh.uv' }
    return $candidate
}

$uv = Find-Uv
$env:COREPACK_ENABLE_DOWNLOAD_PROMPT = '0'

if ($Fake) {
    $env:MILT_LLM_PROVIDER = 'fake'
} else {
    try {
        Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 3 | Out-Null
    } catch {
        Write-Warning 'Ollama no responde en 127.0.0.1:11434. Ábrelo o usa -Fake.'
    }
}
if (-not $env:MILT_LOG_JSON) { $env:MILT_LOG_JSON = 'false' }

$frontendProcess = $null
if (-not $BackendOnly) {
    Push-Location $frontend
    try {
        if (-not (Test-Path 'node_modules')) { corepack pnpm install }
    } finally { Pop-Location }
    # La interfaz se abre en una ventana aparte; al cerrar el backend se detiene también.
    $frontendProcess = Start-Process -PassThru -WorkingDirectory $frontend -FilePath 'cmd.exe' `
        -ArgumentList '/c', 'corepack pnpm dev'
    Write-Host 'Interfaz: http://localhost:5173' -ForegroundColor Cyan
}

Push-Location $backend
try {
    & $uv sync
    & $uv run uvicorn app.main:app --host 127.0.0.1 --port $Port --reload
} finally {
    Pop-Location
    if ($frontendProcess -and -not $frontendProcess.HasExited) {
        Stop-Process -Id $frontendProcess.Id -Force -ErrorAction SilentlyContinue
    }
}
