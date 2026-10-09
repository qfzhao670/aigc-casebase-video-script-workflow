#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$project_dir"

if [[ ! -x .venv/bin/python ]]; then
  echo "尚未初始化环境，请先运行：scripts/setup_macos.sh"
  read -r -p "按回车键退出……"
  exit 1
fi

exec .venv/bin/python run.py

