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


async def test_quick_presses_each_build_on_the_previous_one(tmp_path: Path, frozen: Any) -> None:
    client = FakeClient()
    client.delay = 0.05  # the second press arrives while the first is still in flight
    family = next(s for s in client.snapshot.rooms if s.name == "Family Room")  # Cool
    before = family.controls.cooling_setpoint_c
    async with make_app(tmp_path, client).run_test(size=(100, 30)) as pilot:
        await _home_on(pilot, "Family Room")
        await pilot.press("plus", "plus")
        await _wait_for(pilot, lambda: len(client.calls) == 2)
    assert [c[2]["cool"] for c in client.calls] == pytest.approx(
        [before + STEP_C, before + 2 * STEP_C]
    )


async def test_p_on_the_room_screen_does_not_touch_schedules(tmp_path: Path, frozen: Any) -> None:
    client = FakeClient()
    async with make_app(tmp_path, client).run_test(size=(100, 30)) as pilot:
        await _home_on(pilot, "Family Room")
        await pilot.press("enter")
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, RoomScreen))
        await pilot.press("p", "P")
        await pilot.pause(0.1)
        assert not isinstance(pilot.app.screen, ConfirmScreen)
    assert client.calls == []


async def test_devices_survive_a_device_disappearing_during_recovery(
    tmp_path: Path, frozen: Any
) -> None:
    async with make_app(tmp_path).run_test(size=(100, 30)) as pilot:
        await _home_on(pilot, "Family Room")
        await pilot.press("d")
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, DevicesScreen))
        screen = pilot.app.screen
        assert isinstance(screen, DevicesScreen)
        await pilot.press("down")  # select the Family Room Dial
        selected = screen._rows[1]
        snap = pilot.app.snapshot
        recovered = replace(
            snap, controllers=[c for c in snap.controllers if c.id != selected.device_id]
        )
        pilot.app.update_snapshot(recovered)  # what stream recovery does, then refresh_units()
        screen.refresh_units()
        await pilot.pause()
        assert selected.device_id not in [r.device_id for r in screen._rows]


async def test_a_palette_theme_is_restored_on_restart(tmp_path: Path, frozen: Any) -> None:
    from quilt_hp.cli.settings import SettingsStore

    SettingsStore(tmp_path / "settings.json").update(theme="nord", dark=True)
    app = make_app(tmp_path)
    assert app.theme == "nord"
    async with app.run_test(size=(100, 30)) as pilot:
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, HomeScreen))
        pilot.app.theme = "gruvbox"
        await pilot.pause()
    assert SettingsStore(tmp_path / "settings.json").load().theme == "gruvbox"


async def test_old_settings_with_only_dark_still_apply(tmp_path: Path) -> None:
    from quilt_hp.cli.settings import SettingsStore

    SettingsStore(tmp_path / "settings.json").update(dark=False)
    assert make_app(tmp_path).theme == "textual-light"


# ── Room screen ────────────────────────────────────────────────────────────


async def _room(pilot: Pilot[Any], name: str) -> RoomScreen:
    await _home_on(pilot, name)
    await pilot.press("enter")
    await _wait_for(pilot, lambda: isinstance(pilot.app.screen, RoomScreen))
    screen = pilot.app.screen
    assert isinstance(screen, RoomScreen)
    await pilot.pause()
    return screen


async def test_room_tabs_and_room_switching_keep_the_tab(tmp_path: Path, frozen: Any) -> None:
    from textual.widgets import TabbedContent

    async with make_app(tmp_path).run_test(size=(100, 30)) as pilot:
        room = await _room(pilot, "Family Room")
        names = [s.name for s in pilot.app.snapshot.rooms]
        await pilot.press("2")
        assert room.query_one("#room-tabs", TabbedContent).active == "tab-climate"
        await pilot.press("right_square_bracket")
        await _wait_for(
            pilot,
            lambda: pilot.app.screen is not room and isinstance(pilot.app.screen, RoomScreen),
        )
        nxt = pilot.app.screen
        assert isinstance(nxt, RoomScreen)
        assert nxt.space is not None and nxt.space.name == names[names.index("Family Room") + 1]
        assert nxt.query_one("#room-tabs", TabbedContent).active == "tab-climate"
        await pilot.press("escape")  # back goes to Home, not to the previous room
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, HomeScreen))


