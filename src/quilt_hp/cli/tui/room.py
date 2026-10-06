"""Room screen: one room's overview and controls, climate, schedule, energy and devices."""

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar

from textual import on, work
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import DataTable, Footer, Header, OptionList, Static, TabbedContent, TabPane
from textual.widgets.option_list import Option

from quilt_hp.cli.constants import (
    DEFAULT_COOL_SETPOINT_C,
    DEFAULT_HEAT_SETPOINT_C,
    SETPOINT_MAX_C,
    SETPOINT_MIN_C,
    clamp_setpoint_c,
)
from quilt_hp.cli.tui.base import SnapshotHost
from quilt_hp.cli.tui.controls import (
    STEP_C,
    STEP_F_IN_C,
    SetpointChange,
    light_toggle_brightness,
    next_fan,
    next_louver,
    next_mode,
    nudge_setpoint,
    room_lock,
    send_idu_change,
    send_space_change,
    step_cycle,
)
from quilt_hp.cli.tui.dialogs import RoomSettingsScreen, SettingField, ValueDialog
from quilt_hp.cli.tui.format import (
    _FAN_CYCLE,
    _LOUVER_CYCLE,
    _MODE_CYCLE,
    _WEEKDAY_NAMES,
)
from quilt_hp.cli.tui.render import MODE_WORDS
from quilt_hp.cli.tui.room_panels import _CONTROLS, _LIGHT_STEP, TABS, RoomPanels
from quilt_hp.cli.tui.views import (
    EnergySummary,
    energy_summary,
    system_tz,
)

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from quilt_hp.client import QuiltClient
    from quilt_hp.models.system import SystemSnapshot

logger = logging.getLogger(__name__)


