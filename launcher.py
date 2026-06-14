#!/usr/bin/env python3
"""ASCII entry point for the Japanese launcher filename.

Windows batch files can be fragile when they reference non-ASCII filenames.
Keep this tiny wrapper as the stable command-line target.
"""

from pathlib import Path
import runpy


if __name__ == "__main__":
    launcher_path = Path(__file__).with_name("ランチャー.py")
    runpy.run_path(str(launcher_path), run_name="__main__")
