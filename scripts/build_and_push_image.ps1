# 构建并推送 Docker 镜像到 Docker Hub
#
# 用法：
#   docker login                       # 先登录 Docker Hub
#   .\scripts\build_and_push_image.ps1 -Repository <用户名>/wecom-trusted-ip
#   .\scripts\build_and_push_image.ps1 -Repository <用户名>/wecom-trusted-ip -Tag 1.0.0
param(
    [Parameter(Mandatory = $true)]
    [string]$Repository,

    [string]$Tag = "latest",

    [string]$Platform = "linux/amd64",

    [string]$BaseRegistry = "mcr.microsoft.com",

    [string]$PipIndexUrl = "https://pypi.org/simple"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$image = "${Repository}:${Tag}"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "未找到 docker 命令，请先安装 Docker Desktop 并启动。"
}

Push-Location $projectRoot
try {
    Write-Host "构建镜像 $image（平台 $Platform）..."
    docker build --platform $Platform `
        --build-arg "BASE_REGISTRY=$BaseRegistry" `
        --build-arg "PIP_INDEX_URL=$PipIndexUrl" `
        -t $image .
    if ($LASTEXITCODE -ne 0) { throw "docker build 失败" }

    Write-Host "推送镜像 $image ..."
    docker push $image
    if ($LASTEXITCODE -ne 0) { throw "docker push 失败（是否已 docker login？）" }

    Write-Host "完成：$image"
}
finally {
    Pop-Location
}
