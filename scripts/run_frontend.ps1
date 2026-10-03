# 仅启动前端静态服务（端口 5173），后端需单独运行
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

& $python -m http.server 5173 --directory (Join-Path $projectRoot "frontend")

