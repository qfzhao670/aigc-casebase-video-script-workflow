# Bilibili 视频文案工具

这是一个跨平台桌面工具，包含两个相互衔接的功能：

1. **案例库构建**：可一次输入多个 B 站用户 UID，自动获取每个用户最近 N 条公开投稿的 BV 号，也可手动输入 BV 号；随后下载音频、使用 Whisper 转写、调用通义千问生成摘要和关键词，并写入 JSONL 案例库。
2. **文案生成**：根据创作需求筛选参考案例，结合人工大纲和自定义要求生成新的视频文案。

案例库构建页会实时显示整体进度、音频下载进度和 Whisper 语音转录进度，
并在执行日志中保留带时间戳的阶段记录。转录固定使用 `large-v3-turbo` 模型。
在 UID 模式下，每行输入一个纯数字 UID，并设置每个 UID 的获取数量（1–1000）后点击“开始构建”。
工具会合并去重所有获取到的 BV 号、回填到界面，再自动进入原有入库流程。
如果 B 站对用户空间接口返回 412 或 352 风控，界面默认会使用 Chrome 中的 B 站登录状态自动重试。
使用前请确保 Chrome 已登录 B 站；不希望读取浏览器 Cookie 时，可在页面上取消勾选。

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

安装 Python 3.11、FFmpeg 和 yt-dlp，并保证 `ffmpeg`、`yt-dlp` 可以从 `PATH` 找到。然后在 PowerShell 中运行：

```powershell
.\scripts\setup_windows.ps1
.\.venv\Scripts\pythonw.exe run.py
```

不再把第三方 `.exe` 提交到项目中；这能避免来源不明、版本过期以及仓库体积过大的问题。

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
