"""Pure TUI helpers: ages, the attention list, the hourly chart and plain-text values."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("textual")

from typing import TYPE_CHECKING

import time_machine

from quilt_hp.cli.tui.format import _fmt_display, hourly_chart
from quilt_hp.cli.tui.views import Severity, age_text, attention_items, local_hhmm, system_tz
from quilt_hp.cli.tui.widgets import _KVStatic
from quilt_hp.models import IndoorUnitTestMode, SoftwareUpdateState
from tests.tui_harness import FROZEN_NOW, load_snapshot

if TYPE_CHECKING:
    from rich.text import Text

NOW = datetime(2026, 10, 5, 18, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("ago", "text"),
    [
        (timedelta(seconds=45), "45 s"),
        (timedelta(minutes=12), "12 min"),
        (timedelta(hours=8, minutes=10), "8 h"),
        (timedelta(days=3, hours=2), "3 d"),
        (timedelta(seconds=-5), "0 s"),  # clock skew never shows a negative age
    ],
)
def test_age_text(ago: timedelta, text: str) -> None:
    assert age_text(NOW - ago, NOW) == text


def test_age_text_unknown() -> None:
    assert age_text(None, NOW) == "unknown"


def test_local_hhmm_shows_date_only_for_other_days() -> None:
    tz = UTC
    assert local_hhmm(NOW - timedelta(hours=2), tz, NOW) == "16:00"
    assert local_hhmm(NOW - timedelta(days=1), tz, NOW) == "Oct 4 18:00"


def test_attention_items_on_the_fixture_system() -> None:
    snap = load_snapshot()
    with time_machine.travel(FROZEN_NOW, tick=False):
        items = attention_items(snap, FROZEN_NOW)
    titles = [item.title for item in items]
    assert titles == ["Primary Bedroom Dial offline", "Schedules paused for the whole house"]
    offline = items[0]
    assert offline.severity is Severity.WARNING
    assert offline.detail == "last reading 8 h ago (09:52)"  # system time zone, not UTC
    assert offline.space_id == next(s.id for s in snap.rooms if s.name == "Primary Bedroom")


def test_attention_items_test_mode_and_updates_sorted_by_severity() -> None:
    snap = load_snapshot()
    idu = snap.indoor_units[0]
    snap.indoor_units[0] = replace(
        idu,
        state=replace(idu.state, test_mode=IndoorUnitTestMode.HEALTH_CHECK),
        test_state=None,
    )
    snap.software_update_infos[0] = replace(
        snap.software_update_infos[0], state=SoftwareUpdateState.DOWNLOADING
    )
    with time_machine.travel(FROZEN_NOW, tick=False):
        items = attention_items(snap, FROZEN_NOW)
    assert [i.severity for i in items] == sorted(i.severity for i in items)
    assert any(i.title.endswith("indoor unit running a health check test") for i in items)
    assert "1 firmware update in progress" in [i.title for i in items]


def test_system_tz_uses_the_system_zone() -> None:
    assert str(system_tz(load_snapshot())) == "America/Los_Angeles"


def test_offline_dial_display_is_not_shown_as_current() -> None:
    snap = load_snapshot()
    with time_machine.travel(FROZEN_NOW, tick=False):
        rendered = {c.name: _fmt_display(c)[0] for c in snap.controllers}
    assert sorted(v for v in rendered.values() if v.startswith("⚠")) == ["⚠ offline 8 h"]


def test_hourly_chart_aligns_bars_with_axis() -> None:
    bars, axis = hourly_chart({h: 0.0072 for h in range(16)} | {16: 0.4468, 17: 0.527})
    assert len(bars) == len(axis) == 48
    assert axis.startswith("00    03    06")
    assert bars[32:36] == "▇▇██"  # 16:00 and 17:00, the peak
    assert bars[:32] == "▁" * 32
    assert bars[36:].strip() == ""  # hours without data are blank
    assert axis[30:32] == "15" and axis[36:38] == "18"


def test_hourly_chart_handles_an_all_zero_day() -> None:
    bars, _ = hourly_chart(dict.fromkeys(range(24), 0.0))
    assert bars == "▁" * 48


def test_kv_values_are_plain_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """Room, device and Wi-Fi names containing brackets must not be parsed as markup."""
    widget = _KVStatic()
    shown: list[Text] = []
    monkeypatch.setattr(widget, "update", shown.append)
    widget.set_kv("Name", "[bold]Den[/bold] [x]")
    assert shown[0].plain.endswith("[bold]Den[/bold] [x]")
