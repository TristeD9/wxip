# 管理员账号运维：查看账号、重设密码、忘记账号时重置
#
# 用法：
#   .\scripts\admin_cli.ps1 list-admins
#   .\scripts\admin_cli.ps1 set-password -Username admin
#   .\scripts\admin_cli.ps1 reset-admin
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("list-admins", "set-password", "reset-admin")]
    [string]$Command,

    [string]$Username,

    [string]$Password
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$backend = Join-Path $projectRoot "backend"

if (-not (Test-Path -LiteralPath $python)) {
    throw "未找到虚拟环境：$python"
}

$cliArgs = @($Command)
if ($Username) { $cliArgs += @("--username", $Username) }
if ($Password) { $cliArgs += @("--password", $Password) }

Push-Location $backend
try {
    & $python -m app.cli @cliArgs
}
finally {
    Pop-Location
}