async def test_room_controls_list(tmp_path: Path, frozen: Any) -> None:
    from textual.widgets import Input

    from quilt_hp.cli.tui.dialogs import ValueDialog

    client = FakeClient()
    family = next(s for s in client.snapshot.rooms if s.name == "Family Room")  # Cool
    before = family.controls.cooling_setpoint_c
    async with make_app(tmp_path, client).run_test(size=(100, 30)) as pilot:
        await _room(pilot, "Family Room")
        await pilot.press("down", "right")  # "Cool to", one step warmer
        await _wait_for(pilot, lambda: client.calls)
        assert client.calls[-1][2]["cool"] == pytest.approx(before + STEP_C)
        await pilot.press("enter")  # type a value
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, ValueDialog))
        field = pilot.app.screen.query_one(Input)
        field.value = "99"
        await pilot.press("enter")  # out of range: stays open with an error
        await pilot.pause()
        assert isinstance(pilot.app.screen, ValueDialog)
        field.value = "22.5"
        await pilot.press("enter")
        await _wait_for(pilot, lambda: len(client.calls) == 2)
    assert client.calls[-1][2]["cool"] == pytest.approx(22.5)


async def test_room_fan_louver_and_light_keys(tmp_path: Path, frozen: Any) -> None:
    from quilt_hp.models import FanSpeed, LouverMode

    client = FakeClient()
    async with make_app(tmp_path, client).run_test(size=(100, 30)) as pilot:
        await _room(pilot, "Family Room")  # fan auto, louver auto, light off
        await pilot.press("f")
        await _wait_for(pilot, lambda: len(client.calls) == 1)
        await pilot.press("v")
        await _wait_for(pilot, lambda: len(client.calls) == 2)
        await pilot.press("l")
        await _wait_for(pilot, lambda: len(client.calls) == 3)
    assert [(c[0], c[2]) for c in client.calls[:2]] == [
        ("set_indoor_unit", {"fan_speed": FanSpeed.QUIET}),
        ("set_indoor_unit", {"louver_mode": LouverMode.FIXED}),
    ]
    assert client.calls[2][2]["led_brightness"] > 0  # turned on


async def test_room_settings_dialog_sends_only_what_changed(tmp_path: Path, frozen: Any) -> None:
    from textual.widgets import Input

    from quilt_hp.cli.tui.dialogs import RoomSettingsScreen

    client = FakeClient()
    async with make_app(tmp_path, client).run_test(size=(100, 30)) as pilot:
        await _room(pilot, "Family Room")
        await pilot.press("s")
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, RoomSettingsScreen))
        dialog = pilot.app.screen
        dialog.query_one("#set-away_after", Input).value = "30"
        dialog.query_one("#set-radar_height", Input).value = "2.2"
        await pilot.click("#settings-save")
        await _wait_for(pilot, lambda: len(client.calls) == 2)
    assert client.calls[0] == (
        "set_space_settings",
        (next(s.id for s in client.snapshot.rooms if s.name == "Family Room"),),
        {"unoccupied_timeout_s": 1800.0, "occupied_timeout_s": None},
    )
    name, _args, kwargs = client.calls[1]
    assert name == "set_indoor_unit_settings"
    assert kwargs["radar_height_m"] == pytest.approx(2.2)
    assert kwargs["fence_left_m"] is None and kwargs["light_brightness_default"] is None


async def test_room_raw_toggle_and_offline_dial(tmp_path: Path, frozen: Any) -> None:
    from textual.widgets import Static

    async with make_app(tmp_path).run_test(size=(100, 30)) as pilot:
        room = await _room(pilot, "Primary Bedroom")  # its Dial is offline
        await pilot.press("2")
        raw = room.query_one("#cl-raw", Static)
        assert not raw.display
        await pilot.press("r")
        assert raw.display
        presence = str(room.query_one("#cl-presence", Static).render())
        assert "offline" in presence and "Dial radar" not in presence


