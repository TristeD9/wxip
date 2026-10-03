# 运行后端单元测试
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$backend = Join-Path $projectRoot "backend"

Push-Location $backend
try {
    & $python -m pytest -q
} finally {
    Pop-Location
}