class RoomScreen(RoomPanels):
    """Everything about one room, in five tabs; ``[`` and ``]`` move to the other rooms."""

    DEFAULT_CSS = """
    RoomScreen .panel {
        border: round $primary-darken-2; border-title-color: $text; padding: 0 1;
    }
    RoomScreen #ov-top { height: auto; }
    RoomScreen #ov-hero { width: 1fr; height: auto; min-height: 9; margin-right: 1; }
    RoomScreen #ov-controls { width: 1fr; height: auto; min-height: 9; }
    RoomScreen #ov-today { height: auto; margin-top: 1; }
    RoomScreen #climate-row { height: auto; }
    RoomScreen #climate-row > Static { width: 1fr; height: auto; min-height: 9; }
    RoomScreen #cl-air, RoomScreen #cl-unit { margin-right: 1; }
    RoomScreen #cl-raw { height: auto; margin-top: 1; }
    RoomScreen #sch-status { height: 1; margin-bottom: 1; }
    RoomScreen #sch-week { height: auto; }
    RoomScreen #en-top { height: auto; }
    RoomScreen #en-summary { width: 34; height: auto; margin-right: 1; }
    RoomScreen #en-today { width: 1fr; height: auto; }
    RoomScreen #en-days { height: auto; margin-top: 1; }
    RoomScreen OptionList { border: round $primary-darken-2; padding: 0 1; }
    RoomScreen OptionList:focus { border: round $accent; }
    """
    BINDINGS: ClassVar = [
        Binding("escape,b", "back", "Back"),
        Binding("m", "cycle_mode", "Mode"),
        Binding("plus,equals_sign", "setpoint(1)", "Setpoint", key_display="+/−"),
        Binding("minus", "setpoint(-1)", "Setpoint −", show=False),
        Binding("f", "cycle_fan", "Fan"),
        Binding("v", "cycle_louver", "Louver"),
        Binding("l", "toggle_light", "Light"),
        Binding("s", "settings", "Settings"),
        Binding("r", "toggle_raw", "Raw"),
        Binding("left_square_bracket", "switch_room(-1)", "Previous room", show=False),
        Binding("right_square_bracket", "switch_room(1)", "Next room", show=False),
        Binding("left", "adjust(-1)", "Less", show=False),
        Binding("right", "adjust(1)", "More", show=False),
        *(
            Binding(str(i + 1), f"tab('{tab}')", tab.title(), show=False)
            for i, tab in enumerate(TABS)
        ),
        Binding("u", "toggle_units", "°C/°F", show=False),
    ]

    def __init__(
        self,
        space_id: str,
        snapshot: SystemSnapshot,
        client: QuiltClient,
        tab: str = "overview",
    ) -> None:
        super().__init__()
        self.space_id = space_id
        self._snapshot = snapshot  # fallback when not attached to a QuiltApp
        self._client = client
        self._initial_tab = tab
        self._raw = False
        self._energy: EnergySummary | None = None
        self._energy_error: str | None = None

    # ── Layout ──────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(id="room-tabs", initial=f"tab-{self._initial_tab}"):
            with TabPane("1 Overview", id="tab-overview"), VerticalScroll():
                with Horizontal(id="ov-top"):
                    yield Static(id="ov-hero", classes="panel")
                    yield OptionList(*(Option("", id=key) for key in _CONTROLS), id="ov-controls")
                yield Static(id="ov-today", classes="panel")
            with TabPane("2 Climate", id="tab-climate"), VerticalScroll():
                with Horizontal(id="climate-row"):
                    yield Static(id="cl-air", classes="panel")
                    yield Static(id="cl-unit", classes="panel")
                    yield Static(id="cl-presence", classes="panel")
                yield Static(id="cl-raw", classes="panel")
            with TabPane("3 Schedule", id="tab-schedule"), VerticalScroll():
                yield Static(id="sch-status")
                yield DataTable(id="sch-week", cursor_type="none", zebra_stripes=True)
            with TabPane("4 Energy", id="tab-energy"), VerticalScroll():
                with Horizontal(id="en-top"):
                    yield Static(id="en-summary", classes="panel")
                    yield Static(id="en-today", classes="panel")
                yield Static(id="en-days", classes="panel")
            with TabPane("5 Devices", id="tab-devices"), VerticalScroll():
                yield Static(id="dv-list")
        yield Footer()

    def on_mount(self) -> None:
        space = self.space
        self.title = space.name if space else "Room"
        self.sub_title = "[ ] other rooms · 1–5 tabs"
        for widget_id, title in (
            ("#ov-controls", "Controls"),
            ("#ov-today", "Today"),
            ("#cl-air", "Air"),
            ("#cl-unit", "Indoor unit"),
            ("#cl-presence", "Presence"),
            ("#cl-raw", "Raw telemetry"),
            ("#en-summary", "Energy"),
            ("#en-today", "Today by hour (kWh)"),
            ("#en-days", "Last 14 days"),
        ):
            self.query_one(widget_id).border_title = title
        table: DataTable[Any] = self.query_one("#sch-week", DataTable)
        for name in _WEEKDAY_NAMES:
            table.add_column(name[:3], width=12)  # seven fit in 100 columns
        self.render_all()
        if self._initial_tab == "overview":
            # Focusing a widget in another tab would switch to that tab.
            self.query_one("#ov-controls", OptionList).focus()
        self._fetch_energy()
        self.set_interval(600, self._fetch_energy)

    # ── Live updates ────────────────────────────────────────────

    def snapshot_changed(self, kind: str, _entity: object) -> None:
        if self.space is None:
            self.notify("This room was removed from the system.")
            self.app.pop_screen()
            return
        self.render_all()

    def refresh_units(self) -> None:
        self.render_all()

    @work(exclusive=True, group="room-energy")
    async def _fetch_energy(self) -> None:
        tz = system_tz(self.snapshot)
        now = datetime.now(tz=UTC)
        start = (now.astimezone(tz) - timedelta(days=30)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        try:
            metrics = await self._client.get_energy(start=start, end=now)
        except Exception as exc:
            logger.warning("Room energy fetch failed: %s", exc)
            self._energy_error = f"Couldn't load energy: {exc}"
            self._render_energy()
            return
        buckets = next((m.buckets for m in metrics if m.space_id == self.space_id), [])
        self._energy = energy_summary(buckets, tz, now)
        self._energy_error = None
        with contextlib.suppress(Exception):
            self._render_energy()
            self.query_one("#ov-today", Static).update(self._today_chart())

    # ── Navigation ──────────────────────────────────────────────

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_tab(self, tab: str) -> None:
        self.query_one("#room-tabs", TabbedContent).active = f"tab-{tab}"

    def action_switch_room(self, direction: int) -> None:
        ids = [s.id for s in self.snapshot.rooms]
        if self.space_id not in ids or len(ids) < 2:
            return
        target = ids[(ids.index(self.space_id) + direction) % len(ids)]
        active = self.query_one("#room-tabs", TabbedContent).active.removeprefix("tab-")
        self.app.switch_screen(RoomScreen(target, self.snapshot, self._client, tab=active))

    def action_toggle_raw(self) -> None:
        self._raw = not self._raw
        self.render_all()

    def action_toggle_units(self) -> None:
        app = self.app
        if isinstance(app, SnapshotHost):
            app.use_f = not app.use_f

    # ── Controls ────────────────────────────────────────────────

    def action_cycle_mode(self) -> None:
        self._control("mode", 1)

    def action_setpoint(self, direction: int) -> None:
        self._control("setpoint", direction)

    def action_cycle_fan(self) -> None:
        self._control("fan", 1)

    def action_cycle_louver(self) -> None:
        self._control("louver", 1)

    def action_toggle_light(self) -> None:
        self._control("light_toggle", 0)

    def action_adjust(self, direction: int) -> None:
        """← / → change the highlighted control on the Overview tab."""
        controls = self.query_one("#ov-controls", OptionList)
        if not controls.has_focus or controls.highlighted is None:
            return
        key = _CONTROLS[controls.highlighted]
        self._control({"light": "light_step"}.get(key, key), direction)

    @on(OptionList.OptionSelected, "#ov-controls")
    def _on_control_selected(self, event: OptionList.OptionSelected) -> None:
        key = event.option.id or ""
        if key in ("cool", "heat"):
            self._ask_setpoint(key)
        elif key == "light":
            self._control("light_toggle", 0)
        else:
            self._control(key, 1)

    def _ask_setpoint(self, which: str) -> None:
        space = self.space
        if space is None:
            return
        c = space.controls
        current = c.cooling_setpoint_c if which == "cool" else c.heating_setpoint_c
        current = current or (
            DEFAULT_COOL_SETPOINT_C if which == "cool" else DEFAULT_HEAT_SETPOINT_C
        )
        unit = "°F" if self.use_f else "°C"

        def to_display(c_value: float) -> float:
            return c_value * 9 / 5 + 32 if self.use_f else c_value

        def done(value: float | None) -> None:
            if value is None:
                return
            value_c = (value - 32) * 5 / 9 if self.use_f else value
            self._control(f"set_{which}", 0, clamp_setpoint_c(value_c))

        title = f"{space.name}: {'cool' if which == 'cool' else 'heat'} to"
        self.app.push_screen(
            ValueDialog(
                title,
                to_display(current),
                to_display(SETPOINT_MIN_C),
                to_display(SETPOINT_MAX_C),
                unit,
            ),
            done,
        )

    @work(group="room-control")
    async def _control(self, intent: str, direction: int, value: float | None = None) -> None:
        """Apply one control change. Changes for a room run one at a time (shared with Home),
        and each computes its target from the room as the previous change left it."""
        async with room_lock(self.app, self.space_id):
            space, idu = self.space, self.idu
            if space is None:
                return
            step = (STEP_F_IN_C if self.use_f else STEP_C) * direction
            c = space.controls
            try:
                if intent == "mode":
                    mode = (
                        next_mode(space)
                        if direction > 0
                        else step_cycle(c.hvac_mode, _MODE_CYCLE, -1)
                    )
                    await send_space_change(self._client, self.snapshot, space, mode=mode)
                elif intent == "setpoint":
                    change = nudge_setpoint(space, direction, self.use_f)
                    if change is None:
                        self.notify(
                            f"{space.name} has no setpoint in {MODE_WORDS.get(c.hvac_mode, 'this mode')}."
                        )
                        return
                    await send_space_change(self._client, self.snapshot, space, change=change)
                elif intent in ("cool", "heat", "set_cool", "set_heat"):
                    which = intent.removeprefix("set_")
                    current = c.cooling_setpoint_c if which == "cool" else c.heating_setpoint_c
                    current = current or (
                        DEFAULT_COOL_SETPOINT_C if which == "cool" else DEFAULT_HEAT_SETPOINT_C
                    )
                    target = value if value is not None else clamp_setpoint_c(current + step)
                    change = (
                        SetpointChange(cool_c=target)
                        if which == "cool"
                        else SetpointChange(heat_c=target)
                    )
                    await send_space_change(self._client, self.snapshot, space, change=change)
                elif idu is None:
                    self.notify(f"{space.name} has no indoor unit to control.")
                    return
                elif intent == "fan":
                    fan = (
                        next_fan(idu)
                        if direction > 0
                        else step_cycle(idu.controls.fan_speed, _FAN_CYCLE, -1)
                    )
                    await send_idu_change(self._client, self.snapshot, idu, fan_speed=fan)
                elif intent == "louver":
                    louver = (
                        next_louver(idu)
                        if direction > 0
                        else step_cycle(idu.controls.louver_mode, _LOUVER_CYCLE, -1)
                    )
                    await send_idu_change(self._client, self.snapshot, idu, louver_mode=louver)
                elif intent == "light_toggle":
                    await send_idu_change(
                        self._client,
                        self.snapshot,
                        idu,
                        led_brightness=light_toggle_brightness(idu),
                    )
                elif intent == "light_step":
                    level = idu.controls.led_brightness if idu.controls.light_on else 0.0
                    level = min(1.0, max(0.0, round(level + _LIGHT_STEP * direction, 2)))
                    await send_idu_change(self._client, self.snapshot, idu, led_brightness=level)
            except Exception as exc:
                self.notify(f"Couldn't update {space.name}: {exc}", severity="error")
                return
        self.render_all()

    # ── Room settings ───────────────────────────────────────────

    def action_settings(self) -> None:
        space = self.space
        if space is None:
            return
        idu = self.idu
        away = self.snapshot.away_comfort_setting(space)
        f = self.use_f

        def disp(value_c: float | None) -> float | None:
            if value_c is None:
                return None
            return value_c * 9 / 5 + 32 if f else value_c

        unit = "°F" if f else "°C"
        low, high = disp(SETPOINT_MIN_C), disp(SETPOINT_MAX_C)
        assert low is not None and high is not None
        sections = [
            (
                "Auto-away",
                [
                    SettingField(
                        "away_after",
                        "Away after the room is empty",
                        space.settings.unoccupied_timeout_s / 60,
                        1,
                        720,
                        "min",
                        0,
                    ),
                    SettingField(
                        "back_after",
                        "Back after someone returns",
                        space.settings.occupied_timeout_s / 60,
                        1,
                        60,
                        "min",
                        0,
                    ),
                    SettingField(
                        "away_heat",
                        "Away heat to",
                        disp(away.heating_setpoint_c) if away else None,
                        low,
                        high,
                        unit,
                    ),
                    SettingField(
                        "away_cool",
                        "Away cool to",
                        disp(away.cooling_setpoint_c) if away else None,
                        low,
                        high,
                        unit,
                    ),
                ],
            ),
            (
                "Presence sensor (0 = full range)",
                [
                    SettingField(
                        "fence_left",
                        "Detect to the left",
                        idu.settings.presence_fence_left_m if idu else None,
                        0,
                        10,
                        "m",
                    ),
                    SettingField(
                        "fence_right",
                        "Detect to the right",
                        idu.settings.presence_fence_right_m if idu else None,
                        0,
                        10,
                        "m",
                    ),
                    SettingField(
                        "fence_forward",
                        "Detect ahead",
                        idu.settings.presence_fence_forward_m if idu else None,
                        0,
                        10,
                        "m",
                    ),
                    SettingField(
                        "radar_height",
                        "Sensor height above floor",
                        idu.settings.radar_sensor_distance_from_floor_m if idu else None,
                        0,
                        5,
                        "m",
                    ),
                ],
            ),
            (
                "Light",
                [
                    SettingField(
                        "light_default",
                        "Default brightness",
                        idu.settings.light_brightness_default_percent * 100 if idu else None,
                        0,
                        100,
                        "%",
                        0,
                    ),
                ],
            ),
        ]

        def done(changed: dict[str, float] | None) -> None:
            if changed:
                self._save_settings(changed)

        self.app.push_screen(RoomSettingsScreen(space.name, sections), done)

    @work(group="room-control")
    async def _save_settings(self, changed: dict[str, float]) -> None:
        async with room_lock(self.app, self.space_id):
            space, idu = self.space, self.idu
            if space is None:
                return
            use_f = self.use_f

            def to_c(value: float) -> float:
                return (value - 32) * 5 / 9 if use_f else value

            try:
                if "away_after" in changed or "back_after" in changed:
                    updated = await self._client.set_space_settings(
                        space,
                        unoccupied_timeout_s=changed["away_after"] * 60
                        if "away_after" in changed
                        else None,
                        occupied_timeout_s=changed["back_after"] * 60
                        if "back_after" in changed
                        else None,
                    )
                    self.snapshot.apply_space(updated)
                away = self.snapshot.away_comfort_setting(space)
                if away is not None and ("away_heat" in changed or "away_cool" in changed):
                    preset = await self._client.update_comfort_setting(
                        away,
                        heat_setpoint_c=to_c(changed["away_heat"])
                        if "away_heat" in changed
                        else None,
                        cool_setpoint_c=to_c(changed["away_cool"])
                        if "away_cool" in changed
                        else None,
                    )
                    self.snapshot.comfort_settings[:] = [
                        preset if p.id == preset.id else p for p in self.snapshot.comfort_settings
                    ]
                idu_keys = {
                    "fence_left",
                    "fence_right",
                    "fence_forward",
                    "radar_height",
                    "light_default",
                }
                if idu is not None and idu_keys & changed.keys():
                    updated_idu = await self._client.set_indoor_unit_settings(
                        idu,
                        fence_left_m=changed.get("fence_left"),
                        fence_right_m=changed.get("fence_right"),
                        fence_forward_m=changed.get("fence_forward"),
                        radar_height_m=changed.get("radar_height"),
                        light_brightness_default=changed["light_default"] / 100
                        if "light_default" in changed
                        else None,
                    )
                    self.snapshot.apply_indoor_unit(updated_idu)
            except Exception as exc:
                self.notify(f"Couldn't save {space.name} settings: {exc}", severity="error")
                return
        self.notify(f"Saved {space.name} settings", timeout=3)
        self.render_all()
