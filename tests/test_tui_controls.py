"""Control decisions shared by the Home and Room screens, and the room/device views."""

from __future__ import annotations

from dataclasses import replace

import pytest

pytest.importorskip("textual")

import time_machine

from quilt_hp.cli.tui.controls import STEP_C, STEP_F_IN_C, next_mode, nudge_setpoint
from quilt_hp.cli.tui.views import DeviceKind, device_views, room_views
from quilt_hp.models import HVACMode, OccupancyState
from quilt_hp.models.space import Space
from tests.tui_harness import FROZEN_NOW, load_snapshot


def _room(name: str) -> Space:
    return next(s for s in load_snapshot().rooms if s.name == name)


def _with(
    space: Space, mode: HVACMode, heat: float = 20.0, cool: float = 24.0, temp: float = 22.5
) -> Space:
    return replace(
        space,
        controls=replace(
            space.controls, hvac_mode=mode, heating_setpoint_c=heat, cooling_setpoint_c=cool
        ),
        state=replace(space.state, ambient_temperature_c=temp),
    )


def test_next_mode_cycles() -> None:
    family = _room("Family Room")  # COOL in the fixture
    assert next_mode(_with(family, HVACMode.COOL)) is HVACMode.AUTO
    assert next_mode(_with(family, HVACMode.STANDBY)) is HVACMode.HEAT


@pytest.mark.parametrize(
    ("mode", "temp", "expect"),
    [
        (HVACMode.COOL, 22.5, ("cool", 24.0 + STEP_C)),
        (HVACMode.HEAT, 22.5, ("heat", 20.0 + STEP_C)),
        (HVACMode.AUTO, 20.5, ("heat", 20.0 + STEP_C)),  # nearer the heating setpoint
        (HVACMode.AUTO, 23.5, ("cool", 24.0 + STEP_C)),  # nearer the cooling setpoint
    ],
)
def test_nudge_setpoint_picks_the_setpoint_the_mode_uses(
    mode: HVACMode, temp: float, expect: tuple[str, float]
) -> None:
    change = nudge_setpoint(_with(_room("Family Room"), mode, temp=temp), +1)
    assert change is not None
    which, value = expect
    assert getattr(change, f"{which}_c") == pytest.approx(value)
    assert getattr(change, "cool_c" if which == "heat" else "heat_c") is None


def test_nudge_setpoint_steps_one_fahrenheit_degree_in_fahrenheit() -> None:
    change = nudge_setpoint(_with(_room("Family Room"), HVACMode.COOL), -1, use_f=True)
    assert change is not None and change.cool_c == pytest.approx(24.0 - STEP_F_IN_C)


@pytest.mark.parametrize("mode", [HVACMode.STANDBY, HVACMode.FAN, HVACMode.DRY])
def test_nudge_setpoint_none_without_a_setpoint(mode: HVACMode) -> None:
    assert nudge_setpoint(_with(_room("Family Room"), mode), +1) is None


def test_room_views_on_the_fixture() -> None:
    snap = load_snapshot()
    with time_machine.travel(FROZEN_NOW, tick=False):
        views = {v.name: v for v in room_views(snap, FROZEN_NOW)}
    family = views["Family Room"]
    assert family.mode is HVACMode.COOL and family.heat_c is None and family.cool_c is not None
    assert family.dial_online is True and family.dial_age is None
    primary = views["Primary Bedroom"]
    assert primary.dial_online is False and primary.dial_age == "8 h"
    assert primary.dial_presence is None  # an offline Dial's last radar reading is not used
    assert [a.title for a in primary.alerts] == ["Primary Bedroom Dial offline"]
    assert views["Office"].occupancy is OccupancyState.DETECTED


def test_device_views_group_by_room_with_outdoor_units_last() -> None:
    snap = load_snapshot()
    with time_machine.travel(FROZEN_NOW, tick=False):
        rows = device_views(snap, FROZEN_NOW)
    kinds = [r.kind for r in rows]
    assert kinds[-3:] == [DeviceKind.OUTDOOR_UNIT] * 3
    assert [r.room for r in rows[:2]] == ["Family Room", "Family Room"]
    offline = [r for r in rows if r.online is False]
    assert [(r.kind, r.room, r.age, r.link) for r in offline] == [
        (DeviceKind.DIAL, "Primary Bedroom", "8 h", "")  # no stale Wi-Fi/mesh shown
    ]
    assert all(r.firmware != "N/A" for r in rows)  # the server's placeholder is dropped


def test_device_details_resolve_prefixed_outdoor_unit_ids() -> None:
    """IDs may be path-prefixed on one side and bare on the other (snapshot.odu_for_idu)."""
    from quilt_hp.cli.tui.devices import _details

    snap = load_snapshot()
    idu = snap.indoor_units[0]
    odu = snap.odu_for_idu(idu)
    assert odu is not None
    snap.indoor_units[0] = replace(idu, outdoor_unit_id=f"outdoor_unit/{odu.id}")
    room = next(s.name for s in snap.rooms if s.id == idu.space_id)
    with time_machine.travel(FROZEN_NOW, tick=False):
        rows = {(r.kind, r.device_id): r for r in device_views(snap, FROZEN_NOW)}
        idu_detail = dict(_details(snap, rows[(DeviceKind.INDOOR_UNIT, idu.id)], False, raw=False))
        odu_detail = dict(
            _details(snap, rows[(DeviceKind.OUTDOOR_UNIT, odu.id)], False, raw=False)
        )
    assert idu_detail["Outdoor unit"] == odu.serial_number
    assert room in odu_detail["Serves"]


def test_offline_indoor_unit_details_mark_connectivity_as_last_known() -> None:
    from datetime import timedelta

    from quilt_hp.cli.tui.devices import _details

    snap = load_snapshot()
    idu = snap.indoor_units[0]
    old = FROZEN_NOW - timedelta(hours=3)
    snap.indoor_units[0] = replace(idu, state=replace(idu.state, updated_at=old))
    with time_machine.travel(FROZEN_NOW, tick=False):
        row = next(r for r in device_views(snap, FROZEN_NOW) if r.device_id == idu.id)
        detail = dict(_details(snap, row, False, raw=False))
    assert row.online is False and row.link == ""
    assert detail["Wi-Fi"].endswith("(last known)")
    assert detail["Local mesh"].endswith("(last known)")


def test_settings_remember_the_theme_name(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from quilt_hp.cli.settings import SettingsStore

    store = SettingsStore(tmp_path / "settings.json")
    store.update(theme="nord", dark=True)
    assert store.load().theme == "nord"
