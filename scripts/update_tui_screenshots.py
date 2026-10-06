#!/usr/bin/env python3
"""Copy the TUI screenshots used in the docs from the render-test snapshots.

Run after ``pytest tests/test_tui_snapshots.py --snapshot-update`` changes a screen;
``tests/test_tui_screenshots.py`` fails while the docs copies differ.
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS = ROOT / "tests" / "__snapshots__" / "test_tui_snapshots"
DOCS = ROOT / "docs" / "assets" / "tui"
SCREENS = ("home", "devices", "room-overview", "room-climate", "energy", "help")
SIZE = "160x45"


def source(name: str) -> Path:
    return SNAPSHOTS / f"test_screen[{name}-{SIZE}].svg"


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    for name in SCREENS:
        shutil.copyfile(source(name), DOCS / f"{name}.svg")
        print(f"updated docs/assets/tui/{name}.svg")


if __name__ == "__main__":
    main()
