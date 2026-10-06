"""SVG snapshot tests of every TUI screen, rendered offline from the scrubbed fixture system.

Update the snapshots after an intended visual change with
``pytest tests/test_tui_snapshots.py --snapshot-update`` and review the diff.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("textual")
pytest.importorskip("pytest_textual_snapshot")

import time_machine
from textual.widgets import DataTable, TabbedContent

from quilt_hp.cli.tui import DevicesScreen, HomeScreen, RoomScreen
from tests.tui_harness import FROZEN_NOW, make_app

if TYPE_CHECKING:
    from textual.pilot import Pilot

SIZES = [(100, 30), (160, 45)]
ROOM = "Family Room"
ROOM_TABS = {
    "room-status": "tab-status",
    "room-performance": "tab-perf",
    "room-schedule": "tab-schedule",
    "room-energy": "tab-energy",
}


async def _wait_for(pilot: Pilot[Any], condition: Callable[[], bool]) -> None:
    for _ in range(200):
        await pilot.pause(0.02)
        if condition():
            return
    raise AssertionError("timed out waiting for the TUI")


async def _home(pilot: Pilot[Any]) -> HomeScreen:
    app = pilot.app
    await _wait_for(pilot, lambda: isinstance(app.screen, HomeScreen))
    home = app.screen
    assert isinstance(home, HomeScreen)
    return home


async def _select_room(pilot: Pilot[Any], name: str) -> HomeScreen:
    home = await _home(pilot)
    ids = [s.id for s in home.snapshot.rooms]
    target = next(s.id for s in home.snapshot.rooms if s.name == name)
    home.query_one("#home-rooms", DataTable).move_cursor(row=ids.index(target))
    await pilot.pause()
    return home


async def _open_room(pilot: Pilot[Any]) -> None:
    await _select_room(pilot, ROOM)
    await pilot.press("enter")
    await _wait_for(pilot, lambda: isinstance(pilot.app.screen, RoomScreen))


def _scenario(screen: str) -> Callable[[Pilot[Any]], Awaitable[None]]:
    async def run_before(pilot: Pilot[Any]) -> None:
        app = pilot.app
        if screen == "home":
            await _select_room(pilot, "Primary Bedroom")  # the room with the offline Dial
        elif screen.startswith("devices"):
            await _home(pilot)
            await pilot.press("d")
            await _wait_for(pilot, lambda: isinstance(app.screen, DevicesScreen))
            if screen == "devices-raw":
                await pilot.press("down", "down", "down", "down", "down", "r")
        else:
            await _open_room(pilot)
            app.screen.query_one("#room-tabs", TabbedContent).active = ROOM_TABS[screen]
        await pilot.pause(0.3)  # let workers (energy fetch) finish and the screen settle

    return run_before


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize("screen", ["home", *ROOM_TABS, "devices", "devices-raw"])
def test_screen(snap_compare: Any, tmp_path: Path, screen: str, size: tuple[int, int]) -> None:
    with time_machine.travel(FROZEN_NOW, tick=False):
        app = make_app(tmp_path)
        assert snap_compare(app, terminal_size=size, run_before=_scenario(screen))
