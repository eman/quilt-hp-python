from __future__ import annotations

import pytest

pytest.importorskip("textual")

from quilt_hp.cli.tui import RoomScreen


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
