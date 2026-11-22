<#
.SYNOPSIS
    Regenera los tipos TypeScript del frontend a partir del OpenAPI del backend.
    Ejecutar tras cambiar cualquier esquema de la API.
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) {
    $uv = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Filter 'astral-sh.uv*' -Directory |
        ForEach-Object { Join-Path $_.FullName 'uv.exe' } | Where-Object { Test-Path $_ } | Select-Object -First 1
}

$env:MILT_LOG_LEVEL = 'ERROR'
$openapi = Join-Path $root 'frontend\openapi.json'
Push-Location (Join-Path $root 'backend')
try {
    $json = & $uv run python -c "import json; from app.main import create_app; print(json.dumps(create_app().openapi(), ensure_ascii=False, indent=1))"
    [System.IO.File]::WriteAllText($openapi, ($json -join "`n"), [System.Text.UTF8Encoding]::new($false))
} finally { Pop-Location }

Push-Location (Join-Path $root 'frontend')
try {
    $env:COREPACK_ENABLE_DOWNLOAD_PROMPT = '0'
    corepack pnpm run gen:types
} finally { Pop-Location }
