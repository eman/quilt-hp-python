"""Rendering shared by the Home and Room screens."""

from __future__ import annotations

from typing import Any

from rich.text import Text

from quilt_hp.cli.tui.format import _fmt_state, _tc
from quilt_hp.cli.tui.views import RoomView, Severity
from quilt_hp.models.enums import ControllerViewState, HVACMode, OccupancyState

SEVERITY_MARK = {
    Severity.CRITICAL: ("⚠", "bold red"),
    Severity.WARNING: ("⚠", "yellow"),
    Severity.INFO: ("•", "dim"),
}
MODE_WORDS = {
    HVACMode.COOL: "Cool",
    HVACMode.HEAT: "Heat",
    HVACMode.AUTO: "Auto",
    HVACMode.FAN: "Fan",
    HVACMode.DRY: "Dry",
    HVACMode.STANDBY: "Off",
}


def target_text(v: RoomView, deg: Any) -> Text:
    if v.away:
        return Text("Away", style="yellow")
    word = MODE_WORDS.get(v.mode, "–")
    style = {HVACMode.COOL: "cyan", HVACMode.HEAT: "red", HVACMode.AUTO: "magenta"}.get(
        v.mode, "dim"
    )
    if v.mode == HVACMode.AUTO and v.heat_c is not None and v.cool_c is not None:
        return Text(f"{word} {deg(v.heat_c)}–{deg(v.cool_c)}", style=style)
    setpoint = v.cool_c if v.cool_c is not None else v.heat_c
    return Text(f"{word} {deg(setpoint)}" if setpoint is not None else word, style=style)


def people_text(occupancy: OccupancyState | None) -> Text:
    if occupancy == OccupancyState.DETECTED:
        return Text("● here", style="green")
    if occupancy == OccupancyState.UNDETECTED:
        return Text("○ away", style="dim")
    return Text("–", style="dim")


def room_summary(v: RoomView, use_f: bool) -> Text:
    def t(value: float | None) -> str:
        return _tc(value, use_f)

    lines: list[Text] = []
    if v.away:
        goal = Text("away: standby until someone comes back", style="yellow")
    elif v.mode == HVACMode.AUTO and v.heat_c is not None and v.cool_c is not None:
        goal = Text(f"keeping between {t(v.heat_c)} and {t(v.cool_c)}")
    elif v.mode in (HVACMode.COOL, HVACMode.HEAT) and (v.cool_c or v.heat_c) is not None:
        verb = "cooling to" if v.mode == HVACMode.COOL else "heating to"
        goal = Text(f"{verb} {t(v.cool_c if v.mode == HVACMode.COOL else v.heat_c)}")
    else:
        goal = Text(MODE_WORDS.get(v.mode, "–").replace("Off", "off"), style="dim")
    lines.append(Text.assemble((t(v.temp_c), "bold green"), "  ", goal))
    climate = []
    if v.humidity_percent is not None:
        climate.append(f"{v.humidity_percent:.0f}% RH")
    if v.dew_point_c is not None:
        climate.append(f"dew point {t(v.dew_point_c)}")
    lines.append(Text("  ·  ").join([_fmt_state(v.hvac_state), *(Text(c) for c in climate)]))
    air = []
    if v.fan is not None:
        air.append(f"fan {v.fan.name.lower()}")
    if v.fan_rpm:
        air.append(f"{v.fan_rpm:,.0f} rpm")
    if v.louver is not None:
        air.append(f"louver {v.louver.name.lower()}")
    if air:
        lines.append(Text(" · ".join(air)))
    power = []
    if v.power_w is not None:
        power.append(f"{v.power_w:,.0f} W")
    if v.cop:
        power.append(f"COP {v.cop:.1f}")
    if v.odu_share:
        power.append(f"{v.odu_share:.0%} of its outdoor unit")
    if power:
        lines.append(Text(" · ".join(power)))
    if v.dial_online is False:
        lines.append(Text(f"Dial ⚠ offline {v.dial_age}", style="bold red"))
    elif v.dial_online:
        display = "–"
        if v.dial_display not in (None, ControllerViewState.UNSPECIFIED):
            display = v.dial_display.name.title()
            if v.dial_brightness:
                display += f" {v.dial_brightness:.0%}"
        radar = {True: "radar ● someone", False: "radar ○ clear", None: "radar –"}[v.dial_presence]
        lines.append(Text(f"Dial {display} · {radar}", style="dim"))
    return Text("\n").join(lines)
