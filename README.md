# Bilibili 视频文案工具

这是一个跨平台桌面工具，包含两个相互衔接的功能：

1. **案例库构建**：可一次输入多个 B 站用户 UID，自动获取每个用户最近 N 条公开投稿的 BV 号，也可手动输入 BV 号；随后下载音频、使用 Whisper 转写、调用通义千问生成摘要和关键词，并写入 JSONL 案例库。
2. **文案生成**：根据创作需求筛选参考案例，结合人工大纲和自定义要求生成新的视频文案。

案例库构建页会实时显示整体进度、音频下载进度和 Whisper 语音转录进度，
并在执行日志中保留带时间戳的阶段记录。转录固定使用 `large-v3-turbo` 模型。
在 UID 模式下，每行输入一个纯数字 UID，并设置每个 UID 的获取数量（1–1000）后点击“开始构建”。
工具会合并去重所有获取到的 BV 号、回填到界面，再自动进入原有入库流程。

> **UID 模式的运行前提：**电脑上需要安装 Chrome，并且 Chrome 中的 B 站账号需处于已登录状态。当 B 站对用户空间接口返回 412 或 352 风控时，程序会读取 Chrome 中已登录的 B 站 Cookie 并自动重试。建议在运行前先用 Chrome 登录 B 站，并访问一次目标用户空间。

界面默认勾选“遇到 412/352 风控时，使用 Chrome 的 B 站登录状态重试”。手动输入 BV 号时通常不需要浏览器登录状态；如果取消该勾选，UID 获取触发风控后将无法使用 Cookie 重试。

## 项目结构

```text
.
├── data/
│   └── dataset.jsonl              # 现有案例库
├── examples/
│   └── outline.txt                # 大纲示例
├── scripts/
│   ├── setup_macos.sh             # macOS 初始化
│   └── setup_windows.ps1          # Windows Python 环境初始化
├── src/bili_script_tool/
│   ├── app.py                     # 应用入口
│   ├── config.py                  # 配置、路径及跨平台命令发现
│   ├── domain.py                  # 领域数据模型
│   ├── errors.py                  # 统一异常类型
│   ├── services/
│   │   ├── ai_service.py          # 通义千问调用与提示词
│   │   ├── case_repository.py     # JSONL 案例库存取
│   │   ├── factory.py             # 服务装配
│   │   ├── media_service.py       # 下载、转码和语音转写
│   │   └── workflows.py           # 两条业务工作流
│   └── ui/
│       ├── main_window.py         # 主窗口
│       ├── case_builder_tab.py    # 案例库构建界面
│       └── script_generator_tab.py# 文案生成界面
├── tests/                         # 核心逻辑测试
├── .env.example                   # 配置示例，不包含真实密钥
├── launch_macos.command           # macOS 双击启动入口
├── pyproject.toml
├── requirements.txt
└── run.py                         # 通用开发启动入口
```

运行后是一个统一窗口，使用“案例库构建”和“文案生成”两个标签页。代码层则按照 UI、业务流程、外部服务和数据存储分开，避免把全部功能塞进单个脚本。

## macOS 安装与启动

