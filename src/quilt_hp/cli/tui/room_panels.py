"""Room screen state and panel rendering (read-only); the screen itself is in room.py."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.screen import Screen
from textual.widgets import DataTable, OptionList, Static

from quilt_hp.cli.tui.base import SnapshotHost
from quilt_hp.cli.tui.devices import _KIND_LABELS, _details
from quilt_hp.cli.tui.format import (
    _fmt_state,
    _tc,
    hourly_chart,
)
from quilt_hp.cli.tui.render import MODE_WORDS, SEVERITY_MARK, room_summary
from quilt_hp.cli.tui.views import (
    DeviceKind,
    EnergySummary,
    RoomView,
    device_views,
    room_views,
    week_schedule,
)
from quilt_hp.models.enums import (
    ConditionState,
    HVACMode,
    LouverMode,
    OccupancyMode,
    Presence,
)

if TYPE_CHECKING:
    from quilt_hp.client import QuiltClient
    from quilt_hp.models.controller import Controller
    from quilt_hp.models.indoor_unit import IndoorUnit
    from quilt_hp.models.space import Space
    from quilt_hp.models.system import SystemSnapshot

logger = logging.getLogger(__name__)

TABS = ("overview", "climate", "schedule", "energy", "devices")
_CONTROLS = ("mode", "cool", "heat", "fan", "louver", "light")
_CONTROL_LABELS = {
    "mode": "Mode",
    "cool": "Cool to",
    "heat": "Heat to",
    "fan": "Fan",
    "louver": "Louver",
    "light": "Light",
}
_LIGHT_STEP = 0.1


class RoomPanels(Screen[None]):
    """What the Room screen shows: the room's state and how each tab's panels render it."""

    space_id: str
    _snapshot: SystemSnapshot
    _client: QuiltClient
    _raw: bool
    _energy: EnergySummary | None
    _energy_error: str | None

    # ── Shared state ────────────────────────────────────────────

    @property
    def snapshot(self) -> SystemSnapshot:
        with contextlib.suppress(Exception):
            app = self.app
            if isinstance(app, SnapshotHost) and app.snapshot is not None:
                return app.snapshot
        return self._snapshot

    @property
    def use_f(self) -> bool:
        with contextlib.suppress(Exception):
            app = self.app
            if isinstance(app, SnapshotHost):
                return app.use_f
        return False

    @property
    def space(self) -> Space | None:
        return next((s for s in self.snapshot.rooms if s.id == self.space_id), None)

    @property
    def idu(self) -> IndoorUnit | None:
        return next((u for u in self.snapshot.indoor_units if u.space_id == self.space_id), None)

    @property
    def controller(self) -> Controller | None:
        return next((c for c in self.snapshot.controllers if c.space_id == self.space_id), None)

    def _view(self) -> RoomView | None:
        return next((v for v in room_views(self.snapshot) if v.space_id == self.space_id), None)

    def _t(self, value_c: float | None) -> str:
        return _tc(value_c, self.use_f)

    # ── Rendering ───────────────────────────────────────────────

    def render_all(self) -> None:
        space = self.space
        if space is None:
            return
        view = self._view()
        self._render_overview(space, view)
        self._render_climate(space, view)
        self._render_schedule()
        self._render_energy()
        self._render_devices()

    def _render_overview(self, space: Space, view: RoomView | None) -> None:
        hero = self.query_one("#ov-hero", Static)
        hero.border_title = space.name
        lines = [room_summary(view, self.use_f)] if view else [Text("–", style="dim")]
        lines.append(Text(""))
        lines.append(self._occupancy_line(space, view))
        comfort = self._comfort_line(space)
        if comfort is not None:
            lines.append(comfort)
        for alert in view.alerts if view else ():
            mark, style = SEVERITY_MARK[alert.severity]
            lines.append(
                Text(f"{mark} {alert.title.removeprefix(space.name).strip(' :')}", style=style)
            )
        hero.update(Text("\n").join(lines))

        controls = self.query_one("#ov-controls", OptionList)
        for key in _CONTROLS:
            controls.replace_option_prompt(key, self._control_prompt(key, space))
        today = self.query_one("#ov-today", Static)
        today.update(self._today_chart())

    def _occupancy_line(self, space: Space, view: RoomView | None) -> Text:
        sets = space.settings
        if sets.occupancy_mode != OccupancyMode.ENABLED:
            return Text("Auto-away off", style="dim")
        state = "–"
        if view and view.occupancy is not None:
            state = "Occupied" if view.occupancy.name == "DETECTED" else "Empty"
        return Text.assemble(
            (state, "green" if state == "Occupied" else ""),
            (
                f" · away after {_minutes(sets.unoccupied_timeout_s)} empty, back after "
                f"{_minutes(sets.occupied_timeout_s)}",
                "dim",
            ),
        )

    def _occupancy_word(self, space: Space, view: RoomView | None) -> Text:
        if space.settings.occupancy_mode != OccupancyMode.ENABLED:
            return Text("auto-away off", style="dim")
        if view is None or view.occupancy is None:
            return Text("–", style="dim")
        if view.occupancy.name == "DETECTED":
            return Text("● occupied", style="green")
        return Text("○ empty", style="dim")

    def _comfort_line(self, space: Space) -> Text | None:
        c = space.controls
        preset = next(
            (p for p in self.snapshot.comfort_settings if p.id == c.comfort_setting_id), None
        )
        if preset is None:
            return None
        how = {
            "NONE": "from the schedule",
            "SCHEDULE": "from the schedule",
            "UNTIL_NEXT_SCHEDULE": "set by hand until the next schedule event",
            "INDEFINITE": "set by hand",
            "UNOCCUPIED": "set by auto-away",
            "OCCUPIED": "set when someone came back",
        }.get(c.comfort_setting_override.name, "")
        loc = self.snapshot.primary_location
        if loc is not None and loc.schedule_paused and "schedule" in how:
            how += " (schedules are paused)"
        return Text.assemble(("Comfort ", "dim"), preset.name, (f" · {how}" if how else "", "dim"))

    def _control_prompt(self, key: str, space: Space) -> Text:
        label = Text(f"{_CONTROL_LABELS[key]:<9}", style="dim")
        c = space.controls
        idu = self.idu
        mode = c.hvac_mode
        if key == "mode":
            value = Text(
                MODE_WORDS.get(mode, "–") + (" (away)" if space.is_away else ""), style="bold"
            )
        elif key in ("cool", "heat"):
            setpoint = c.cooling_setpoint_c if key == "cool" else c.heating_setpoint_c
            uses = {
                "cool": (HVACMode.COOL, HVACMode.AUTO),
                "heat": (HVACMode.HEAT, HVACMode.AUTO),
            }[key]
            value = Text(self._t(setpoint), style="bold cyan" if key == "cool" else "bold red")
            if mode not in uses:
                value = Text.assemble(
                    (self._t(setpoint), "dim"),
                    (f"  not used in {MODE_WORDS.get(mode, '–')}", "dim"),
                )
        elif idu is None:
            value = Text("–  no indoor unit", style="dim")
        elif key == "fan":
            value = Text(idu.controls.fan_speed.name.title())
        elif key == "louver":
            lm = idu.controls.louver_mode
            text = lm.name.title()
            if lm == LouverMode.FIXED and idu.controls.louver_fixed_position:
                text += f" {idu.controls.louver_fixed_position:.0f}°"
            value = Text(text)
        else:
            on = idu.controls.light_on
            value = Text(f"On {idu.controls.led_brightness:.0%}" if on else "Off")
        return Text.assemble(label, " ", value)

    def _today_chart(self, totals: bool = True) -> Text:
        if self._energy is None:
            return Text(self._energy_error or "Loading energy…", style="dim")
        bars, axis = hourly_chart(self._energy.today_by_hour)
        if not totals:
            return Text.assemble((bars, "cyan"), "\n", (axis, "dim"))
        return Text.assemble(
            (bars, "cyan"),
            f"   {self._energy.today_kwh:.2f} kWh today\n",
            (axis, "dim"),
            (f"   {self._energy.yesterday_kwh:.2f} kWh yesterday", "dim"),
        )

    def _render_climate(self, space: Space, view: RoomView | None) -> None:
        idu, ctrl = self.idu, self.controller
        diag = next(
            (
                d
                for d in self.snapshot.diagnostics().indoor_units
                if idu and d.indoor_unit_id == idu.id
            ),
            None,
        )
        t = self._t
        live = bool(idu and idu.is_online)

        air: list[tuple[str, Text | str]] = []
        if ctrl is not None:
            dial = t(ctrl.calibrated_ambient_c) if ctrl.is_online else "Dial offline"
            air.append(("Room (Dial)", Text(dial, style="green" if ctrl.is_online else "red")))
        if idu is not None:
            air.append(("Unit sensor", t(idu.state.ambient_temperature_c) if live else "–"))
        if diag is not None and live:
            air += [
                ("Air in", t(diag.inlet_temperature_c)),
                ("Air out", t(diag.outlet_temperature_c)),
                ("Coil", t(diag.coil_temperature_c)),
                ("Gas pipe", t(diag.gas_pipe_temperature_c)),
                ("Liquid pipe", t(diag.liquid_pipe_temperature_c)),
            ]
        humidity = view.humidity_percent if view else None
        air.append(("Humidity", f"{humidity:.0f}%" if humidity is not None else "–"))
        air.append(
            ("Dew point", t(view.dew_point_c) if view and view.dew_point_c is not None else "–")
        )
        self.query_one("#cl-air", Static).update(_kv(air))

        unit: list[tuple[str, Text | str]] = []
        if idu is None:
            unit.append(("", Text("This room has no indoor unit.", style="dim")))
        elif not live:
            unit.append(("", Text("Indoor unit offline.", style="bold red")))
        else:
            pm = idu.performance_metrics
            unit.append(("State", _fmt_state(idu.state.hvac_state)))
            unit.append(
                (
                    "Fan",
                    f"{idu.state.fan_speed_rpm:,.0f} rpm"
                    + (
                        f" (target {idu.state.fan_speed_setpoint_rpm:,.0f})"
                        if idu.state.fan_speed_setpoint_rpm
                        else ""
                    ),
                )
            )
            if pm is not None:
                unit.append(("Power", f"{pm.hvac_power_w:,.0f} W"))
                if pm.capacity_w:
                    unit.append(("Capacity", f"{pm.capacity_w / 1000:.2f} kW"))
                if pm.coefficient_of_performance:
                    unit.append(("COP", f"{pm.coefficient_of_performance:.1f}"))
                if pm.odu_usage_fraction:
                    unit.append(("Outdoor share", f"{pm.odu_usage_fraction:.0%}"))
            active = diag.active_faults if diag else []
            busy = [
                name
                for name, state in (diag.conditions.items() if diag else [])
                if state == ConditionState.ACTIVE and name not in active
            ]
            if active:
                unit.append(
                    ("Faults", Text(", ".join(_words(a) for a in active), style="bold red"))
                )
            elif busy:
                unit.append(("Conditions", ", ".join(_words(b) for b in busy)))
            else:
                unit.append(("Conditions", Text("none active", style="green")))
            if idu.is_under_test:
                unit.append(
                    ("Test", Text(_words(idu.effective_test_mode.name), style="bold yellow"))
                )
        self.query_one("#cl-unit", Static).update(_kv(unit))

        presence: list[tuple[str, Text | str]] = []
        presence.append(("Room", self._occupancy_word(space, view)))
        if idu is not None and live and idu.presence is not None:
            channels = (idu.presence.sensor0_presence, idu.presence.sensor1_presence)
            seen = any(ch == Presence.DETECTED for ch in channels)
            presence.append(
                (
                    "Unit radar",
                    Text("● someone", style="green") if seen else Text("○ clear", style="dim"),
                )
            )
        if ctrl is not None:
            if ctrl.is_online:
                presence.append(
                    (
                        "Dial radar",
                        Text("● someone", style="green")
                        if ctrl.presence_detected
                        else Text("○ clear", style="dim"),
                    )
                )
                display = ctrl.view_state.name.title()
                if ctrl.screen_brightness:
                    display += f" {ctrl.screen_brightness:.0%}"
                presence.append(("Dial display", display))
                if ctrl.ambient_light_lux is not None:
                    presence.append(("Light", f"{ctrl.ambient_light_lux:.0f} lx"))
            else:
                presence.append(("Dial", Text("offline", style="bold red")))
        self.query_one("#cl-presence", Static).update(_kv(presence))

        raw = self.query_one("#cl-raw", Static)
        raw.display = self._raw
        if self._raw:
            raw.update(_kv(self._raw_pairs(idu)))

    def _raw_pairs(self, idu: IndoorUnit | None) -> list[tuple[str, Text | str]]:
        if idu is None:
            return [("", Text("No indoor unit.", style="dim"))]
        t = self._t
        pairs: list[tuple[str, Text | str]] = []
        if idu.presence is not None:
            p = idu.presence
            pairs.append(
                (
                    "Radar channels",
                    f"{p.sensor0_presence.name.lower()} / {p.sensor1_presence.name.lower()}",
                )
            )
        st = idu.settings
        pairs.append(
            (
                "Radar fence",
                f"left {_metres(st.presence_fence_left_m)} · right {_metres(st.presence_fence_right_m)} · "
                f"depth {_metres(st.presence_fence_forward_m)} · height {_metres(st.radar_sensor_distance_from_floor_m)}",
            )
        )
        if idu.hvac_inputs is not None:
            hi = idu.hvac_inputs
            pairs.append(
                (
                    "Controller input",
                    f"{t(hi.external_ambient_temperature_c)} → {t(hi.temperature_setpoint_c)} · "
                    f"{hi.hvac_mode.name.lower()} · source {hi.ambient_temperature_source.name.lower()}",
                )
            )
        if idu.commands is not None:
            pairs.append(("Fallback command", idu.commands.fallback_control_command.name.lower()))
        c = idu.controls
        pairs.append(
            (
                "LED",
                f"{c.led_state.name.lower()} · {c.led_brightness:.0%} · colour {c.led_color_code} · {c.led_animation.name.lower()}",
            )
        )
        qsm = self.snapshot.qsm_for_idu(idu)
        if qsm is not None and qsm.sensors is not None:
            s = qsm.sensors
            pairs += [
                (
                    "Module radar",
                    f"phase {s.phase_detected_raw:.3f} · target {s.target_detected_raw:.3f}",
                ),
                (
                    "Module light",
                    f"{s.als_illuminance_raw} (IR {s.als_ir_raw}, both {s.als_both_raw})",
                ),
                ("Accelerometer", f"{s.accel_x_raw} / {s.accel_y_raw} / {s.accel_z_raw}"),
            ]
        pairs.append(("", Text("Dial telemetry is on the Devices tab.", style="dim italic")))
        return pairs

    def _render_schedule(self) -> None:
        loc = self.snapshot.primary_location
        paused = loc is not None and loc.schedule_paused
        self.query_one("#sch-status", Static).update(
            Text.assemble(("Schedules paused", "yellow"), ("  resume from Home with P", "dim"))
            if paused
            else Text("Schedules running", style="green")
        )
        table: DataTable[Any] = self.query_one("#sch-week", DataTable)
        table.clear()
        grid = week_schedule(self.snapshot, self.space_id)
        if grid is None:
            table.display = False
            self.query_one("#sch-status", Static).update(
                Text("This room has no schedule.", style="dim")
            )
            return
        table.display = True
        for row in range(max((len(day) for day in grid), default=0)):
            cells = []
            for day in grid:
                if row >= len(day):
                    cells.append(Text(""))
                    continue
                slot = day[row]
                word = MODE_WORDS.get(slot.mode, "–")
                if slot.heat_c is not None and slot.cool_c is not None:
                    word += f" {self._deg(slot.heat_c)}–{self._deg(slot.cool_c)}"
                elif (slot.cool_c or slot.heat_c) is not None:
                    word += (
                        f" {self._deg(slot.cool_c if slot.cool_c is not None else slot.heat_c)}"
                    )
                cells.append(Text.assemble((slot.time, "bold"), "\n", word))
            table.add_row(*cells, height=2)

    def _deg(self, value_c: float | None) -> str:
        return self._t(value_c).removesuffix("F").removesuffix("C")

    def _render_energy(self) -> None:
        summary = self.query_one("#en-summary", Static)
        today = self.query_one("#en-today", Static)
        days = self.query_one("#en-days", Static)
        e = self._energy
        if e is None:
            message = Text(self._energy_error or "Loading energy…", style="dim")
            for widget in (summary, today, days):
                widget.update(message)
            return
        summary.update(
            _kv(
                [
                    ("Today", Text(f"{e.today_kwh:.2f} kWh", style="bold cyan")),
                    ("Yesterday", f"{e.yesterday_kwh:.2f} kWh"),
                    ("Last 7 days", f"{e.last_7_days_kwh:.2f} kWh"),
                    ("Last 30 days", f"{e.last_30_days_kwh:.2f} kWh"),
                ]
            )
        )
        today.update(self._today_chart(totals=False))
        recent = e.last_days(14)
        peak = max((kwh for _, kwh in recent if kwh is not None), default=0.0)
        lines = []
        for day, kwh in recent:
            label = (f"{day.strftime('%a %b')} {day.day:>2}  ", "dim")
            if kwh is None:
                lines.append(Text.assemble(label, ("no data", "dim")))
                continue
            width = round(kwh / peak * 30) if peak > 0 else 0
            lines.append(Text.assemble(label, ("█" * width or "▏", "cyan"), f" {kwh:.2f} kWh"))
        days.update(Text("\n").join(lines) if lines else Text("No energy data yet.", style="dim"))

    def _render_devices(self) -> None:
        space = self.space
        snap = self.snapshot
        rows = [r for r in device_views(snap) if space and r.room == space.name]
        idu = self.idu
        odu = snap.odu_for_idu(idu) if idu else None
        if odu is not None:
            rows += [
                r
                for r in device_views(snap)
                if r.kind == DeviceKind.OUTDOOR_UNIT and r.device_id == odu.id
            ]
        blocks = []
        for row in rows:
            status = (
                "online" if row.online else (f"offline {row.age}" if row.online is False else "")
            )
            title = Text.assemble(
                (_KIND_LABELS[row.kind], "bold"),
                (
                    f"  {status}",
                    "green" if row.online else "red" if row.online is False else "dim",
                ),
            )
            blocks.append(
                Text.assemble(title, "\n", _kv(_details(snap, row, self.use_f, raw=self._raw)))
            )
        if not self._raw:
            blocks.append(Text("r shows raw telemetry", style="dim italic"))
        self.query_one("#dv-list", Static).update(
            Text("\n\n").join(blocks) if blocks else Text("No devices.", style="dim")
        )


def _kv(pairs: Sequence[tuple[str, Text | str]]) -> Text:
    width = max((len(k) for k, _ in pairs), default=0) + 2
    lines = []
    for key, value in pairs:
        val = value if isinstance(value, Text) else Text(value)
        lines.append(Text.assemble((key.ljust(width), "dim"), val) if key else val)
    return Text("\n").join(lines)


def _words(name: str) -> str:
    return name.replace("_", " ").lower()


def _minutes(seconds: float) -> str:
    minutes = seconds / 60
    return f"{minutes:.0f} min" if minutes < 120 else f"{minutes / 60:.1f} h"


def _metres(value: float) -> str:
    return "full" if not value else f"{value:.1f} m"
