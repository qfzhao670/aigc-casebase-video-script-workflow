$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot
$EnvironmentName = "bili-script-tool"
Set-Location $ProjectDir

if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
    throw "未找到 Conda。请先安装 Miniconda 或 Anaconda，然后重新打开 PowerShell。"
}

function Invoke-Conda {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    & conda @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Conda 命令执行失败：conda $($Arguments -join ' ')"
    }
}

$EnvironmentJson = & conda env list --json
if ($LASTEXITCODE -ne 0) {
    throw "无法读取 Conda 环境列表。"
}
$EnvironmentPaths = ($EnvironmentJson | ConvertFrom-Json).envs
$EnvironmentExists = $EnvironmentPaths | Where-Object {
    (Split-Path -Leaf $_) -eq $EnvironmentName
}

if (-not $EnvironmentExists) {
    Write-Host "正在创建 Conda 环境 $EnvironmentName (Python 3.11)..."
    Invoke-Conda -Arguments @("create", "--name", $EnvironmentName, "python=3.11", "-y")
} else {
    Write-Host "Conda 环境 $EnvironmentName 已存在，将继续安装或更新依赖。"
}

Invoke-Conda -Arguments @("install", "--name", $EnvironmentName, "--channel", "conda-forge", "ffmpeg", "-y")
Invoke-Conda -Arguments @("run", "--name", $EnvironmentName, "python", "-m", "pip", "install", "--upgrade", "pip")
Invoke-Conda -Arguments @("run", "--name", $EnvironmentName, "python", "-m", "pip", "install", "-r", "requirements.txt")
Invoke-Conda -Arguments @("run", "--name", $EnvironmentName, "python", "-m", "pip", "install", "--upgrade", "yt-dlp[default]")

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "已创建 .env，请填写 DASHSCOPE_API_KEY。"
}

Write-Host ""
Write-Host "Windows 环境安装完成。"
Write-Host "1. 运行：conda activate $EnvironmentName"
Write-Host "2. 编辑 .env，填写 DASHSCOPE_API_KEY"
Write-Host "3. 运行：python run.py"

