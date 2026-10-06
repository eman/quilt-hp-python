"""Formatting helpers, style tables and control cycles shared by the TUI screens."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from rich.text import Text

from quilt_hp.cli.tui.views import age_text
from quilt_hp.models.controller import Controller
from quilt_hp.models.enums import (
    ControllerViewState,
    FanSpeed,
    HVACMode,
    HVACState,
    LightPreset,
    LocalCommsHealthStatus,
    LouverMode,
    OccupancyState,
)

if TYPE_CHECKING:
    from quilt_hp.models.space import Space


logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

_MODE_STYLE: dict[HVACMode, str] = {
    HVACMode.HEAT: "bold red",
    HVACMode.COOL: "bold cyan",
    HVACMode.AUTO: "bold yellow",
    HVACMode.FAN: "bold green",
    HVACMode.DRY: "bold blue",
    HVACMode.STANDBY: "dim",
    HVACMode.FALLBACK_AUTO: "bold yellow",
    HVACMode.FALLBACK_OFF: "dim",
    HVACMode.UNSPECIFIED: "dim",
}

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

_MODE_LABELS: dict[HVACMode, str] = {
    HVACMode.HEAT: "HEAT",
    HVACMode.COOL: "COOL",
    HVACMode.AUTO: "AUTO",
    HVACMode.FAN: " FAN",
    HVACMode.DRY: " DRY",
    HVACMode.STANDBY: "STBY",
    HVACMode.FALLBACK_AUTO: "FAUTO",
    HVACMode.FALLBACK_OFF: "FOFF",
    HVACMode.UNSPECIFIED: " -- ",
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


def _fmt_timeout(seconds: float) -> str:
    """Format timeout as readable text (for example, '20 min')."""
    if seconds <= 0:
        return "0 s"
    total_m = int(seconds) // 60
    rem_s = int(seconds) % 60
    if total_m == 0:
        return f"{rem_s} s"
    if rem_s == 0:
        return f"{total_m} min"
    return f"{total_m} min {rem_s} s"


def _tu(use_f: bool) -> str:
    return "°F" if use_f else "°C"


def _led_color_str(color_code: int) -> str:
    """Return a human-readable LED color label from a packed RGBW uint32.

    Matches against known LightPreset values first; falls back to hex notation.
    """
    if color_code == 0:
        return "Black"
    try:
        return LightPreset(color_code).name.capitalize()
    except ValueError:
        r = (color_code >> 24) & 0xFF
        g = (color_code >> 16) & 0xFF
        b = (color_code >> 8) & 0xFF
        w = color_code & 0xFF
        return f"#{r:02X}{g:02X}{b:02X}w{w:02X}"


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


def _occ_glyph(occ: OccupancyState | int | None) -> str:
    if occ is None:
        return "?"
    state = OccupancyState(occ) if isinstance(occ, int) else occ
    if state == OccupancyState.DETECTED:
        return "[green]●[/green]"
    if state == OccupancyState.UNDETECTED:
        return "[dim]○[/dim]"
    return "[dim]?[/dim]"


_LOCAL_COMMS_STYLE: dict[LocalCommsHealthStatus, str] = {
    LocalCommsHealthStatus.HEALTHY: "green",
    LocalCommsHealthStatus.STARTING_UP: "green",  # transient — treat as healthy
    LocalCommsHealthStatus.DEGRADED: "bold yellow",
    LocalCommsHealthStatus.OFFLINE: "bold red",
    LocalCommsHealthStatus.UNSPECIFIED: "dim",
}
_LOCAL_COMMS_LABELS: dict[LocalCommsHealthStatus, str] = {
    LocalCommsHealthStatus.HEALTHY: "● Healthy",
    LocalCommsHealthStatus.STARTING_UP: "⋯ Starting",
    LocalCommsHealthStatus.DEGRADED: "⚠ Degraded",
    LocalCommsHealthStatus.OFFLINE: "✗ Offline",
    LocalCommsHealthStatus.UNSPECIFIED: "--",
}


def _fmt_local_comms(health: LocalCommsHealthStatus) -> tuple[str, str]:
    """Return (label, style) for a LocalCommsHealthStatus value."""
    return (
        _LOCAL_COMMS_LABELS.get(health, health.name),
        _LOCAL_COMMS_STYLE.get(health, ""),
    )


def _fmt_mode(mode: HVACMode) -> Text:
    label = _MODE_LABELS.get(mode, mode.name)
    style = _MODE_STYLE.get(mode, "")
    return Text(label, style=style)


def _space_mode_badge(space: Space) -> Text:
    """Mode badge using Space.is_away / Space.is_off from the core model."""
    if space.is_away:
        return Text("AWAY", style="yellow dim")
    if space.is_off:
        return Text(" OFF", style="dim")
    return _fmt_mode(space.controls.hvac_mode)


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
