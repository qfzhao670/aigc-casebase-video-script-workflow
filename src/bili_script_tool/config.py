"""Cross-platform paths, environment loading, and executable discovery."""

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sys
from typing import Dict, Optional

from .errors import ConfigurationError, DependencyError


PROJECT_ROOT = Path(__file__).resolve().parents[2]

WHISPER_MODEL_FILES = {
    "tiny": "tiny.pt",
    "base": "base.pt",
    "small": "small.pt",
    "medium": "medium.pt",
    "turbo": "large-v3-turbo.pt",
    "large-v3": "large-v3.pt",
}


def installed_whisper_models(model_dir: Path) -> list:
    """Return supported multilingual models already present in the project."""
    return [
        model_name
        for model_name, filename in WHISPER_MODEL_FILES.items()
        if (model_dir / filename).is_file()
    ]


def load_dotenv(path: Path) -> None:
    """Load a small KEY=VALUE environment file without another dependency."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def subprocess_environment() -> Dict[str, str]:
    """Return an environment that also works when launched from macOS Finder."""
    env = os.environ.copy()
    current_path = env.get("PATH", "")
    preferred = [
        str(Path(sys.executable).resolve().parent),
        "/opt/homebrew/bin",
        "/usr/local/bin",
    ]
    path_entries = preferred + [entry for entry in current_path.split(os.pathsep) if entry]
    env["PATH"] = os.pathsep.join(dict.fromkeys(path_entries))
    return env


def find_executable(name: str) -> Optional[str]:
    return shutil.which(name, path=subprocess_environment()["PATH"])


def require_executable(name: str, install_hint: str) -> str:
    executable = find_executable(name)
    if executable:
        return executable
    raise DependencyError(f"未找到 {name}。{install_hint}")


@dataclass(frozen=True)
class Settings:
    project_root: Path
    data_dir: Path
    audio_dir: Path
    transcript_dir: Path
    default_library: Path
    default_outline: Path
    dashscope_api_key: str
    dashscope_analysis_model: str
    dashscope_generation_model: str
    whisper_model: str
    whisper_model_dir: Path

    @classmethod
    def from_environment(cls, project_root: Path = PROJECT_ROOT) -> "Settings":
        load_dotenv(project_root / ".env")
        data_dir = Path(os.environ.get("BILI_SCRIPT_DATA_DIR", project_root / "data"))
        whisper_model_dir = Path(
            os.environ.get("WHISPER_MODEL_DIR", project_root / "models" / "whisper")
        )
        if not whisper_model_dir.is_absolute():
            whisper_model_dir = project_root / whisper_model_dir
        return cls(
            project_root=project_root,
            data_dir=data_dir,
            audio_dir=data_dir / "audio",
            transcript_dir=data_dir / "transcripts",
            default_library=data_dir / "dataset.jsonl",
            default_outline=project_root / "examples" / "outline.txt",
            dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY", "").strip(),
            dashscope_analysis_model=os.environ.get(
                "DASHSCOPE_ANALYSIS_MODEL",
                os.environ.get("DASHSCOPE_MODEL", "qwen-max"),
            ).strip(),
            dashscope_generation_model=os.environ.get(
                "DASHSCOPE_GENERATION_MODEL",
                os.environ.get("DASHSCOPE_MODEL", "qwen3.7-max"),
            ).strip(),
            whisper_model=os.environ.get("WHISPER_MODEL", "small").strip(),
            whisper_model_dir=whisper_model_dir,
        )

    def ensure_work_directories(self) -> None:
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.transcript_dir.mkdir(parents=True, exist_ok=True)
        self.whisper_model_dir.mkdir(parents=True, exist_ok=True)

    def require_api_key(self) -> str:
        if not self.dashscope_api_key:
            raise ConfigurationError(
                "未配置 DASHSCOPE_API_KEY。请复制 .env.example 为 .env，并填写 API Key。"
            )
        return self.dashscope_api_key

