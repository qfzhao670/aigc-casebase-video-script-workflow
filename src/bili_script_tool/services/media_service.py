"""Cross-platform video download and speech-to-text operations."""

from collections import deque
from contextlib import redirect_stderr
import importlib
import importlib.util
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
from typing import Callable, Optional, Sequence

from ..config import (
    PROJECT_ROOT,
    WHISPER_MODEL,
    Settings,
    require_executable,
    subprocess_environment,
)
from ..domain import VideoMetadata
from ..errors import DataValidationError, DependencyError, ExternalCommandError


LogCallback = Callable[[str], None]
ProgressCallback = Callable[[float], None]


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_PERCENT = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%")
_BVID = re.compile(r"^BV[0-9A-Za-z]{10}$", re.IGNORECASE)
_BILIBILI_RISK_ERROR = re.compile(
    r"(?:blocked|rejected) by server \((352|412)\)",
    re.IGNORECASE,
)


def _extract_percent(output: str) -> Optional[float]:
    """Extract and clamp the last percentage value from command output."""
    matches = _PERCENT.findall(_ANSI_ESCAPE.sub("", output))
    if not matches:
        return None
    return max(0.0, min(100.0, float(matches[-1])))


class _TqdmProgressStream:
    """Turn an in-process tqdm meter into ordinary progress callbacks."""

    def __init__(self, callback: Optional[ProgressCallback]):
        self.callback = callback
        self._last_percent: Optional[float] = None

    def write(self, output: str) -> int:
        percent = _extract_percent(output)
        if (
            percent is not None
            and percent != self._last_percent
            and self.callback is not None
        ):
            self._last_percent = percent
            self.callback(percent)
        return len(output)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False


def _is_apple_silicon() -> bool:
    """Return whether this process is native Apple Silicon on macOS."""
    return sys.platform == "darwin" and platform.machine().lower() in {
        "arm64",
        "aarch64",
    }


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


