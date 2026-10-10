# 运行前端单元测试（vitest + jsdom）
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $projectRoot "frontend"

Push-Location $frontend
try {
    if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
        Write-Host "首次运行，先安装前端测试依赖（npm ci）..."
        & npm ci
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    & npm test
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

exit $code
