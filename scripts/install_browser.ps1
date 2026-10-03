# 安装 Playwright 使用的 Chromium（非 Docker 部署时必须执行一次）
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

& $python -m playwright install chromium

