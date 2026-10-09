$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectDir

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "未找到 Python Launcher。请先安装 Python 3.11。"
}

py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "已创建 .env，请填写 DASHSCOPE_API_KEY。"
}

foreach ($Command in @("ffmpeg", "yt-dlp")) {
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        Write-Warning "未找到 $Command，请安装后将其加入 PATH。"
    }
}

Write-Host "Python 环境安装完成。运行 .\.venv\Scripts\pythonw.exe run.py 启动。"

