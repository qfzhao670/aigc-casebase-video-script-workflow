# Bilibili 视频文案工具

这是一个跨平台桌面工具，包含两个相互衔接的功能：

1. **案例库构建**：可一次输入多个 B 站用户 UID，自动获取每个用户最近 N 条公开投稿的 BV 号，也可手动输入 BV 号；随后下载音频、使用 Whisper 转写、调用通义千问生成摘要和关键词，并写入 JSONL 案例库。
2. **文案生成**：根据创作需求筛选参考案例，结合人工大纲和自定义要求生成新的视频文案。

案例库构建页会将整体、音频下载、Whisper 语音转录、分析入库分成
独立的实时进度行，同时显示当前序号和 BV 号。事件日志只保留带时间戳的
分类阶段事件与异常，不再反复追加百分比。转录使用 `large-v3-turbo`
模型：Apple Silicon Mac 会自动使用 MLX GPU 后端，其他环境使用
`openai-whisper`；两种后端的转录百分比都会尽可能实时更新。同一批任务中
模型只加载一次。

处理多个视频时会自动使用流水线：当前视频转录时预下载下一条，
下一条转录时并行分析上一条的摘要和关键词。转录本身仍保持单路，
避免同时加载多份模型占满统一内存。
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
│   └── setup_windows.ps1          # Windows PyCharm 虚拟环境依赖安装
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
# 仅 Apple Silicon Mac 需要检查此项
.venv/bin/python -c "import mlx_whisper; print('MLX Whisper OK')"
ffmpeg -version
yt-dlp --version
```

如果现有 `.venv` 还没有 MLX，Apple Silicon Mac 只需补装这一项：

```bash
cd "/Users/zhaoqifan/AIGC/案例库构建v1.0"
.venv/bin/python -m pip install --timeout 600 "mlx-whisper>=0.4.3"
```

安装包约需下载 70MB 的 Metal 运行库。首次真正转录时还会自动下载
`mlx-community/whisper-large-v3-turbo` 模型；下载后会由 Hugging Face
缓存，不会每次重新下载。

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
MLX_WHISPER_MODEL=mlx-community/whisper-large-v3-turbo
```

以上配置与重构前保持一致：案例入库的摘要和关键词分析使用 `qwen-max`，案例筛选及
最终文案生成使用 `qwen3.7-max`。Whisper 固定使用 `large-v3-turbo` 模型。

启动方式：

```bash
./launch_macos.command
```

也可以在 Finder 中双击 `launch_macos.command`。不要使用 macOS 自带的
`/usr/bin/python3` 启动：它可能链接到过旧的 Tk，无法在新版 macOS 上创建窗口。
初始化脚本会建立使用新版 Tk 的独立 Python 环境。Apple Silicon Mac
首次转录时会从 Hugging Face 下载 MLX 版 `large-v3-turbo` 模型；
后续视频会复用内存中的模型。请确保网络和磁盘空间充足。

## Windows 安装与启动

本项目在 Windows 上使用 **PyCharm 创建的项目虚拟环境 `.venv`**，不再使用 Conda。
FFmpeg 和 yt-dlp 也不通过 Conda、pip 或安装脚本下载，而是将已准备好的
Windows 可执行文件手动放到项目根目录。程序会优先使用这些本地文件，
不需要修改 Windows 的系统 `PATH`。建议使用 64 位 Python 3.11。

### 1. 安装前准备

1. 安装 64 位 Python 3.11 和 PyCharm。
2. 准备与 Windows 架构匹配的 `ffmpeg.exe`、`ffprobe.exe`、`ffplay.exe`、`yt-dlp.exe`。
   这些文件由使用者手动复制，项目脚本不会自动下载或替换它们。
3. 如果要通过 UID 获取视频，需要安装 Chrome、在 Chrome 中登录 B 站，并建议先访问一次目标用户空间。触发 412/352 风控时，程序会读取该登录 Cookie 重试。
4. 准备通义千问 API Key。Whisper 固定使用 `large-v3-turbo` 模型；如果项目的
   `models/whisper/large-v3-turbo.pt` 尚未手动准备，Whisper 首次运行时仍需下载模型。