async def test_room_follows_live_updates_and_closes_when_removed(
    tmp_path: Path, frozen: Any
) -> None:
    async with make_app(tmp_path).run_test(size=(100, 30)) as pilot:
        room = await _room(pilot, "Family Room")
        space = room.space
        assert space is not None
        cooler = replace(space, controls=replace(space.controls, cooling_setpoint_c=21.0))
        pilot.app._dispatch_space(cooler)
        await pilot.pause()
        assert room.space is not None and room.space.controls.cooling_setpoint_c == 21.0
        pilot.app._dispatch_delete("space", space.id)
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, HomeScreen))


async def test_energy_screen_ranks_rooms_and_sums_the_house(tmp_path: Path, frozen: Any) -> None:
    from quilt_hp.cli.tui import EnergyScreen

    async with make_app(tmp_path).run_test(size=(100, 30)) as pilot:
        await _home_on(pilot, "Family Room")
        await pilot.press("e")
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, EnergyScreen))
        screen = pilot.app.screen
        await _wait_for(pilot, lambda: screen._house is not None)
        rooms = list(screen._rooms.values())
        assert screen._house.today_kwh == pytest.approx(sum(r.today_kwh for r in rooms))
        assert screen.query_one("#en-rooms", DataTable).row_count == len(pilot.app.snapshot.rooms)
        await pilot.press("escape")
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, HomeScreen))


async def test_help_lists_every_screens_keys(tmp_path: Path, frozen: Any) -> None:
    from textual.widgets import Static

    from quilt_hp.cli.tui.help import HelpScreen

    async with make_app(tmp_path).run_test(size=(100, 30)) as pilot:
        await _room(pilot, "Family Room")
        await pilot.press("question_mark")
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, HelpScreen))
        text = str(pilot.app.screen.query_one(Static).render())
        for expected in (
            "Previous / next room",
            "Raise / lower the setpoint",
            "Pause/resume schedules",
            "Raw telemetry",
        ):
            assert expected in text
        await pilot.press("escape")
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, RoomScreen))


async def test_energy_lists_rooms_without_energy_history(tmp_path: Path, frozen: Any) -> None:
    from quilt_hp.cli.tui import EnergyScreen

    class PartialClient(FakeClient):
        async def get_energy(self, start: Any, end: Any) -> Any:
            metrics = await super().get_energy(start, end)
            return metrics[1:]  # the first room has no history

    client = PartialClient()
    async with make_app(tmp_path, client).run_test(size=(100, 30)) as pilot:
        await _home_on(pilot, "Family Room")
        await pilot.press("e")
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, EnergyScreen))
        screen = pilot.app.screen
        await _wait_for(pilot, lambda: screen._house is not None)
        assert screen.query_one("#en-rooms", DataTable).row_count == len(client.snapshot.rooms)
        assert screen._rooms[client.snapshot.rooms[0].id].last_30_days_kwh == 0.0


async def test_room_catches_up_after_help_closes(tmp_path: Path, frozen: Any) -> None:
    from textual.widgets import OptionList

    from quilt_hp.cli.tui.help import HelpScreen

    async with make_app(tmp_path).run_test(size=(100, 30)) as pilot:
        room = await _room(pilot, "Family Room")
        await pilot.press("question_mark")
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, HelpScreen))
        space = room.space
        assert space is not None
        pilot.app._dispatch_space(
            replace(space, controls=replace(space.controls, cooling_setpoint_c=21.0))
        )  # arrives while Help is on top
        await pilot.press("escape")
        await _wait_for(pilot, lambda: pilot.app.screen is room)
        await pilot.pause()
        prompt = room.query_one("#ov-controls", OptionList).get_option("cool").prompt
        assert "21.0" in str(prompt)