class MediaService:
    def __init__(
        self,
        settings: Settings,
        log: Optional[LogCallback] = None,
    ):
        self.settings = settings
        self.log = log or (lambda _message: None)
        self._mlx_whisper = None
        self._transcription_backend = (
            "mlx" if _is_apple_silicon() and _module_available("mlx_whisper") else "openai"
        )

    def check_dependencies(self) -> None:
        require_executable(
            "yt-dlp",
            "macOS 请运行 scripts/setup_macos.sh；Windows 请将 yt-dlp.exe 放到项目根目录。",
            project_root=self.settings.project_root,
        )
        require_executable(
            "ffmpeg",
            "macOS 请运行 scripts/setup_macos.sh；Windows 请将 ffmpeg.exe 放到项目根目录。",
            project_root=self.settings.project_root,
        )
        require_executable(
            "ffprobe",
            "macOS 请运行 scripts/setup_macos.sh；Windows 请将 ffprobe.exe 放到项目根目录。",
            project_root=self.settings.project_root,
        )
        if self._transcription_backend == "mlx":
            self.log(
                "语音转录后端：MLX（Apple Silicon GPU，模型将在本次运行中复用）。"
            )
        else:
            require_executable(
                "whisper",
                "请在项目的虚拟环境中安装 openai-whisper。",
                project_root=self.settings.project_root,
            )
            if _is_apple_silicon():
                self.log(
                    "未找到 mlx-whisper，已回退到 openai-whisper CPU 后端。"
                    "运行 pip install mlx-whisper 可启用 Apple Silicon 加速。"
                )
            else:
                self.log("语音转录后端：openai-whisper。")

    def _require_executable(self, name: str, install_hint: str) -> str:
        settings = getattr(self, "settings", None)
        project_root = settings.project_root if settings is not None else PROJECT_ROOT
        return require_executable(
            name,
            install_hint,
            project_root=project_root,
        )

    def _subprocess_environment(self) -> dict[str, str]:
        settings = getattr(self, "settings", None)
        project_root = settings.project_root if settings is not None else PROJECT_ROOT
        return subprocess_environment(project_root)

    def get_user_bvids(
        self,
        uid: str,
        limit: int,
        cookies_from_browser: Optional[str] = None,
    ) -> list[str]:
        """Return up to ``limit`` recent public video IDs from a Bilibili user."""
        normalized_uid = str(uid).strip()
        if not normalized_uid.isdigit() or int(normalized_uid) <= 0:
            raise DataValidationError("B 站 UID 必须是大于 0 的整数。")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise DataValidationError("抓取数量必须是 1–1000 之间的整数。")

        yt_dlp = self._require_executable(
            "yt-dlp",
            "Windows 请将 yt-dlp.exe 放到项目根目录。",
        )
        command = [
            yt_dlp,
            "--flat-playlist",
            "--playlist-end",
            str(limit),
            "--print",
            "%(id)s",
            f"https://space.bilibili.com/{normalized_uid}/video",
        ]
        try:
            result = self._run(command)
        except ExternalCommandError as exc:
            risk_match = _BILIBILI_RISK_ERROR.search(str(exc))
            if not risk_match or not cookies_from_browser:
                raise
            risk_code = risk_match.group(1)
            self.log(
                f"UID {normalized_uid} 触发 B 站 {risk_code} 风控，"
                f"正在使用 {cookies_from_browser} 登录状态重试……"
            )
            try:
                result = self._run(
                    command[:-1]
                    + ["--cookies-from-browser", cookies_from_browser, command[-1]]
                )
            except ExternalCommandError as retry_exc:
                raise ExternalCommandError(
                    f"UID {normalized_uid} 重试后仍被 B 站 {risk_code} 风控拒绝。"
                    f"请先在 {cookies_from_browser} 中登录 B 站，"
                    "访问一次该用户空间后稍后重试。"
                ) from retry_exc
        bvids = []
        seen = set()
        for line in result.stdout.splitlines():
            bvid = line.strip()
            if _BVID.fullmatch(bvid) and bvid.upper() not in seen:
                bvids.append(bvid)
                seen.add(bvid.upper())

        if not bvids:
            raise DataValidationError(
                f"未获取到 UID {normalized_uid} 的公开视频。"
                "请检查 UID、用户投稿状态或稍后重试。"
            )
        return bvids

    def get_metadata(self, bvid: str) -> VideoMetadata:
        yt_dlp = self._require_executable(
            "yt-dlp",
            "Windows 请将 yt-dlp.exe 放到项目根目录。",
        )
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

    def download_audio(
        self,
        metadata: VideoMetadata,
        progress: Optional[ProgressCallback] = None,
    ) -> Path:
        self.settings.audio_dir.mkdir(parents=True, exist_ok=True)
        audio_path = self.settings.audio_dir / f"{metadata.bvid}.wav"
        if audio_path.exists():
            self.log(f"音频已存在，跳过下载：{audio_path.name}")
            if progress:
                progress(100.0)
            return audio_path

        self.log(f"正在下载音频：{metadata.bvid}")
        if progress:
            progress(0.0)
        yt_dlp = self._require_executable(
            "yt-dlp",
            "Windows 请将 yt-dlp.exe 放到项目根目录。",
        )
        ffmpeg = self._require_executable(
            "ffmpeg",
            "Windows 请将 ffmpeg.exe 放到项目根目录。",
        )
        output_template = str(self.settings.audio_dir / "%(id)s.%(ext)s")
        self._run_streaming(
            [
                yt_dlp,
                "--ffmpeg-location",
                str(Path(ffmpeg).parent),
                "--no-playlist",
                "--newline",
                "--progress",
                "--progress-delta",
                "0.5",
                "-x",
                "--audio-format",
                "wav",
                "-o",
                output_template,
                f"https://www.bilibili.com/video/{metadata.bvid}",
            ],
            on_output=lambda output: self._handle_download_output(output, progress),
        )
        if not audio_path.exists():
            raise ExternalCommandError(f"下载完成后未找到音频文件：{audio_path}")
        if progress:
            progress(100.0)
        return audio_path

    def transcribe(
        self,
        audio_path: Path,
        progress: Optional[ProgressCallback] = None,
    ) -> str:
        self.settings.transcript_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = self.settings.transcript_dir / f"{audio_path.stem}.txt"
        if transcript_path.exists():
            self.log(f"转写已存在，跳过识别：{transcript_path.name}")
            if progress:
                progress(100.0)
            return transcript_path.read_text(encoding="utf-8")

        self.log(f"正在转写：{audio_path.name}")
        if progress:
            progress(0.0)
        if self._transcription_backend == "mlx":
            transcript = self._transcribe_with_mlx(audio_path, progress)
            transcript_path.write_text(transcript, encoding="utf-8")
        else:
            self._transcribe_with_openai(audio_path, progress)
        if not transcript_path.exists():
            raise ExternalCommandError(f"转写完成后未找到文本文件：{transcript_path}")
        if progress:
            progress(100.0)
        return transcript_path.read_text(encoding="utf-8")

    def _transcribe_with_mlx(
        self,
        audio_path: Path,
        progress: Optional[ProgressCallback] = None,
    ) -> str:
        """Transcribe with MLX; its ModelHolder keeps weights resident in-process."""
        if self._mlx_whisper is None:
            try:
                self._mlx_whisper = importlib.import_module("mlx_whisper")
            except ImportError as exc:
                raise DependencyError(
                    "未安装 mlx-whisper。请重新运行 scripts/setup_macos.sh，"
                    "或在虚拟环境中运行 pip install mlx-whisper。"
                ) from exc
            self.log(
                f"正在加载 MLX 模型 {self.settings.mlx_whisper_model}；"
                "首次使用需下载，后续视频将复用已加载模型。"
            )

        try:
            # mlx-whisper exposes its live position through tqdm rather than a
            # callback. Capture that meter so the desktop UI receives the same
            # incremental percentages as the command-line Whisper backend.
            with redirect_stderr(_TqdmProgressStream(progress)):
                result = self._mlx_whisper.transcribe(
                    str(audio_path),
                    path_or_hf_repo=self.settings.mlx_whisper_model,
                    language="zh",
                    verbose=False,
                )
        except Exception as exc:
            raise ExternalCommandError(f"MLX 语音转录失败：{exc}") from exc

        transcript = str(result.get("text", "")).strip()
        if not transcript:
            raise ExternalCommandError("MLX 语音转录未返回文本。")
        return transcript + "\n"

    def _transcribe_with_openai(
        self,
        audio_path: Path,
        progress: Optional[ProgressCallback],
    ) -> None:
        whisper = self._require_executable(
            "whisper",
            "请在项目的虚拟环境中安装 openai-whisper。",
        )
        self._run_streaming(
            [
                whisper,
                str(audio_path),
                "--language",
                "Chinese",
                "--model",
                WHISPER_MODEL,
                "--model_dir",
                str(self.settings.whisper_model_dir),
                "--verbose",
                "False",
                "--output_format",
                "txt",
                "--output_dir",
                str(self.settings.transcript_dir),
            ],
            on_output=lambda output: self._handle_transcription_output(output, progress),
        )

    def _handle_download_output(
        self,
        output: str,
        progress: Optional[ProgressCallback],
    ) -> None:
        clean_output = _ANSI_ESCAPE.sub("", output).strip()
        if not clean_output:
            return
        percent = _extract_percent(clean_output)
        if percent is not None and progress:
            progress(percent)
            return
        if clean_output.startswith(("[download] Destination", "[ExtractAudio]")):
            self.log(clean_output)

    def _handle_transcription_output(
        self,
        output: str,
        progress: Optional[ProgressCallback],
    ) -> None:
        clean_output = _ANSI_ESCAPE.sub("", output).strip()
        if not clean_output:
            return
        percent = _extract_percent(clean_output)
        if percent is not None and progress:
            progress(percent)
        elif not clean_output.startswith("UserWarning:"):
            self.log(f"Whisper：{clean_output}")

    def _run(self, command: Sequence[str]) -> subprocess.CompletedProcess:
        result = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=self._subprocess_environment(),
        )
        if result.returncode != 0:
            details = result.stderr.strip() or result.stdout.strip() or "未知错误"
            raise ExternalCommandError(f"外部命令执行失败：{details}")
        return result

    def _run_streaming(
        self,
        command: Sequence[str],
        on_output: Callable[[str], None],
    ) -> None:
        """Run a command while forwarding newline/carriage-return progress records."""
        process = subprocess.Popen(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=self._subprocess_environment(),
        )
        assert process.stdout is not None

        records = deque(maxlen=20)
        current = []
        while True:
            character = process.stdout.read(1)
            if character == "" and process.poll() is not None:
                break
            if not character:
                continue
            if character in "\r\n":
                record = "".join(current).strip()
                current.clear()
                if record:
                    records.append(record)
                    on_output(record)
            else:
                current.append(character)

        final_record = "".join(current).strip()
        if final_record:
            records.append(final_record)
            on_output(final_record)

        process.stdout.close()
        return_code = process.wait()
        if return_code != 0:
            details = "\n".join(records).strip() or "未知错误"
            raise ExternalCommandError(f"外部命令执行失败：{details}")

