"""The TUI screenshots in the docs must match the render-test snapshots."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "update_tui_screenshots.py"
_spec = importlib.util.spec_from_file_location("update_tui_screenshots", _SCRIPT)
assert _spec is not None and _spec.loader is not None
screens = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(screens)


@pytest.mark.parametrize("name", screens.SCREENS)
def test_docs_screenshot_matches_snapshot(name: str) -> None:
    docs_copy = screens.DOCS / f"{name}.svg"
    assert docs_copy.read_bytes() == screens.source(name).read_bytes(), (
        f"docs/assets/tui/{name}.svg is stale; run python scripts/update_tui_screenshots.py"
    )