async def test_room_removed_while_help_is_open_closes_after_help(
    tmp_path: Path, frozen: Any
) -> None:
    from quilt_hp.cli.tui.help import HelpScreen

    async with make_app(tmp_path).run_test(size=(100, 30)) as pilot:
        room = await _room(pilot, "Family Room")
        await pilot.press("question_mark")
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, HelpScreen))
        pilot.app._dispatch_delete("space", room.space_id)
        await pilot.pause()
        assert isinstance(pilot.app.screen, HelpScreen)  # the dialog isn't closed for it
        await pilot.press("escape")
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, HomeScreen))


async def _devices_on(pilot: Pilot[Any], kind: str, room: str) -> DevicesScreen:
    await _wait_for(pilot, lambda: isinstance(pilot.app.screen, HomeScreen))
    await pilot.press("d")
    await _wait_for(pilot, lambda: isinstance(pilot.app.screen, DevicesScreen))
    screen = pilot.app.screen
    assert isinstance(screen, DevicesScreen)
    rows = screen._rows
    index = next(i for i, r in enumerate(rows) if r.kind.name == kind and r.room == room)
    screen.query_one("#devices-table", DataTable).move_cursor(row=index)
    await pilot.pause()
    return screen


async def test_t_runs_a_self_test_after_confirming(tmp_path: Path, frozen: Any) -> None:
    client = FakeClient()
    async with make_app(tmp_path, client).run_test(size=(100, 30)) as pilot:
        await _devices_on(pilot, "INDOOR_UNIT", "Family Room")
        await pilot.press("t")
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, ConfirmScreen))
        assert "30 minutes" in str(pilot.app.screen.query_one("#confirm-detail").render())
        await pilot.press("y")
        await _wait_for(pilot, lambda: client.calls)
    name, (idu,), _ = client.calls[0]
    family = next(s for s in client.snapshot.rooms if s.name == "Family Room")
    assert name == "start_self_test" and idu.space_id == family.id


async def test_dial_keys_only_act_on_a_dial(tmp_path: Path, frozen: Any) -> None:
    client = FakeClient()
    async with make_app(tmp_path, client).run_test(size=(100, 30)) as pilot:
        screen = await _devices_on(pilot, "INDOOR_UNIT", "Dining Room")
        assert screen.check_action("dial_sensor", ()) is None  # dimmed in the footer
        await pilot.press("s")
        await pilot.pause()
        assert isinstance(pilot.app.screen, DevicesScreen) and not client.calls

        dining = next(s for s in client.snapshot.rooms if s.name == "Dining Room")
        dial = next(c for c in client.snapshot.controllers if c.space_id == dining.id)
        index = next(i for i, r in enumerate(screen._rows) if r.device_id == dial.id)
        screen.query_one("#devices-table", DataTable).move_cursor(row=index)
        await pilot.pause()
        await pilot.press("s")
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, ConfirmScreen))
        await pilot.press("y")
        await _wait_for(pilot, lambda: client.calls)
        assert client.calls[-1] == (
            "set_controller",
            (dial,),
            {"name": None, "uses_dial_temperature": not dial.uses_dial_temperature},
        )

        await pilot.press("n")
        await _wait_for(pilot, lambda: pilot.app.screen.__class__.__name__ == "TextDialog")
        field = pilot.app.screen.query_one("#text-input")
        field.value = "Dining Dial"  # type: ignore[attr-defined]
        await pilot.press("enter")
        await _wait_for(pilot, lambda: len(client.calls) == 2)
        assert client.calls[-1][2] == {"name": "Dining Dial", "uses_dial_temperature": None}


async def test_shift_o_turns_the_whole_house_off(tmp_path: Path, frozen: Any) -> None:
    from quilt_hp.models import ClimateMode

    client = FakeClient()
    async with make_app(tmp_path, client).run_test(size=(100, 30)) as pilot:
        await _home_on(pilot, "Family Room")
        await pilot.press("O")
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, ConfirmScreen))
        await pilot.press("y")
        await _wait_for(pilot, lambda: client.calls)
    assert client.calls[0] == ("apply_mode", (ClimateMode.OFF,), {"whole_house": True})
