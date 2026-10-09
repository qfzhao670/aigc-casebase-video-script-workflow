#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_dir"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew 未安装。请先访问 https://brew.sh 安装 Homebrew。"
  exit 1
fi

echo "正在安装 macOS 原生依赖……"
brew install python@3.11 python-tk@3.11 ffmpeg yt-dlp

python_bin="$(brew --prefix python@3.11)/bin/python3.11"
"$python_bin" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "已创建 .env，请填写 DASHSCOPE_API_KEY。"
fi

echo "安装完成。填写 .env 后，可双击 launch_macos.command 启动。"

