$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectDir

$PythonExe = Join-Path $ProjectDir ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe -PathType Leaf)) {
    throw @"
未找到 .venv\Scripts\python.exe。
请先在 PyCharm 中为本项目新建 Virtualenv，位置选择：$ProjectDir\.venv
建议使用 Python 3.11，然后重新运行本脚本。
"@
}

$RequiredTools = @("ffmpeg.exe", "ffprobe.exe", "ffplay.exe", "yt-dlp.exe")
$MissingTools = @($RequiredTools | Where-Object {
    -not (Test-Path (Join-Path $ProjectDir $_) -PathType Leaf)
})
if ($MissingTools.Count -gt 0) {
    throw "项目根目录缺少：$($MissingTools -join ', ')。请手动复制这些文件，本脚本不会自动下载。"
}

Write-Host "正在将 Python 依赖安装到 PyCharm 虚拟环境 .venv ..."
& $PythonExe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    throw "Python 依赖安装失败。"
}

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "已创建 .env，请填写 DASHSCOPE_API_KEY。"
}

Write-Host ""
Write-Host "Windows 环境安装完成。"
Write-Host "1. 编辑 .env，填写 DASHSCOPE_API_KEY"
Write-Host "2. 在 PyCharm 中将 .venv 设为项目解释器"
Write-Host "3. 运行 run.py"

