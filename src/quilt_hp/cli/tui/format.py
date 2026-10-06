"""Formatting helpers, style tables and control cycles shared by the TUI screens."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from rich.text import Text

from quilt_hp.cli.tui.views import age_text
from quilt_hp.models.controller import Controller
from quilt_hp.models.enums import (
    ControllerViewState,
    FanSpeed,
    HVACMode,
    HVACState,
    LouverMode,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────


_STATE_STYLE: dict[HVACState, str] = {
    HVACState.HEAT: "red",
    HVACState.COOL: "cyan",
    HVACState.DRIFT: "yellow",
    HVACState.FAN: "green",
    HVACState.DRY: "blue",
    HVACState.COOL_DEFERRED: "cyan",
    HVACState.HEAT_DEFERRED: "red",
    HVACState.FAN_DEFERRED: "green",
    HVACState.DRY_DEFERRED: "blue",
    HVACState.COOL_PREPARING: "cyan",
    HVACState.HEAT_PREPARING: "red",
    HVACState.DRY_PREPARING: "blue",
    HVACState.STANDBY: "dim",
    HVACState.UNSPECIFIED: "dim",
}


_STATE_SYMBOLS: dict[HVACState, str] = {
    HVACState.HEAT: "◉ Heating",
    HVACState.COOL: "◉ Cooling",
    HVACState.DRIFT: "~ Drift",
    HVACState.FAN: "~ Fan",
    HVACState.DRY: "◉ Drying",
    HVACState.COOL_DEFERRED: "○ Cool (deferred)",
    HVACState.HEAT_DEFERRED: "○ Heat (deferred)",
    HVACState.FAN_DEFERRED: "○ Fan (deferred)",
    HVACState.DRY_DEFERRED: "○ Dry (deferred)",
    HVACState.COOL_PREPARING: "⋯ Preparing to Cool",
    HVACState.HEAT_PREPARING: "⋯ Preparing to Heat",
    HVACState.DRY_PREPARING: "⋯ Preparing to Dry",
    HVACState.STANDBY: "◌ Standby",
    HVACState.UNSPECIFIED: "--",
}

_FAN_CYCLE = [
    FanSpeed.AUTO,
    FanSpeed.QUIET,
    FanSpeed.LOW,
    FanSpeed.MEDIUM,
    FanSpeed.HIGH,
    FanSpeed.BLAST,
]
_MODE_CYCLE = [
    HVACMode.HEAT,
    HVACMode.COOL,
    HVACMode.AUTO,
    HVACMode.FAN,
    HVACMode.DRY,
    HVACMode.STANDBY,
]
_LOUVER_CYCLE = [
    LouverMode.SWEEP,
    LouverMode.AUTO,
    LouverMode.FIXED,
    LouverMode.CLOSED,
]

_WEEKDAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def _tc(val_c: float | None, use_f: bool) -> str:
    """Format a temperature value in °C or °F."""
    if val_c is None:
        return "--"
    if use_f:
        return f"{val_c * 9 / 5 + 32:.1f}°F"
    return f"{val_c:.1f}°C"


def _fmt_display(ctrl: Controller) -> tuple[str, str]:
    """Dial screen: view state plus brightness, e.g. ``Glance 25%``; ``⚠ offline 8 h`` when offline.

    An offline Dial's last report is not shown: it would read as the current state.
    """
    if not ctrl.is_online:
        return f"⚠ offline {age_text(ctrl.state_updated_at, datetime.now(tz=UTC))}", "bold red"
    if ctrl.view_state == ControllerViewState.UNSPECIFIED:
        return "--", ""
    label = ctrl.view_state.name.title()
    if ctrl.screen_brightness:
        label += f" {ctrl.screen_brightness:.0%}"
    style = {
        ControllerViewState.SLEEP: "dim",
        ControllerViewState.GLANCE: "cyan",
        ControllerViewState.ACTIVE: "bold green",
    }.get(ctrl.view_state, "")
    return label, style


def _fmt_detected(value: bool | None) -> tuple[str, str]:
    """Presence from a radar: detected / clear / unknown."""
    if value is None:
        return "--", ""
    return ("● detected", "bold green") if value else ("○ clear", "dim")


def _sku_or_none(model_sku: str | None) -> str | None:
    """Return a displayable SKU value or None for empty/placeholder values."""
    if not model_sku:
        return None
    sku = model_sku.strip()
    return sku if sku and sku != "N/A" else None


def _id_tokens(value: str | None) -> set[str]:
    """Return raw and normalized ID tokens for tolerant ID comparisons."""
    if not value:
        return set()
    raw = value.strip()
    if not raw:
        return set()
    return {raw, raw.rsplit("/", 1)[-1]}


def _fmt_state(state: HVACState) -> Text:
    label = _STATE_SYMBOLS.get(state, state.name)
    style = _STATE_STYLE.get(state, "")
    return Text(label, style=style)


_BAR_LEVELS = "▁▂▃▄▅▆▇█"
_HOUR_WIDTH = 2


def hourly_chart(hour_kwh: dict[int, float]) -> tuple[str, str]:
    """Bars and a matching axis for one day of hourly energy, two columns per hour.

    Hours with data get a bar scaled to the day's peak (``▁`` for the lowest); hours without
    data are blank. The axis labels every third hour at the same column as its bar.
    """
    peak = max(hour_kwh.values(), default=0.0)
    bars = []
    for hour in range(24):
        if hour not in hour_kwh:
            bars.append(" " * _HOUR_WIDTH)
            continue
        level = round(hour_kwh[hour] / peak * (len(_BAR_LEVELS) - 1)) if peak > 0 else 0
        bars.append(_BAR_LEVELS[level] * _HOUR_WIDTH)
    axis = [" "] * (24 * _HOUR_WIDTH)
    for hour in range(0, 24, 3):
        axis[hour * _HOUR_WIDTH : hour * _HOUR_WIDTH + 2] = f"{hour:02d}"
    return "".join(bars), "".join(axis)


def _cycle_next[T](current: T, cycle: list[T]) -> T:
    try:
        return cycle[(cycle.index(current) + 1) % len(cycle)]
    except ValueError:
        return cycle[0]
