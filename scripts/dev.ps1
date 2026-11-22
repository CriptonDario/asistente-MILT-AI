<#
.SYNOPSIS
    Arranca el backend de MILT AI en modo desarrollo (Windows).
.PARAMETER Fake
    Usa el proveedor de IA simulado (no necesita Ollama).
.PARAMETER Port
    Puerto local del backend (por defecto 8765).
#>
param(
    [switch]$Fake,
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'

# uv: en el PATH o en la ruta de instalación de winget.
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) {
    $candidate = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Filter 'astral-sh.uv*' -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName 'uv.exe' } | Where-Object { Test-Path $_ } | Select-Object -First 1
    $uv = $candidate
}
if (-not $uv) { throw 'No se encontró uv. Instálalo con: winget install astral-sh.uv' }

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

Push-Location $backend
try {
    & $uv sync
    & $uv run uvicorn app.main:app --host 127.0.0.1 --port $Port --reload
} finally {
    Pop-Location
}
