"""Development launcher that works without installing the package."""

from pathlib import Path
import sys


SOURCE_DIR = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SOURCE_DIR))

from bili_script_tool.app import main  # noqa: E402


if __name__ == "__main__":
    main()

