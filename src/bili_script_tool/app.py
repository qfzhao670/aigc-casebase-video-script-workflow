"""Application entry point."""

import platform
import tkinter

from .config import Settings
from .ui.main_window import MainWindow


def validate_gui_runtime() -> None:
    if platform.system() == "Darwin" and tkinter.TkVersion < 8.6:
        raise SystemExit(
            "当前 Python 使用过旧的 Tk 版本，无法在此 macOS 上启动界面。\n"
            "请运行 ./scripts/setup_macos.sh，然后使用 ./launch_macos.command 启动。"
        )


def main() -> None:
    validate_gui_runtime()
    settings = Settings.from_environment()
    settings.ensure_work_directories()
    window = MainWindow(settings)
    window.mainloop()
