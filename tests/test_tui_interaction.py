"""Drive the TUI with real keypresses against the fake client and check what reaches the server."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("textual")

import time_machine
from textual.widgets import DataTable

from quilt_hp.cli.tui import DevicesScreen, HomeScreen, RoomScreen
from quilt_hp.cli.tui.controls import STEP_C
from quilt_hp.cli.tui.dialogs import ConfirmScreen
from tests.tui_harness import FROZEN_NOW, FakeClient, make_app

if TYPE_CHECKING:
    from textual.pilot import Pilot


async def _wait_for(pilot: Pilot[Any], condition: Any) -> None:
    for _ in range(200):
        await pilot.pause(0.02)
        if condition():
            return
    raise AssertionError("timed out waiting for the TUI")


async def _home_on(pilot: Pilot[Any], room: str) -> HomeScreen:
    await _wait_for(pilot, lambda: isinstance(pilot.app.screen, HomeScreen))
    home = pilot.app.screen
    assert isinstance(home, HomeScreen)
    ids = [s.id for s in home.snapshot.rooms]
    target = next(s.id for s in home.snapshot.rooms if s.name == room)
    home.query_one("#home-rooms", DataTable).move_cursor(row=ids.index(target))
    await pilot.pause()
    return home


@pytest.fixture
def frozen() -> Any:
    with time_machine.travel(FROZEN_NOW, tick=False) as traveller:
        yield traveller


async def test_plus_raises_the_cooling_setpoint_of_the_selected_room(
    tmp_path: Path, frozen: Any
) -> None:
    client = FakeClient()
    family = next(s for s in client.snapshot.rooms if s.name == "Family Room")  # Cool
    before = family.controls.cooling_setpoint_c
    async with make_app(tmp_path, client).run_test(size=(100, 30)) as pilot:
        await _home_on(pilot, "Family Room")
        await pilot.press("plus")
        await _wait_for(pilot, lambda: client.calls)
    name, args, kwargs = client.calls[0]
    assert (name, args) == ("set_space", (family.id,))
    assert kwargs["cool"] == pytest.approx(before + STEP_C)
    assert kwargs["heat"] is None and kwargs["mode"] is None


async def test_plus_in_standby_explains_instead_of_sending(tmp_path: Path, frozen: Any) -> None:
    client = FakeClient()
    async with make_app(tmp_path, client).run_test(size=(100, 30)) as pilot:
        await _home_on(pilot, "Office")  # Standby
        await pilot.press("plus")
        await pilot.pause(0.1)
        assert any("has no setpoint" in str(n.message) for n in pilot.app._notifications)
    assert client.calls == []


async def test_pausing_schedules_needs_confirmation(tmp_path: Path, frozen: Any) -> None:
    client = FakeClient()  # the fixture system has schedules paused
    async with make_app(tmp_path, client).run_test(size=(100, 30)) as pilot:
        await _home_on(pilot, "Family Room")
        await pilot.press("P")
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, ConfirmScreen))
        await pilot.press("escape")  # cancel: nothing is sent
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, HomeScreen))
        assert client.calls == []
        await pilot.press("P")
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, ConfirmScreen))
        await pilot.press("y")
        await _wait_for(pilot, lambda: client.calls)
    assert client.calls == [("set_schedule_execution", (False,), {})]


async def test_enter_opens_the_room_and_d_opens_devices(tmp_path: Path, frozen: Any) -> None:
    async with make_app(tmp_path).run_test(size=(100, 30)) as pilot:
        await _home_on(pilot, "Dining Room")
        await pilot.press("enter")
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, RoomScreen))
        assert pilot.app.screen.space_id == next(
            s.id for s in pilot.app.snapshot.rooms if s.name == "Dining Room"
        )
        await pilot.press("escape")
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, HomeScreen))
        await pilot.press("d")
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, DevicesScreen))


async def test_a_dial_coming_back_online_clears_the_alert(tmp_path: Path, frozen: Any) -> None:
    async with make_app(tmp_path).run_test(size=(100, 30)) as pilot:
        home = await _home_on(pilot, "Primary Bedroom")
        assert home._alerts[0].title == "Primary Bedroom Dial offline"
        snap = pilot.app.snapshot
        dial = next(c for c in snap.controllers if not c.is_online)
        fresh = replace(dial, state_updated_at=FROZEN_NOW - timedelta(seconds=5))
        pilot.app._dispatch_ctrl(fresh)  # as the notifier stream would
        await pilot.pause()
        assert "Primary Bedroom Dial offline" not in [a.title for a in home._alerts]
