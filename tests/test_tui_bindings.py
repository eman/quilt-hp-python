from __future__ import annotations

from typing import ClassVar

import pytest

pytest.importorskip("textual")

from quilt_hp.cli.tui import DevicesScreen, HomeScreen, RoomScreen
from quilt_hp.cli.tui.format import _id_tokens, _sku_or_none


def _key_action_map() -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for binding in RoomScreen.BINDINGS:
        for key in binding.key.split(","):
            mapping.setdefault(key, set()).add(binding.action)
    return mapping


def test_room_bindings_have_no_case_pairs_or_modifier_chords() -> None:
    keymap = _key_action_map()
    assert keymap["f"] == {"cycle_fan"}
    assert keymap["v"] == {"cycle_louver"}
    assert keymap["l"] == {"toggle_light"}
    assert keymap["s"] == {"settings"}
    assert keymap["plus"] == {"setpoint(1)"} and keymap["minus"] == {"setpoint(-1)"}
    assert keymap["left_square_bracket"] == {"switch_room(-1)"}
    assert keymap["right_square_bracket"] == {"switch_room(1)"}
    assert keymap["1"] == {"tab('overview')"} and keymap["5"] == {"tab('devices')"}
    # Rare settings live in the settings dialog, not on chords many terminals intercept.
    assert not [k for k in keymap if k.startswith(("ctrl+", "alt+"))]
    # No upper/lower-case pairs bound to different actions (the old H/h, C/c, L/l).
    letters = [k for k in keymap if len(k) == 1 and k.isalpha()]
    assert not [k for k in letters if k.swapcase() in keymap and keymap[k] != keymap[k.swapcase()]]
    # Schedules for the whole house are never changed from a room.
    assert "p" not in keymap and "P" not in keymap


def _keymap(screen: type) -> dict[str, set[str]]:
    keymap: dict[str, set[str]] = {}
    for binding in screen.BINDINGS:
        for key in binding.key.split(","):
            keymap.setdefault(key, set()).add(binding.action)
    return keymap


def test_home_bindings() -> None:
    keymap = _keymap(HomeScreen)
    assert keymap["enter"] == {"open_room"}
    assert keymap["m"] == {"cycle_mode"}
    assert keymap["plus"] == keymap["equals_sign"] == {"setpoint(1)"}
    assert keymap["minus"] == {"setpoint(-1)"}
    assert keymap["d"] == {"devices"}
    assert keymap["u"] == {"toggle_units"}
    # Pausing every room's schedule takes a capital P and a confirmation, never a stray p.
    assert keymap["P"] == {"toggle_schedules"}
    assert "p" not in keymap


def test_devices_bindings() -> None:
    keymap = _keymap(DevicesScreen)
    assert keymap["r"] == {"toggle_raw"}
    assert keymap["escape"] == {"back"}


def test_sku_or_none_filters_empty_and_placeholder_values() -> None:
    assert _sku_or_none(None) is None
    assert _sku_or_none("") is None
    assert _sku_or_none("  ") is None
    assert _sku_or_none("N/A") is None
    assert _sku_or_none("  N/A  ") is None


def test_sku_or_none_returns_trimmed_sku() -> None:
    assert _sku_or_none("  QHP-1234  ") == "QHP-1234"


def test_id_tokens_normalizes_prefixed_ids() -> None:
    assert _id_tokens("outdoor_unit/odu-1") == {"outdoor_unit/odu-1", "odu-1"}
    assert _id_tokens("  odu-1  ") == {"odu-1"}
    assert _id_tokens("") == set()
    assert _id_tokens(None) == set()


def test_odu_for_space_falls_back_to_space_id_match() -> None:
    from quilt_hp.cli.tui.shared import _odu_for_space

    class _Snap:
        def __init__(self) -> None:
            self.outdoor_units = [type("Odu", (), {"space_id": "space-1"})()]

        def odu_for_idu(self, _idu: object) -> object | None:
            return None

    assert _odu_for_space(_Snap(), "space/space-1", idu=object()) is not None  # type: ignore[arg-type]


def test_setpoint_clamp_constants() -> None:
    from quilt_hp.cli.constants import SETPOINT_MAX_C, SETPOINT_MIN_C, clamp_setpoint_c

    assert clamp_setpoint_c(SETPOINT_MIN_C - 5) == SETPOINT_MIN_C
    assert clamp_setpoint_c(SETPOINT_MAX_C + 5) == SETPOINT_MAX_C
    assert clamp_setpoint_c(21.5) == 21.5


def test_patch_schedule_paused_replaces_location_in_place() -> None:
    from dataclasses import dataclass

    from quilt_hp.cli.tui.shared import _patch_schedule_paused

    @dataclass
    class _Loc:
        schedule_paused: bool

    class _Snap:
        def __init__(self) -> None:
            self.locations = [_Loc(schedule_paused=False)]

        @property
        def primary_location(self) -> _Loc | None:
            return self.locations[0] if self.locations else None

    snap = _Snap()
    _patch_schedule_paused(snap, paused=True)  # type: ignore[arg-type]
    assert snap.locations[0].schedule_paused is True


def test_odu_for_space_prefers_idu_link() -> None:
    from quilt_hp.cli.tui.shared import _odu_for_space

    sentinel = object()

    class _Snap:
        outdoor_units: ClassVar[list[object]] = []

        def odu_for_idu(self, _idu: object) -> object:
            return sentinel

    assert _odu_for_space(_Snap(), "space/space-1", idu=object()) is sentinel  # type: ignore[arg-type]


def test_fmt_display_and_detected() -> None:
    from types import SimpleNamespace

    from quilt_hp.cli.tui.format import _fmt_detected, _fmt_display
    from quilt_hp.models import ControllerViewState

    glance = SimpleNamespace(
        view_state=ControllerViewState.GLANCE, screen_brightness=0.25, is_online=True
    )
    assert _fmt_display(glance) == ("Glance 25%", "cyan")  # type: ignore[arg-type]
    asleep = SimpleNamespace(
        view_state=ControllerViewState.SLEEP, screen_brightness=0.0, is_online=True
    )
    assert _fmt_display(asleep) == ("Sleep", "dim")  # type: ignore[arg-type]
    unknown = SimpleNamespace(
        view_state=ControllerViewState.UNSPECIFIED, screen_brightness=None, is_online=True
    )
    assert _fmt_display(unknown) == ("--", "")  # type: ignore[arg-type]

    assert _fmt_detected(True)[0] == "● detected"
    assert _fmt_detected(False)[0] == "○ clear"
    assert _fmt_detected(None) == ("--", "")