支持 Intel Mac 和 Apple Silicon Mac。需要先安装 [Homebrew](https://brew.sh)。

### 使用当前已有的虚拟环境

项目根目录已经保留 `.venv`。如果虚拟环境已经创建，只需要自行安装系统工具和
Python 依赖：

```bash
cd "/Users/zhaoqifan/AIGC/案例库构建v1.0"

# 安装 Mac 原生媒体工具
brew install ffmpeg yt-dlp

# 安装到项目自己的虚拟环境，不影响系统 Python
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

可以用下面的命令检查环境：

```bash
.venv/bin/python --version
.venv/bin/python -c "import tkinter, dashscope, whisper; print('Tk', tkinter.TkVersion)"
ffmpeg -version
yt-dlp --version
```

### 从零初始化

如果 `.venv` 不存在，或者希望完全重建环境，也可以运行自动初始化脚本：

```bash
chmod +x scripts/setup_macos.sh launch_macos.command
./scripts/setup_macos.sh
```

然后复制或编辑 `.env`：

```dotenv
DASHSCOPE_API_KEY=你的通义千问API密钥
DASHSCOPE_ANALYSIS_MODEL=qwen-max
DASHSCOPE_GENERATION_MODEL=qwen3.7-max
WHISPER_MODEL_DIR=models/whisper
```

以上配置与重构前保持一致：案例入库的摘要和关键词分析使用 `qwen-max`，案例筛选及
最终文案生成使用 `qwen3.7-max`。Whisper 固定使用 `large-v3-turbo` 模型。

启动方式：

```bash
./launch_macos.command
```

也可以在 Finder 中双击 `launch_macos.command`。不要使用 macOS 自带的
`/usr/bin/python3` 启动：它可能链接到过旧的 Tk，无法在新版 macOS 上创建窗口。
初始化脚本会建立使用新版 Tk 的独立 Python 环境。首次使用 Whisper 时会下载 `large-v3-turbo` 模型，
请确保网络和磁盘空间充足。

## Windows 安装与启动

本项目在 Windows 上使用独立的 Conda 环境，环境名默认为 `bili-script-tool`，Python 版本为 3.11。

### 1. 安装前准备

1. 安装 [Miniconda](https://docs.conda.io/projects/miniconda/en/latest/) 或 Anaconda。推荐安装体积更小的 Miniconda。
2. 如果要通过 UID 获取视频，需要安装 Chrome、在 Chrome 中登录 B 站，并建议先访问一次目标用户空间。触发 412/352 风控时，程序会读取该登录 Cookie 重试。
3. 准备通义千问 API Key。首次使用 Whisper 时还会下载 `large-v3-turbo` 模型，请确保网络正常且磁盘空间充足。

安装 Conda 后，请使用“Anaconda Prompt”或已初始化 Conda 的 PowerShell。如果 PowerShell 无法执行 `conda activate`，先运行 `conda init powershell`，然后关闭并重新打开 PowerShell。

### 2. 进入项目目录

把下面的路径替换为项目在本机的实际路径：

```powershell
Set-Location "D:\path\to\案例库构建v1.0"
```

### 3. 自动安装

在 PowerShell 中运行：

```powershell
.\scripts\setup_windows.ps1
```

该脚本会：

- 创建 Python 3.11 Conda 环境 `bili-script-tool`；
- 通过 `conda-forge` 安装 FFmpeg；
- 安装 `requirements.txt` 中的 Python 依赖以及 `yt-dlp`；
- 当 `.env` 不存在时，从 `.env.example` 复制生成。

如果 PowerShell 禁止运行本地脚本，可仅在当前窗口临时放开限制后重试：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup_windows.ps1
```

### 4. 手动安装（可选）

如果不使用自动脚本，可以依次运行：

```powershell
conda create --name bili-script-tool python=3.11 -y
conda activate bili-script-tool
conda install --channel conda-forge ffmpeg -y
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install --upgrade "yt-dlp[default]"

Copy-Item .env.example .env
```

### 5. 配置 API Key

用文本编辑器打开项目根目录中的 `.env`，至少填写：

```dotenv
DASHSCOPE_API_KEY=你的通义千问API密钥
DASHSCOPE_ANALYSIS_MODEL=qwen-max
DASHSCOPE_GENERATION_MODEL=qwen3.7-max
WHISPER_MODEL_DIR=models/whisper
```

### 6. 检查环境

每次启动前先激活 Conda 环境，然后检查 Python 和外部命令：

```powershell
conda activate bili-script-tool
python --version
python -c "import tkinter, dashscope, whisper; print('Tk', tkinter.TkVersion)"
ffmpeg -version
yt-dlp --version
```

如果提示找不到 `ffmpeg` 或 `yt-dlp`，请先确认命令行左侧显示 `(bili-script-tool)`，表示当前 Conda 环境已激活。

### 7. 启动程序

首次运行建议保留终端窗口，方便查看报错：

```powershell
conda activate bili-script-tool
python run.py
```

如果不希望显示终端窗口，可以在环境激活后使用：

```powershell
pythonw run.py
```

项目不会提交 FFmpeg 或 yt-dlp 的第三方 `.exe` 文件；它们由 Conda 环境和 pip 管理，避免仓库内包含来源不明或过期的可执行文件。

## 开发与验证

```bash
python3 -m compileall -q src tests run.py
python3 -m unittest discover -v
```

外部依赖只在真正执行下载、转写或 AI 请求时加载，因此数据存储等核心测试不需要联网。

## 数据说明

- `data/dataset.jsonl`：每行一个案例，字段为 `uploader`、`bvid`、`title`、`text`、`summary`、`keywords`。
- `data/audio/`：运行时生成的 WAV 文件，已被 Git 忽略。
- `data/transcripts/`：运行时生成的转写文本，已被 Git 忽略。
- `models/whisper/`：Whisper 模型文件，默认保存在项目内并被 Git 忽略。
- `examples/outline.txt`：示例大纲，可以在界面中选择任意其他文本文件。

## 安全说明

API Key 不应写入 Python 代码或提交到版本控制。项目只从 `.env` 或系统环境变量读取 `DASHSCOPE_API_KEY`。如果旧版本中使用过硬编码密钥，应立即在服务后台将旧密钥作废并创建新密钥。
