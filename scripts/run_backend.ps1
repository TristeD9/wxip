# 启动后端（开发模式，前端由同一进程静态托管在 http://127.0.0.1:8000）
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "未找到虚拟环境，请先执行：python -m venv .venv 并安装 backend/requirements-dev.txt"
}

& $python -m uvicorn app.main:app --app-dir (Join-Path $projectRoot "backend") --host 0.0.0.0 --port 8000 --reload