### 2. 放置 Windows 工具

将四个 `.exe` 直接放在项目根目录，和 `run.py` 处在同一层：

```text
案例库构建v1.0\
├── ffmpeg.exe
├── ffprobe.exe
├── ffplay.exe
├── yt-dlp.exe
├── run.py
├── requirements.txt
└── ...
```

这四个文件不需要复制到 `System32`，也不需要添加到系统环境变量。

### 3. 在 PyCharm 中创建虚拟环境

1. 用 PyCharm 打开项目根目录。
2. 打开 **File > Settings > Project > Python Interpreter**。
3. 选择 **Add Interpreter > Add Local Interpreter > Virtualenv Environment > New**。
4. `Location` 设为项目下的 `.venv`，`Base interpreter` 选择 Python 3.11，然后确认创建。

创建后应存在：

```text
案例库构建v1.0\.venv\Scripts\python.exe
```

### 4. 安装 Python 依赖

打开 PyCharm 底部的 **Terminal**，确认当前位置是项目根目录，然后运行：

```powershell
.\scripts\setup_windows.ps1
```

该脚本会：

- 检查 PyCharm 创建的 `.venv\Scripts\python.exe`；
- 检查项目根目录中的四个 `.exe`，但不下载它们；
- 仅将 `requirements.txt` 中的 Python 包安装到该 `.venv`；
- 当 `.env` 不存在时，从 `.env.example` 复制生成。

如果 PowerShell 禁止运行本地脚本，可仅在当前窗口临时放开限制后重试：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup_windows.ps1
```

Python 依赖必须通过 pip 安装；已安装齐全时可跳过该脚本。如果不使用脚本，
也可在 PyCharm Terminal 中手动运行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

### 5. 配置 API Key

用文本编辑器打开项目根目录中的 `.env`，至少填写：

```dotenv
DASHSCOPE_API_KEY=你的通义千问API密钥
DASHSCOPE_ANALYSIS_MODEL=qwen-max
DASHSCOPE_GENERATION_MODEL=qwen3.7-max
WHISPER_MODEL_DIR=models/whisper
MLX_WHISPER_MODEL=mlx-community/whisper-large-v3-turbo
```

### 6. 检查环境

在 PyCharm Terminal 中检查项目解释器和本地工具：

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -c "import tkinter, dashscope, whisper; print('Tk', tkinter.TkVersion)"
.\ffmpeg.exe -version
.\ffprobe.exe -version
.\ffplay.exe -version
.\yt-dlp.exe --version
```

如果某个 `.exe` 无法运行，请确认文件名没有被 Windows 隐藏扩展名后变成
`ffmpeg.exe.exe`，并确认它与当前 Windows 架构匹配。

### 7. 启动程序

在 PyCharm 中右键单击 `run.py`，选择 **Run 'run'**。请确认运行配置使用项目的
`.venv` 解释器，`Working directory` 为项目根目录。

也可在 PyCharm Terminal 中启动：

```powershell
.\.venv\Scripts\python.exe run.py
```

如果不希望显示终端窗口，可使用：

```powershell
.\.venv\Scripts\pythonw.exe run.py
```

以上 `.exe` 是本机手动放置的运行工具，已在 `.gitignore` 中排除，不会被 Git 误提交。

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
- `models/whisper/`：`openai-whisper` 模型文件，默认保存在项目内并被 Git 忽略。
- MLX 模型由 Hugging Face 缓存管理，可用 `MLX_WHISPER_MODEL` 替换为其他兼容模型。
- `examples/outline.txt`：示例大纲，可以在界面中选择任意其他文本文件。

## 安全说明

API Key 不应写入 Python 代码或提交到版本控制。项目只从 `.env` 或系统环境变量读取 `DASHSCOPE_API_KEY`。如果旧版本中使用过硬编码密钥，应立即在服务后台将旧密钥作废并创建新密钥。
