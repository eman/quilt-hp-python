from __future__ import annotations

import pytest

pytest.importorskip("textual")

from quilt_hp.cli.tui import RoomScreen, SystemScreen


def _key_action_map() -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for binding in RoomScreen.BINDINGS:
        for key in binding.key.split(","):
            mapping.setdefault(key, set()).add(binding.action)
    return mapping


def test_fan_key_does_not_overlap_with_fence_adjustment() -> None:
    keymap = _key_action_map()
    assert keymap["f"] == {"cycle_fan"}
    assert "fence_fwd_inc" not in keymap["f"]
    assert "ctrl+up" in keymap
    assert keymap["ctrl+up"] == {"fence_fwd_inc"}


def test_system_bindings_map_units_and_schedule_actions() -> None:
    keymap: dict[str, set[str]] = {}
    for binding in SystemScreen.BINDINGS:
        for key in binding.key.split(","):
            keymap.setdefault(key, set()).add(binding.action)

    assert keymap["u"] == {"toggle_units"}
    assert keymap["p"] == {"toggle_schedule"}


def test_system_screen_accepts_initial_unit_preference() -> None:
    screen = SystemScreen(snapshot=object(), client=object(), use_f=True)
    assert screen.use_f is True
