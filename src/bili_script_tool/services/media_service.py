"""Cross-platform video download and speech-to-text operations."""

import json
from pathlib import Path
import subprocess
from typing import Callable, Optional, Sequence

from ..config import Settings, require_executable, subprocess_environment
from ..domain import VideoMetadata
from ..errors import ExternalCommandError


LogCallback = Callable[[str], None]


class MediaService:
    def __init__(self, settings: Settings, log: Optional[LogCallback] = None):
        self.settings = settings
        self.log = log or (lambda _message: None)

    def check_dependencies(self) -> None:
        require_executable(
            "yt-dlp",
            "macOS 请运行 scripts/setup_macos.sh，Windows 请安装 yt-dlp 并加入 PATH。",
        )
        require_executable(
            "ffmpeg",
            "macOS 请运行 scripts/setup_macos.sh，Windows 请安装 FFmpeg 并加入 PATH。",
        )
        require_executable(
            "whisper",
            "请在项目虚拟环境中安装 openai-whisper。",
        )

    def get_metadata(self, bvid: str) -> VideoMetadata:
        yt_dlp = require_executable("yt-dlp", "请安装 yt-dlp 并加入 PATH。")
        result = self._run(
            [
                yt_dlp,
                "--dump-single-json",
                "--skip-download",
                "--no-playlist",
                f"https://www.bilibili.com/video/{bvid}",
            ]
        )
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ExternalCommandError("yt-dlp 返回了无法解析的视频信息") from exc

        resolved_bvid = str(value.get("id", bvid)).strip() or bvid
        return VideoMetadata(
            uploader=str(value.get("uploader", "Unknown")).strip() or "Unknown",
            bvid=resolved_bvid,
            title=str(value.get("title", "Untitled")).strip() or "Untitled",
        )

    def download_audio(self, metadata: VideoMetadata) -> Path:
        self.settings.audio_dir.mkdir(parents=True, exist_ok=True)
        audio_path = self.settings.audio_dir / f"{metadata.bvid}.wav"
        if audio_path.exists():
            self.log(f"音频已存在，跳过下载：{audio_path.name}")
            return audio_path

        self.log(f"正在下载音频：{metadata.bvid}")
        yt_dlp = require_executable("yt-dlp", "请安装 yt-dlp 并加入 PATH。")
        output_template = str(self.settings.audio_dir / "%(id)s.%(ext)s")
        self._run(
            [
                yt_dlp,
                "--no-playlist",
                "--no-progress",
                "-x",
                "--audio-format",
                "wav",
                "-o",
                output_template,
                f"https://www.bilibili.com/video/{metadata.bvid}",
            ]
        )
        if not audio_path.exists():
            raise ExternalCommandError(f"下载完成后未找到音频文件：{audio_path}")
        return audio_path

    def transcribe(self, audio_path: Path) -> str:
        self.settings.transcript_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = self.settings.transcript_dir / f"{audio_path.stem}.txt"
        if transcript_path.exists():
            self.log(f"转写已存在，跳过识别：{transcript_path.name}")
            return transcript_path.read_text(encoding="utf-8")

        self.log(f"正在转写：{audio_path.name}")
        whisper = require_executable("whisper", "请安装 openai-whisper 并加入 PATH。")
        self._run(
            [
                whisper,
                str(audio_path),
                "--language",
                "Chinese",
                "--model",
                self.settings.whisper_model,
                "--output_format",
                "txt",
                "--output_dir",
                str(self.settings.transcript_dir),
            ]
        )
        if not transcript_path.exists():
            raise ExternalCommandError(f"转写完成后未找到文本文件：{transcript_path}")
        return transcript_path.read_text(encoding="utf-8")

    def _run(self, command: Sequence[str]) -> subprocess.CompletedProcess:
        result = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=subprocess_environment(),
        )
        if result.returncode != 0:
            details = result.stderr.strip() or result.stdout.strip() or "未知错误"
            raise ExternalCommandError(f"外部命令执行失败：{details}")
        return result

