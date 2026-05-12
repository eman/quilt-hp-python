from __future__ import annotations

import pytest

pytest.importorskip("textual")

from quilt_hp.cli.tui import DashboardScreen, RoomScreen, SystemScreen, _id_tokens, _sku_or_none


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


def test_dashboard_odu_for_falls_back_to_space_id_match() -> None:
    class _Snap:
        def __init__(self) -> None:
            self.outdoor_units = [type("Odu", (), {"space_id": "space-1"})()]

        def odu_for_idu(self, _idu: object) -> object | None:
            return None

    screen = DashboardScreen(snapshot=_Snap(), client=object())
    odu = screen._odu_for("space/space-1", idu=object())
    assert odu is not None
