"""Room screen: Status, Performance, Schedule and Energy tabs for one room."""

from __future__ import annotations

import contextlib
import datetime
import logging
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual import on, work
from textual.binding import Binding
from textual.containers import (
    Horizontal,
    ScrollableContainer,
    Vertical,
)
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Label,
    Rule,
    Static,
    TabbedContent,
    TabPane,
)

from quilt_hp.cli.constants import (
    DEFAULT_COOL_SETPOINT_C,
    DEFAULT_HEAT_SETPOINT_C,
    clamp_setpoint_c,
)
from quilt_hp.cli.tui.base import SnapshotHost
from quilt_hp.cli.tui.format import (
    _FAN_CYCLE,
    _LOUVER_CYCLE,
    _MODE_CYCLE,
    _MODE_STYLE,
    _STATE_STYLE,
    _WEEKDAY_NAMES,
    _cycle_next,
    _fmt_detected,
    _fmt_display,
    _fmt_local_comms,
    _fmt_state,
    _fmt_timeout,
    _led_color_str,
    _sku_or_none,
    _tc,
    hourly_chart,
)
from quilt_hp.cli.tui.shared import _odu_for_space
from quilt_hp.cli.tui.widgets import _KVStatic
from quilt_hp.client import QuiltClient
from quilt_hp.models.controller import Controller
from quilt_hp.models.enums import (
    AmbientTemperatureSource,
    FanSpeed,
    HVACMode,
    HVACState,
    LedAnimation,
    LouverMode,
    OccupancyMode,
    OccupancyState,
    SafetyHeatingMode,
)
from quilt_hp.models.indoor_unit import IndoorUnit
from quilt_hp.models.outdoor_unit import OutdoorUnit
from quilt_hp.models.qsm import QuiltSmartModule, WifiInfo

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from quilt_hp.models.comfort import ComfortSetting
    from quilt_hp.models.enums import MetricBucketStatus
    from quilt_hp.models.schedule import ScheduleDay
    from quilt_hp.models.space import Space
    from quilt_hp.models.system import SystemSnapshot


logger = logging.getLogger(__name__)


# Labels for rows whose data branch may not run (no Dial / no outdoor-unit data).
_SAFETY_HEATING_LABELS = {
    SafetyHeatingMode.UNSPECIFIED: "On (default)",
    SafetyHeatingMode.ENABLED: "On",
    SafetyHeatingMode.DISABLED: "Off",
}
_AMBIENT_SOURCE_LABELS = {
    AmbientTemperatureSource.DEFAULT: "Indoor unit sensor",
    AmbientTemperatureSource.CONTROL: "Dial",
    AmbientTemperatureSource.UNSPECIFIED: "--",
}

_FALLBACK_LABELS: dict[str, str] = {
    "dial-model": "Model",
    "dial-serial": "Serial",
    "dial-fw": "Firmware",
    "dial-ambient": "Ambient",
    "dial-calib": "Raw Thermistor",
    "dial-pcb": "Encoder / SoC",
    "dial-boards": "Main / Power Board",
    "dial-humidity": "Humidity",
    "dial-display": "Display",
    "dial-radar": "Radar Presence",
    "dial-light": "Ambient Light",
    "dial-power": "Power Draw",
    "dial-wifi": "WiFi",
    "dial-wifi-ip": "  IP",
    "dial-wifi-last": "  Last Seen",
    "dial-wifi-ap": "WiFi (AP)",
    "dial-wifi-p2p": "WiFi (P2P)",
    "dial-remote-sensor": "Zone Sensor",
    "dial-crs-temp": "  Zone Temp",
    "dial-crs-humidity": "  Zone Humidity",
    "dial-crs-battery": "  Battery",
    "dial-crs-signal": "  Signal",
    "dial-local-comms": "Local Control",
    "p-odu-freq": "Compressor Freq",
    "p-odu-coil": "ODU Coil Temp",
    "p-odu-exhaust": "Exhaust Temp",
    "p-odu-hi": "High Pressure",
    "p-odu-lo": "Low Pressure",
    "p-odu-ambient": "ODU Ambient",
    "p-odu-state": "ODU State",
    "p-odu-model": "Model",
    "p-odu-serial": "Serial",
    "p-odu-fw": "Firmware",
}


class RoomScreen(Screen[None]):
    """Room detail screen with Status / Performance / Schedule tabs."""

    BINDINGS: ClassVar = [
        Binding("escape,b", "back", "Back"),
        Binding("u", "toggle_units", "°C/°F"),
        # Status tab mutations
        Binding("m", "cycle_mode", "Mode"),
        Binding("H", "heat_up", "Heat+"),
        Binding("h", "heat_down", "Heat-"),
        Binding("C", "cool_up", "Cool+"),
        Binding("c", "cool_down", "Cool-"),
        Binding("f", "cycle_fan", "Fan"),
        Binding("l", "cycle_louver", "Louver"),
        Binding("L", "toggle_led", "LED"),
        Binding("e", "refresh_energy", "Energy ↻"),
        Binding("[", "away_timeout_dec", "Away-5m", show=False),
        Binding("]", "away_timeout_inc", "Away+5m", show=False),
        Binding("{", "return_timeout_dec", "Return-1m", show=False),
        Binding("}", "return_timeout_inc", "Return+1m", show=False),
        # Presence fence adjustment (status tab)
        Binding("ctrl+up", "fence_fwd_inc", "Fence Depth+", show=False),
        Binding("ctrl+down", "fence_fwd_dec", "Fence Depth-", show=False),
        Binding("ctrl+right", "fence_lr_inc", "Fence L/R+", show=False),
        Binding("ctrl+left", "fence_lr_dec", "Fence L/R-", show=False),
        Binding("alt+r", "radar_height_inc", "Radar H+", show=False),
        Binding("alt+t", "radar_height_dec", "Radar H-", show=False),
    ]

    def __init__(
        self,
        space: Space,
        idu: IndoorUnit | None,
        controller: Controller | None,
        odu: OutdoorUnit | None,
        qsm: QuiltSmartModule | None,
        snapshot: SystemSnapshot,
        client: QuiltClient,
        use_f: bool = False,
    ) -> None:
        super().__init__()
        self._space = space
        self._idu = idu
        self._controller = controller
        self._odu = odu
        self._qsm = qsm
        self._snapshot = snapshot  # fallback when not attached to a QuiltApp
        self._client = client
        self._use_f = use_f
        self.title = space.name
        self.sub_title = "Room"

    @property
    def snapshot(self) -> SystemSnapshot:
        """The app-owned snapshot, falling back to the constructor value."""
        with contextlib.suppress(Exception):
            app = self.app
            if isinstance(app, SnapshotHost) and app.snapshot is not None:
                return app.snapshot
        return self._snapshot

    @property
    def use_f(self) -> bool:
        """App-level °C/°F preference (falls back to the constructor value)."""
        with contextlib.suppress(Exception):
            app = self.app
            if isinstance(app, SnapshotHost):
                return app.use_f
        return self._use_f

    # Entity IDs for the app-level stream dispatchers.

    @property
    def space_id(self) -> str:
        return self._space.id

    @property
    def idu_id(self) -> str | None:
        return self._idu.id if self._idu else None

    @property
    def odu_id(self) -> str | None:
        return self._odu.id if self._odu else None

    @property
    def controller_id(self) -> str | None:
        return self._controller.id if self._controller else None

    @property
    def qsm_id(self) -> str | None:
        return self._qsm.id if self._qsm else None

    # ── Layout ──────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(id="room-tabs"):
            with TabPane("Status", id="tab-status"):
                yield from self._compose_status()
            with TabPane("Performance", id="tab-perf"):
                yield from self._compose_perf()
            with TabPane("Schedule", id="tab-schedule"):
                yield from self._compose_schedule()
            with TabPane("Energy", id="tab-energy"):
                yield from self._compose_energy()
        yield Footer()

    def _compose_status(self) -> ComposeResult:
        with Horizontal(classes="controls-sensors-row"):
            # Controls panel
            with Vertical(classes="panel controls-panel") as v:
                v.border_title = "Controls"
                yield _KVStatic(id="ctl-mode")
                yield _KVStatic(id="ctl-heat")
                yield _KVStatic(id="ctl-cool")
                yield _KVStatic(id="ctl-fan")
                yield _KVStatic(id="ctl-louver")
                yield _KVStatic(id="ctl-louver-pos")
                yield _KVStatic(id="ctl-boost")
                yield _KVStatic(id="ctl-led")
                yield _KVStatic(id="ctl-led-color")
                yield _KVStatic(id="ctl-led-anim")
                yield _KVStatic(id="ctl-preset")
                yield _KVStatic(id="ctl-preset-override")
                yield _KVStatic(id="ctl-state-preset")
                yield _KVStatic(id="ctl-occ-mode")
                yield _KVStatic(id="ctl-safety")
                yield _KVStatic(id="ctl-away-after")
                yield _KVStatic(id="ctl-return-after")
                yield _KVStatic(id="ctl-away-temps")
            # Sensors panel
            with Vertical(classes="panel sensors-panel", id="sensors-panel") as v:
                v.border_title = "Sensors"
                yield _KVStatic(id="sen-ambient")
                yield _KVStatic(id="sen-calc-ambient")
                yield _KVStatic(id="sen-humidity")
                yield _KVStatic(id="sen-fan-rpm")
                yield _KVStatic(id="sen-fan-setpoint-rpm")
                yield _KVStatic(id="sen-setpoint")
                yield _KVStatic(id="sen-inlet")
                yield _KVStatic(id="sen-outlet")
                yield _KVStatic(id="sen-louver-angle")
                yield _KVStatic(id="sen-state")
                yield _KVStatic(id="sen-occ-state")
                yield _KVStatic(id="sen-presence-l")
                yield _KVStatic(id="sen-presence-r")
                yield _KVStatic(id="sen-presence-level")
                yield _KVStatic(id="sen-fence-lr")
                yield _KVStatic(id="sen-fence-fwd")
                yield _KVStatic(id="sen-radar-height")
                yield _KVStatic(id="sen-idu-mode")
                yield _KVStatic(id="sen-idu-name")
                yield _KVStatic(id="sen-idu-light-default")
                yield _KVStatic(id="sen-dew-point")
                yield _KVStatic(id="sen-test")
        yield Rule(classes="section-rule")
        # Dial and QSM panels side by side
        with Horizontal(classes="controls-sensors-row"):
            # Dial panel
            with Vertical(classes="panel dial-panel", id="dial-panel") as v:
                v.border_title = "Dial (Thermostat)"
                yield _KVStatic(id="dial-model")
                yield _KVStatic(id="dial-serial")
                yield _KVStatic(id="dial-fw")
                yield _KVStatic(id="dial-ambient")
                yield _KVStatic(id="dial-calib")
                yield _KVStatic(id="dial-pcb")
                yield _KVStatic(id="dial-boards")
                yield _KVStatic(id="dial-humidity")
                yield _KVStatic(id="dial-display")
                yield _KVStatic(id="dial-radar")
                yield _KVStatic(id="dial-light")
                yield _KVStatic(id="dial-power")
                yield _KVStatic(id="dial-wifi")
                yield _KVStatic(id="dial-wifi-ip")
                yield _KVStatic(id="dial-wifi-last")
                yield _KVStatic(id="dial-wifi-ap")
                yield _KVStatic(id="dial-wifi-p2p")
                yield _KVStatic(id="dial-remote-sensor")
                yield _KVStatic(id="dial-crs-temp")
                yield _KVStatic(id="dial-crs-humidity")
                yield _KVStatic(id="dial-crs-battery")
                yield _KVStatic(id="dial-crs-signal")
                yield _KVStatic(id="dial-local-comms")
            # QSM panel
            with Vertical(classes="panel qsm-panel") as v:
                v.border_title = "QSM (Smart Module)"
                yield _KVStatic(id="qsm-wifi-hosted")
                yield _KVStatic(id="qsm-wifi-ap")
                yield _KVStatic(id="qsm-wifi-p2p")
                yield _KVStatic(id="qsm-presence")
                yield _KVStatic(id="qsm-als")
                yield _KVStatic(id="qsm-accel")
                yield _KVStatic(id="qsm-local-comms")

    def _compose_perf(self) -> ComposeResult:
        with Horizontal(classes="perf-row"):
            with ScrollableContainer(classes="panel perf-left") as v:
                v.border_title = "IDU / ODU"
                yield Label("IDU Temperatures", classes="section-label")
                yield _KVStatic(id="p-coil")
                yield _KVStatic(id="p-outlet")
                yield _KVStatic(id="p-inlet")
                yield _KVStatic(id="p-gas")
                yield _KVStatic(id="p-liquid")
                yield Rule()
                yield Label("HVAC Inputs (Controller→IDU)", classes="section-label")
                yield _KVStatic(id="p-hi-ext-ambient")
                yield _KVStatic(id="p-hi-setpoint")
                yield _KVStatic(id="p-hi-mode")
                yield _KVStatic(id="p-hi-state")
                yield _KVStatic(id="p-hi-source")
                yield _KVStatic(id="p-hi-ctrl-type")
                yield Rule()
                yield Label("ODU Compressor", classes="section-label")
                yield _KVStatic(id="p-odu-state")
                yield _KVStatic(id="p-odu-freq")
                yield _KVStatic(id="p-odu-coil")
                yield _KVStatic(id="p-odu-exhaust")
                yield _KVStatic(id="p-odu-hi")
                yield _KVStatic(id="p-odu-lo")
                yield _KVStatic(id="p-odu-ambient")
            with ScrollableContainer(classes="panel perf-right") as v:
                v.border_title = "Energy / Efficiency"
                yield Label("IDU Energy", classes="section-label")
                yield _KVStatic(id="p-interval")
                yield _KVStatic(id="p-energy-j")
                yield _KVStatic(id="p-energy-kwh")
                yield _KVStatic(id="p-fan-actual")
                yield _KVStatic(id="p-pd-mode")
                yield _KVStatic(id="p-pd-state")
                yield Rule()
                yield Label("Efficiency", classes="section-label")
                yield _KVStatic(id="p-capacity")
                yield _KVStatic(id="p-cop")
                yield _KVStatic(id="p-hvac-power")
                yield _KVStatic(id="p-led-power")
                yield _KVStatic(id="p-odu-share")
                yield _KVStatic(id="p-pm-mode")
                yield _KVStatic(id="p-pm-state")
                yield _KVStatic(id="p-pm-duration")
                yield _KVStatic(id="p-pm-energy-total")
                yield _KVStatic(id="p-pm-hvac-energy")
                yield _KVStatic(id="p-pm-led-energy")
                yield Rule()
                yield Label("IDU Conditions", classes="section-label")
                yield _KVStatic(id="p-cond-defrost")
                yield _KVStatic(id="p-cond-oilreturn")
                yield _KVStatic(id="p-cond-coilpreheat")
                yield _KVStatic(id="p-cond-safetyheat")
                yield _KVStatic(id="p-cond-anticold")
                yield _KVStatic(id="p-cond-modeswitch")
                yield _KVStatic(id="p-cond-modeconflict")
                yield _KVStatic(id="p-cond-modeconflictavoid")
                yield _KVStatic(id="p-cond-abnormal-odu-air")
                yield _KVStatic(id="p-cond-odu-comm")
                yield _KVStatic(id="p-cond-modbus")
                yield Rule()
                yield Label("ODU Hardware", classes="section-label")
                yield _KVStatic(id="p-odu-model")
                yield _KVStatic(id="p-odu-serial")
                yield _KVStatic(id="p-odu-fw")
                yield Rule()
                yield Label("IDU Commands", classes="section-label")
                yield _KVStatic(id="p-cmd-fallback")

    def _compose_schedule(self) -> ComposeResult:
        yield Static("", id="sched-status")
        with Horizontal(classes="sched-row"):
            with ScrollableContainer(classes="sched-days-panel") as v:
                v.border_title = "Schedule"
                yield DataTable(id="sched-week", show_cursor=True, cursor_type="row")
            with ScrollableContainer(classes="sched-events-panel", id="sched-events-panel") as v:
                v.border_title = "Events"
                yield DataTable(id="sched-day", show_cursor=False)

    def _compose_energy(self) -> ComposeResult:
        yield Static("", id="energy-status")
        with Vertical(classes="energy-summary") as v:
            v.border_title = "Energy Summary"
            yield _KVStatic(id="e-today")
            yield _KVStatic(id="e-yesterday")
            yield _KVStatic(id="e-7day")
            yield _KVStatic(id="e-30day")
        with Vertical(classes="energy-chart") as v:
            v.border_title = "Today — Hourly (kWh)"
            yield Static("", id="e-sparkline")
        yield DataTable(id="e-table")

    # ── Mount: populate all panels ───────────────────────────────

    def on_mount(self) -> None:
        self._populate_status()
        self._populate_perf()
        self._populate_schedule()
        self._fetch_energy()

    def _populate_status(self) -> None:
        space = self._space
        idu = self._idu
        ctrl = self._controller
        use_f = self.use_f

        c = space.controls
        s = space.state
        sets = space.settings

        # Look up comfort preset name
        preset_name = "--"
        if c.comfort_setting_id:
            cs = next(
                (x for x in self.snapshot.comfort_settings if x.id == c.comfort_setting_id),
                None,
            )
            if cs:
                preset_name = cs.name
                if cs.name.casefold() != cs.type.name.replace("_", " ").casefold():
                    preset_name += f" ({cs.type.name.replace('_', ' ').title()})"

        if space.is_away:
            mode_label, mode_style = "AWAY", "yellow dim"
        elif space.is_off:
            mode_label, mode_style = "OFF", "dim"
        else:
            mode_label = space.controls.hvac_mode.name
            mode_style = _MODE_STYLE.get(space.controls.hvac_mode, "")
        self._kv("ctl-mode", "Mode", mode_label, mode_style)
        self._kv("ctl-heat", "Heat Setpoint", _tc(c.heating_setpoint_c, use_f), "red")
        self._kv(
            "ctl-cool",
            "Cool Setpoint",
            _tc(c.cooling_setpoint_c, use_f),
            "cyan",
        )
        self._kv("ctl-fan", "Fan Speed", idu.controls.fan_speed.name if idu else "--")
        self._kv(
            "ctl-louver",
            "Louver",
            idu.controls.louver_mode.name if idu else "--",
        )
        if (
            idu
            and idu.controls.louver_mode == LouverMode.FIXED
            and idu.controls.louver_fixed_position
        ):
            self._kv(
                "ctl-louver-pos",
                "  Fixed Pos",
                f"{idu.controls.louver_fixed_position:.1f}°",
            )
        else:
            self._kv("ctl-louver-pos", "  Fixed Pos", "--")
        boost_str = "--"
        if idu and c.boost_mode.name not in ("UNSPECIFIED",):
            boost_str = "ON" if c.boost_mode.name == "ON" else "Off"
        elif idu:
            boost_str = "Off"
        self._kv(
            "ctl-boost",
            "Boost Mode",
            boost_str,
            "bold yellow" if boost_str == "ON" else "",
        )
        led_str = "--"
        led_color_str = "--"
        led_anim_str = "--"
        if idu:
            if not idu.is_online:
                led_str = "OFF (offline)"
                led_color_str = "--"
                led_anim_str = "--"
            elif idu.led_on:
                led_str = f"ON  {idu.controls.led_brightness * 100:.0f}%"
                led_color_str = _led_color_str(idu.controls.led_color_code)
                anim = idu.controls.led_animation
                led_anim_str = (
                    anim.name.replace("_", " ").title()
                    if anim not in (LedAnimation.UNSPECIFIED, LedAnimation.NONE)
                    else "None"
                )
            else:
                led_str = "OFF"
                led_color_str = "--"
                led_anim_str = "--"
        self._kv("ctl-led", "LED", led_str)
        self._kv("ctl-led-color", "  Color", led_color_str)
        self._kv("ctl-led-anim", "  Effect", led_anim_str)
        self._kv("ctl-preset", "Comfort Preset", preset_name, "yellow")
        # Comfort setting override: why the current preset was applied
        override = c.comfort_setting_override
        from quilt_hp.models.enums import ComfortSettingOverride

        override_labels = {
            ComfortSettingOverride.NONE: ("Schedule", "dim"),
            ComfortSettingOverride.UNTIL_NEXT_SCHEDULE: (
                "Manual (until next event)",
                "yellow",
            ),
            ComfortSettingOverride.INDEFINITE: (
                "Manual (indefinite)",
                "yellow",
            ),
            ComfortSettingOverride.SCHEDULE: ("Schedule", "dim"),
            ComfortSettingOverride.UNOCCUPIED: ("Auto-Away", "yellow dim"),
            ComfortSettingOverride.OCCUPIED: ("Auto-Return", "green dim"),
        }
        ov_str, ov_style = override_labels.get(
            override, (override.name.replace("_", " ").title(), "")
        )
        self._kv("ctl-preset-override", "  Applied Via", ov_str, ov_style)
        # State-reported active comfort setting may differ from controls preset.
        state_preset_name = "--"
        if s.comfort_setting_id:
            cs_state = next(
                (x for x in self.snapshot.comfort_settings if x.id == s.comfort_setting_id),
                None,
            )
            if cs_state:
                state_preset_name = cs_state.name
            elif s.comfort_setting_id != c.comfort_setting_id:
                state_preset_name = f"…{s.comfort_setting_id[-8:]}"
        self._kv(
            "ctl-state-preset",
            "  Active (state)",
            state_preset_name,
            "yellow dim",
        )
        occ_mode_label = sets.occupancy_mode.name.capitalize()
        self._kv("ctl-occ-mode", "Occupancy Mode", occ_mode_label)
        self._kv(
            "ctl-safety",
            "Safety Heating",
            _SAFETY_HEATING_LABELS.get(sets.safety_heating, sets.safety_heating.name.title()),
        )

        # Auto-away / auto-return timeouts (editable with [ ] { })
        away_style = "" if sets.occupancy_mode == OccupancyMode.ENABLED else "dim"
        self._kv(
            "ctl-away-after",
            "Auto-Away After",
            _fmt_timeout(sets.unoccupied_timeout_s),
            away_style,
        )
        self._kv(
            "ctl-return-after",
            "Auto-Return After",
            _fmt_timeout(sets.occupied_timeout_s),
            away_style,
        )

        # Away temperatures — from the space's AWAY comfort setting
        away_cs = next(
            (
                cs
                for cs in self.snapshot.comfort_settings
                if cs.space_id == space.id and cs.type.name == "AWAY"
            ),
            None,
        )
        if away_cs:
            away_temps = (
                f"Heat {_tc(away_cs.heating_setpoint_c, use_f)} / "
                f"Cool {_tc(away_cs.cooling_setpoint_c, use_f)}"
            )
            self._kv("ctl-away-temps", "Away Temps", away_temps, "yellow dim")
        else:
            self._kv("ctl-away-temps", "Away Temps", "not configured", "dim")

        # Update panel titles with offline status
        idu_title = "Sensors  [dim]F/G depth  X/Z L/R  R/T height[/dim]"
        if idu and not idu.is_online:
            idu_title = "Sensors  [bold red]⚠ IDU OFFLINE[/]"
        with contextlib.suppress(Exception):
            self.query_one("#sensors-panel").border_title = idu_title

        dial_title = "Dial (Thermostat)"
        if ctrl and not ctrl.is_online:
            dial_title = "Dial (Thermostat)  [bold red]⚠ OFFLINE[/]"
        with contextlib.suppress(Exception):
            self.query_one("#dial-panel").border_title = dial_title

        self._kv(
            "sen-ambient",
            "Ambient Temp",
            _tc(s.ambient_temperature_c, use_f),
            "green",
        )
        if idu and idu.state.calculated_ambient_temperature_c is not None:
            self._kv(
                "sen-calc-ambient",
                "Ambient (calc)",
                _tc(idu.state.calculated_ambient_temperature_c, use_f),
            )
        else:
            self._kv("sen-calc-ambient", "Ambient (calc)", "--")
        self._kv(
            "sen-humidity",
            "Humidity",
            f"{idu.state.ambient_humidity_percent:.0f}%"
            if idu and idu.state.ambient_humidity_percent is not None
            else "--",
        )
        fan_rpm = idu.state.fan_speed_rpm if idu and idu.state else None
        if fan_rpm is None:
            fan_rpm_str = "--"
        else:
            # 0 RPM is a real reading — the fan is off.
            fan_rpm_str = f"{fan_rpm:.0f} RPM" if fan_rpm else "Off"
        self._kv(
            "sen-fan-rpm",
            "Fan Speed (actual)",
            fan_rpm_str,
        )
        fan_sp_rpm = idu.state.fan_speed_setpoint_rpm if idu and idu.state else None
        self._kv(
            "sen-fan-setpoint-rpm",
            "Fan Speed (setpoint)",
            f"{fan_sp_rpm:.0f} RPM" if fan_sp_rpm else "--",
        )
        self._kv("sen-setpoint", "Active Setpoint", _tc(s.setpoint_c, use_f))
        if idu and idu.state.inlet_temperature_c is not None:
            self._kv(
                "sen-inlet",
                "Inlet Temp",
                _tc(idu.state.inlet_temperature_c, use_f),
            )
        else:
            self._kv("sen-inlet", "Inlet Temp", "--")
        if idu and idu.state.outlet_temperature_c is not None:
            self._kv(
                "sen-outlet",
                "Outlet Temp",
                _tc(idu.state.outlet_temperature_c, use_f),
            )
        else:
            self._kv("sen-outlet", "Outlet Temp", "--")
        if idu and idu.state.louver_angle_up_down_degrees is not None:
            self._kv(
                "sen-louver-angle",
                "Louver Angle",
                f"{idu.state.louver_angle_up_down_degrees:.1f}°",
            )
        else:
            self._kv("sen-louver-angle", "Louver Angle", "--")
        state_fmt = _fmt_state(s.hvac_state)
        self._kv("sen-state", "HVAC State", state_fmt.plain, str(state_fmt.style))
        raw_occ = idu.effective_occupancy_state if idu else None
        occ_state = OccupancyState(raw_occ) if raw_occ is not None else None
        if occ_state == OccupancyState.DETECTED:
            occ_str, occ_style = "Occupied", "green"
        elif occ_state == OccupancyState.UNDETECTED:
            occ_str, occ_style = "Vacant", "dim"
        elif idu and not idu.is_online:
            occ_str, occ_style = "offline", "dim italic"
        else:
            occ_str, occ_style = "--", "dim italic"
        # occupancy_state is the auto-away engine decision (lags real presence
        # unoccupied_timeout_s).  It controls HVAC setback, not live radar.
        self._kv("sen-occ-state", "Occupancy (auto-away)", occ_str, occ_style)

        # Presence channels — binary DETECTED / UNDETECTED per radar detection
        # channel.  One physical radar, two channels; they move in lockstep in
        # practice and the vendor app ORs them (never "left"/"right" sensors).
        if idu and idu.presence:
            from quilt_hp.models.enums import Presence

            def _presence_str(p: Presence) -> tuple[str, str]:
                if p == Presence.DETECTED:
                    return "Detected", "green bold"
                if p == Presence.UNDETECTED:
                    return "Not Detected", "dim"
                return "--", "dim italic"

            ch0_str, ch0_style = _presence_str(idu.presence.sensor0_presence)
            ch1_str, ch1_style = _presence_str(idu.presence.sensor1_presence)
            self._kv("sen-presence-l", "Radar ch 0", ch0_str, ch0_style)
            self._kv("sen-presence-r", "Radar ch 1", ch1_str, ch1_style)
        else:
            self._kv("sen-presence-l", "Radar ch 0", "--")
            self._kv("sen-presence-r", "Radar ch 1", "--")

        # Presence detection level and fence geometry (from IDU settings)
        if idu:
            pdl = idu.state.presence_detection_level
            pdl_str = f"{pdl:.2f}" if pdl is not None else "--"
            self._kv("sen-presence-level", "Detection Level", pdl_str)
            st = idu.settings
            if st.presence_fence_left_m or st.presence_fence_right_m:
                lr_str = (
                    f"L {st.presence_fence_left_m:.2f} m  /  R {st.presence_fence_right_m:.2f} m"
                )
            else:
                lr_str = "[dim]unconfigured (max range)[/dim]"
            if st.presence_fence_forward_m:
                fwd_str = f"{st.presence_fence_forward_m:.2f} m"
            else:
                fwd_str = "[dim]unconfigured (max range)[/dim]"
            h_str = (
                f"{st.radar_sensor_distance_from_floor_m:.2f} m"
                if st.radar_sensor_distance_from_floor_m
                else "[dim]unconfigured[/dim]"
            )
            self._kv("sen-fence-lr", "Fence L/R", lr_str)
            self._kv("sen-fence-fwd", "Fence Depth", fwd_str)
            self._kv("sen-radar-height", "Radar Height", h_str)
        else:
            self._kv("sen-presence-level", "Detection Level", "--")
            self._kv("sen-fence-lr", "Fence L/R", "--")
            self._kv("sen-fence-fwd", "Fence Depth", "--")
            self._kv("sen-radar-height", "Radar Height", "--")

        idu_mode_str = idu.state.hvac_mode.name if idu and idu.state else "--"
        idu_mode_style = _MODE_STYLE.get(idu.state.hvac_mode, "") if idu and idu.state else ""
        self._kv("sen-idu-mode", "IDU Mode", idu_mode_str, idu_mode_style)
        if idu and idu.settings:
            self._kv("sen-idu-name", "IDU Name", idu.settings.name or "--")
            light_pct = idu.settings.light_brightness_default_percent
            self._kv(
                "sen-idu-light-default",
                "Default Brightness",
                f"{light_pct * 100:.0f}%" if light_pct else "--",
            )
        else:
            self._kv("sen-idu-name", "IDU Name", "--")
            self._kv("sen-idu-light-default", "Default Brightness", "--")
        self._kv("sen-dew-point", "Dew Point", _tc(idu.dew_point_c if idu else None, use_f))
        if idu and idu.is_under_test:
            test = idu.effective_test_mode.name.replace("_", " ").title()
            phase = idu.test_state.test_phase if idu.test_state else None
            if phase is not None and phase.name not in ("UNSPECIFIED", "NONE"):
                test += f" · {phase.name.replace('_', ' ').lower()}"
            self._kv("sen-test", "Test", f"⚠ {test}", "bold yellow")
        else:
            self._kv("sen-test", "Test", "none" if idu else "--", "dim")

        # Dial / Controller
        def _wifi_str(w: WifiInfo | None) -> str:
            if not w:
                return "--"
            parts = []
            if w.ssid:
                parts.append(w.ssid)
            if w.ip:
                parts.append(w.ip)
            if w.signal_dbm:
                parts.append(f"{w.signal_dbm} dBm")
            return "  ·  ".join(parts) if parts else "--"

        if ctrl:
            self._kv("dial-model", "Model", _sku_or_none(ctrl.model_sku) or "--")
            self._kv("dial-serial", "Serial", ctrl.serial_number or "--")
            self._kv("dial-fw", "Firmware", ctrl.firmware_version or "--")
            self._kv(
                "dial-ambient",
                "Ambient",
                _tc(ctrl.calibrated_ambient_c, use_f),
                "green",
            )
            self._kv(
                "dial-calib",
                "Raw Thermistor",
                _tc(ctrl.raw_thermistor_c, use_f),
            )
            self._kv(
                "dial-pcb",
                "Encoder / SoC",
                f"{_tc(ctrl.pcb_temperature_a_c, use_f)}  /  "
                f"{_tc(ctrl.pcb_temperature_b_c, use_f)}",
            )
            self._kv(
                "dial-boards",
                "Main / Power Board",
                f"{_tc(ctrl.main_board_temperature_c, use_f)}  /  "
                f"{_tc(ctrl.power_board_temperature_c, use_f)}",
            )
            self._kv(
                "dial-humidity",
                "Humidity",
                f"{ctrl.humidity_percent:.0f}%" if ctrl.humidity_percent is not None else "--",
            )
            disp, disp_style = _fmt_display(ctrl)
            self._kv("dial-display", "Display", disp, disp_style)
            live = ctrl.is_online  # an offline Dial's last readings are not current
            radar, radar_style = _fmt_detected(ctrl.presence_detected if live else None)
            self._kv("dial-radar", "Radar Presence", radar, radar_style)
            self._kv(
                "dial-light",
                "Ambient Light",
                f"{ctrl.ambient_light_lux:.0f} lx"
                if live and ctrl.ambient_light_lux is not None
                else "--",
            )
            self._kv(
                "dial-power",
                "Power Draw",
                f"{ctrl.power_w:.2f} W" if ctrl.power_w is not None else "--",
            )
            # Wi-Fi status: SSID, band, signal
            wifi_parts = []
            if ctrl.wifi_ssid:
                wifi_parts.append(ctrl.wifi_ssid)
            if ctrl.wifi_band:
                wifi_parts.append(ctrl.wifi_band)
            if ctrl.wifi_signal_dbm:
                wifi_parts.append(f"{ctrl.wifi_signal_dbm} dBm")
            self._kv("dial-wifi", "WiFi", "  ·  ".join(wifi_parts) or "--")
            self._kv("dial-wifi-ip", "  IP", ctrl.wifi_ip or "--")
            # Last seen: format as local time if available
            if ctrl.wifi_last_seen:
                local_ts = ctrl.wifi_last_seen.astimezone()
                last_seen_str = local_ts.strftime("%Y-%m-%d %H:%M:%S")
            else:
                last_seen_str = "--"
            self._kv("dial-wifi-last", "  Last Seen", last_seen_str)
            self._kv("dial-wifi-ap", "WiFi (AP)", _wifi_str(ctrl.ap_wifi))
            self._kv("dial-wifi-p2p", "WiFi (P2P)", _wifi_str(ctrl.p2p_wifi))
            rsm = ctrl.remote_sensor_mode
            rsm_str = (
                "Enabled"
                if rsm.name == "ENABLED"
                else ("Disabled" if rsm.name == "DISABLED" else "--")
            )
            rsm_style = "green" if rsm.name == "ENABLED" else "dim"
            self._kv("dial-remote-sensor", "Zone Sensor", rsm_str, rsm_style)
            # ControllerRemoteSensor — Dial acting as zone sensor
            crs = next(
                (r for r in self.snapshot.controller_remote_sensors if r.controller_id == ctrl.id),
                None,
            )
            if crs:
                self._kv(
                    "dial-crs-temp",
                    "  Zone Temp",
                    _tc(crs.ambient_temperature_c, use_f),
                    "green",
                )
                self._kv(
                    "dial-crs-humidity",
                    "  Zone Humidity",
                    f"{crs.humidity_percent:.0f}%" if crs.humidity_percent is not None else "--",
                )
                self._kv(
                    "dial-crs-battery",
                    "  Battery",
                    f"{crs.battery_level_percent:.0f}%"
                    if crs.battery_level_percent is not None
                    else "--",
                )
                self._kv(
                    "dial-crs-signal",
                    "  Signal",
                    f"{crs.signal_level_dbm} dBm" if crs.signal_level_dbm else "--",
                )
            else:
                self._kv("dial-crs-temp", "  Zone Temp", "--")
                self._kv("dial-crs-humidity", "  Zone Humidity", "--")
                self._kv("dial-crs-battery", "  Battery", "--")
                self._kv("dial-crs-signal", "  Signal", "--")
            lc_label, lc_style = _fmt_local_comms(ctrl.local_comms_health)
            self._kv("dial-local-comms", "Local Control", lc_label, lc_style)
        else:
            for nid in (
                "dial-model",
                "dial-serial",
                "dial-fw",
                "dial-ambient",
                "dial-calib",
                "dial-pcb",
                "dial-boards",
                "dial-humidity",
                "dial-display",
                "dial-radar",
                "dial-light",
                "dial-power",
                "dial-wifi",
                "dial-wifi-ip",
                "dial-wifi-last",
                "dial-wifi-ap",
                "dial-wifi-p2p",
                "dial-remote-sensor",
                "dial-crs-temp",
                "dial-crs-humidity",
                "dial-crs-battery",
                "dial-crs-signal",
                "dial-local-comms",
            ):
                self._kv_empty(nid, "--")

        # QSM / Smart Module
        qsm = self._qsm

        if qsm:
            self._kv("qsm-wifi-hosted", "WiFi (hosted)", _wifi_str(qsm.hosted_wifi))
            self._kv("qsm-wifi-ap", "WiFi (AP)", _wifi_str(qsm.ap_wifi))
            self._kv("qsm-wifi-p2p", "WiFi (P2P)", _wifi_str(qsm.p2p_wifi))
            if qsm.sensors:
                sensors = qsm.sensors
                self._kv(
                    "qsm-presence",
                    "Presence",
                    f"phase {sensors.phase_detected_raw:.3f}  target {sensors.target_detected_raw:.3f}",
                )
                self._kv(
                    "qsm-als",
                    "Light (ALS)",
                    f"illum {sensors.als_illuminance_raw}  IR {sensors.als_ir_raw}  both {sensors.als_both_raw}",
                )
                self._kv(
                    "qsm-accel",
                    "Accel X/Y/Z",
                    f"{sensors.accel_x_raw}  /  {sensors.accel_y_raw}  /  {sensors.accel_z_raw}",
                )
            else:
                for nid, lbl in [
                    ("qsm-presence", "Presence"),
                    ("qsm-als", "ALS"),
                    ("qsm-accel", "Accel"),
                ]:
                    self._kv(nid, lbl, "--")
            lc_label, lc_style = _fmt_local_comms(qsm.local_comms_health)
            self._kv("qsm-local-comms", "Local Control", lc_label, lc_style)
        else:
            for nid, lbl in [
                ("qsm-wifi-hosted", "WiFi (hosted)"),
                ("qsm-wifi-ap", "WiFi (AP)"),
                ("qsm-wifi-p2p", "WiFi (P2P)"),
                ("qsm-presence", "Presence"),
                ("qsm-als", "ALS"),
                ("qsm-accel", "Accel"),
                ("qsm-local-comms", "Local Control"),
            ]:
                self._kv(nid, lbl, "no QSM")

    def _populate_perf(self) -> None:
        idu = self._idu
        odu = self._odu
        use_f = self.use_f

        _COND_STATE_LABELS = {0: "—", 1: "inactive", 2: "ACTIVE"}
        _COND_ACTIVE_STYLE = "bold red"

        if idu and idu.performance_data:
            pd = idu.performance_data
            self._kv("p-coil", "Coil Temp", _tc(pd.coil_temperature_c, use_f))
            self._kv("p-outlet", "Outlet Temp", _tc(pd.outlet_temperature_c, use_f))
            self._kv("p-inlet", "Inlet Temp", _tc(pd.inlet_temperature_c, use_f))
            self._kv("p-gas", "Gas Pipe Temp", _tc(pd.gas_pipe_temperature_c, use_f))
            self._kv(
                "p-liquid",
                "Liquid Pipe Temp",
                _tc(pd.liquid_pipe_temperature_c, use_f),
            )
            self._kv(
                "p-interval",
                "Sample Interval",
                f"{pd.measurement_interval_s:.1f} s",
            )
            # energy_measurement_j is IDU electronics (QSM + fan board),
            # not HVAC/compressor energy.
            # Actual HVAC power is in performance_metrics below.
            pwr = (
                pd.energy_measurement_j / pd.measurement_interval_s
                if pd.measurement_interval_s > 0
                else 0
            )
            self._kv("p-energy-j", "IDU Module Power", f"{pwr:.1f} W")
            self._kv(
                "p-energy-kwh",
                "IDU Module Energy",
                f"{pd.energy_measurement_j:.1f} J",
            )
            self._kv(
                "p-fan-actual",
                "Fan (actual)",
                f"{pd.actual_fan_speed_rpm:.0f} RPM",
            )
            self._kv(
                "p-pd-mode",
                "Mode (perf)",
                pd.hvac_mode.name,
                _MODE_STYLE.get(pd.hvac_mode, ""),
            )
            pd_state_fmt = _fmt_state(pd.hvac_state)
            self._kv(
                "p-pd-state",
                "State (perf)",
                pd_state_fmt.plain,
                str(pd_state_fmt.style),
            )
        else:
            for nid, label in [
                ("p-coil", "Coil"),
                ("p-outlet", "Outlet"),
                ("p-inlet", "Inlet"),
                ("p-gas", "Gas Pipe"),
                ("p-liquid", "Liquid Pipe"),
                ("p-interval", "Interval"),
                ("p-energy-j", "Energy J"),
                ("p-energy-kwh", "Energy kWh"),
                ("p-fan-actual", "Fan actual"),
                ("p-pd-mode", "Mode (perf)"),
                ("p-pd-state", "State (perf)"),
            ]:
                self._kv(nid, label, "no data")

        if idu and idu.performance_metrics:
            pm = idu.performance_metrics
            self._kv("p-capacity", "Capacity", f"{pm.capacity_w:.0f} W")
            self._kv("p-cop", "COP", f"{pm.coefficient_of_performance:.2f}")
            self._kv("p-hvac-power", "HVAC Power", f"{pm.hvac_power_w:.0f} W")
            self._kv("p-led-power", "LED Power", f"{pm.led_power_w:.1f} W")
            self._kv(
                "p-odu-share",
                "Outdoor-Unit Share",
                f"{pm.odu_usage_fraction:.0%}" if pm.odu_usage_fraction else "--",
            )
            self._kv(
                "p-pm-mode",
                "Mode (metrics)",
                pm.hvac_mode.name,
                _MODE_STYLE.get(pm.hvac_mode, ""),
            )
            pm_state_fmt = _fmt_state(pm.hvac_state)
            self._kv(
                "p-pm-state",
                "State (metrics)",
                pm_state_fmt.plain,
                str(pm_state_fmt.style),
            )
            self._kv("p-pm-duration", "Window", f"{pm.measurement_duration_s:.1f} s")
            self._kv(
                "p-pm-energy-total",
                "Energy (total)",
                f"{pm.energy_total_j:.1f} J",
            )
            self._kv("p-pm-hvac-energy", "Energy (HVAC)", f"{pm.hvac_energy_j:.1f} J")
            self._kv("p-pm-led-energy", "Energy (LED)", f"{pm.led_energy_j:.1f} J")
        else:
            for nid, label in [
                ("p-capacity", "Capacity"),
                ("p-cop", "COP"),
                ("p-hvac-power", "HVAC Power"),
                ("p-led-power", "LED Power"),
                ("p-odu-share", "Outdoor-Unit Share"),
                ("p-pm-mode", "Mode (metrics)"),
                ("p-pm-state", "State (metrics)"),
                ("p-pm-duration", "Window"),
                ("p-pm-energy-total", "Energy (total)"),
                ("p-pm-hvac-energy", "Energy (HVAC)"),
                ("p-pm-led-energy", "Energy (LED)"),
            ]:
                self._kv(nid, label, "no data")

        if idu and idu.hvac_inputs:
            hi = idu.hvac_inputs
            self._kv(
                "p-hi-ext-ambient",
                "Ext. Ambient",
                _tc(hi.external_ambient_temperature_c, use_f),
            )
            self._kv(
                "p-hi-setpoint",
                "Setpoint (ctrl)",
                _tc(hi.temperature_setpoint_c, use_f),
            )
            self._kv(
                "p-hi-mode",
                "Mode (ctrl)",
                hi.hvac_mode.name,
                _MODE_STYLE.get(hi.hvac_mode, ""),
            )
            hi_state_fmt = _fmt_state(hi.hvac_state)
            self._kv(
                "p-hi-state",
                "State (ctrl)",
                hi_state_fmt.plain,
                str(hi_state_fmt.style),
            )
            self._kv(
                "p-hi-source",
                "Ambient Source",
                _AMBIENT_SOURCE_LABELS.get(
                    hi.ambient_temperature_source, hi.ambient_temperature_source.name.title()
                ),
            )
            ctrl_type = hi.hvac_controller_type
            ctrl_type_short = (
                ctrl_type.name.replace("HVAC_CONTROLLER_TYPE_", "").replace("_", " ").title()
            )
            self._kv("p-hi-ctrl-type", "Controller Type", ctrl_type_short)
        else:
            for nid, label in [
                ("p-hi-ext-ambient", "Ext. Ambient"),
                ("p-hi-setpoint", "Setpoint (ctrl)"),
                ("p-hi-mode", "Mode (ctrl)"),
                ("p-hi-state", "State (ctrl)"),
                ("p-hi-source", "Ambient Source"),
                ("p-hi-ctrl-type", "Controller Type"),
            ]:
                self._kv(nid, label, "no data")

        if idu and idu.conditions:
            co = idu.conditions

            def _cs(val: int) -> tuple[str, str]:
                return _COND_STATE_LABELS.get(val, str(val)), (
                    _COND_ACTIVE_STYLE if val == 2 else ""
                )

            for nid, label, val in [
                ("p-cond-defrost", "Defrost Cycle", co.defrost_cycle),
                ("p-cond-oilreturn", "Oil Return", co.oil_return),
                ("p-cond-coilpreheat", "Coil Preheat", co.coil_preheat),
                ("p-cond-safetyheat", "Safety Heating", co.safety_heating),
                ("p-cond-anticold", "Anti-Cold Wind", co.anti_cold_wind),
                (
                    "p-cond-modeswitch",
                    "Mode Switch Delay",
                    co.hvac_mode_switching_delay,
                ),
                ("p-cond-modeconflict", "Mode Conflict", co.mode_conflict),
                (
                    "p-cond-modeconflictavoid",
                    "Mode Conflict Avoid",
                    co.mode_conflict_avoidance,
                ),
                (
                    "p-cond-abnormal-odu-air",
                    "Abnormal ODU Air",
                    co.abnormal_outdoor_air_temperature,
                ),
                (
                    "p-cond-odu-comm",
                    "ODU Comm Error",
                    co.outdoor_unit_communication_error,
                ),
                (
                    "p-cond-modbus",
                    "Modbus Comm Error",
                    co.modbus_communication_error,
                ),
            ]:
                text, style = _cs(val)
                self._kv(nid, label, text, style)
        else:
            for nid, label in [
                ("p-cond-defrost", "Defrost Cycle"),
                ("p-cond-oilreturn", "Oil Return"),
                ("p-cond-coilpreheat", "Coil Preheat"),
                ("p-cond-safetyheat", "Safety Heating"),
                ("p-cond-anticold", "Anti-Cold Wind"),
                ("p-cond-modeswitch", "Mode Switch Delay"),
                ("p-cond-modeconflict", "Mode Conflict"),
                ("p-cond-modeconflictavoid", "Mode Conflict Avoid"),
                ("p-cond-abnormal-odu-air", "Abnormal ODU Air"),
                ("p-cond-odu-comm", "ODU Comm Error"),
                ("p-cond-modbus", "Modbus Comm Error"),
            ]:
                self._kv(nid, label, "no data")

        if odu:
            hs = HVACState(odu.hvac_state)
            odu_state_str = hs.name if odu.hvac_state else "—"
            odu_state_style = _STATE_STYLE.get(hs, "dim") if odu.hvac_state else "dim"
            self._kv("p-odu-state", "ODU State", odu_state_str, odu_state_style)
            self._kv("p-odu-model", "Model", _sku_or_none(odu.model_sku) or "--")
            self._kv("p-odu-serial", "Serial", odu.serial_number or "--")
            self._kv("p-odu-fw", "Firmware", odu.firmware_version or "--")
            if odu.performance_data:
                odu_pd = odu.performance_data
                self._kv(
                    "p-odu-freq",
                    "Compressor Freq",
                    f"{odu_pd.compressor_frequency_hz:.1f} Hz",
                )
                self._kv(
                    "p-odu-coil",
                    "ODU Coil Temp",
                    _tc(odu_pd.coil_temperature_c, use_f),
                )
                self._kv(
                    "p-odu-exhaust",
                    "Exhaust Temp",
                    _tc(odu_pd.exhaust_temperature_c, use_f),
                )
                self._kv(
                    "p-odu-hi",
                    "High Pressure",
                    f"{odu_pd.high_pressure_kpa:.1f} kPa",
                )
                self._kv("p-odu-lo", "Low Pressure", f"{odu_pd.low_pressure_kpa:.1f} kPa")
                self._kv(
                    "p-odu-ambient",
                    "ODU Ambient",
                    _tc(odu_pd.ambient_temperature_c, use_f),
                )
            else:
                for nid in (
                    "p-odu-freq",
                    "p-odu-coil",
                    "p-odu-exhaust",
                    "p-odu-hi",
                    "p-odu-lo",
                    "p-odu-ambient",
                ):
                    self._kv_empty(nid, "no data")
        else:
            for nid in (
                "p-odu-state",
                "p-odu-freq",
                "p-odu-coil",
                "p-odu-exhaust",
                "p-odu-hi",
                "p-odu-lo",
                "p-odu-ambient",
                "p-odu-model",
                "p-odu-serial",
                "p-odu-fw",
            ):
                self._kv_empty(nid, "no outdoor unit")

        # IDU Commands (fallback control on connectivity loss)
        if idu and idu.commands:
            fc = idu.commands.fallback_control_command
            fc_str = fc.name.replace("FALLBACK_CONTROL_COMMAND_", "").replace("_", " ").title()
            self._kv("p-cmd-fallback", "Fallback Command", fc_str)
        else:
            self._kv("p-cmd-fallback", "Fallback Command", "--")

    def _populate_schedule(self) -> None:
        space_id = self._space.id
        snap = self.snapshot

        week = next((w for w in snap.schedule_weeks if w.space_id == space_id), None)
        self._sched_day_by_id = {d.id: d for d in snap.schedule_days}
        self._sched_cs_by_id = {cs.id: cs for cs in snap.comfort_settings}

        week_table: DataTable[str | Text] = self.query_one("#sched-week", DataTable)
        if not week_table.columns:
            week_table.add_columns("Day")

        week_table.clear()
        # Each weekday can map to multiple day programs (one event each).
        # _sched_row_day_ids[i] is a list of day_ids for weekday i+1.
        self._sched_row_day_ids: list[list[str]] = [[] for _ in _WEEKDAY_NAMES]

        if week:
            for wd in week.days:
                idx = wd.weekday - 1  # weekday 1=Mon … 7=Sun → 0-based
                if 0 <= idx < 7:
                    self._sched_row_day_ids[idx].append(wd.day_id)
            for day_name in _WEEKDAY_NAMES:
                week_table.add_row(day_name)
            # Show Monday's events by default
            self._populate_day_events(
                [
                    self._sched_day_by_id[did]
                    for did in self._sched_row_day_ids[0]
                    if did in self._sched_day_by_id
                ],
                self._sched_cs_by_id,
                label="Monday",
            )
        else:
            for day_name in _WEEKDAY_NAMES:
                week_table.add_row(day_name)
            self._populate_day_events([], {}, label="Monday")

        loc = snap.primary_location
        self._update_schedule_status(loc.schedule_paused if loc else False)

    @on(DataTable.RowHighlighted, "#sched-week")
    def _on_sched_week_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        idx = event.cursor_row
        row_ids = getattr(self, "_sched_row_day_ids", [[] for _ in _WEEKDAY_NAMES])
        cs_by_id = getattr(self, "_sched_cs_by_id", {})
        day_by_id = getattr(self, "_sched_day_by_id", {})
        day_ids = row_ids[idx] if idx < len(row_ids) else []
        days = [day_by_id[did] for did in day_ids if did in day_by_id]
        self._populate_day_events(days, cs_by_id, label=_WEEKDAY_NAMES[idx] if idx < 7 else "")

    def _populate_day_events(
        self, days: list[ScheduleDay], cs_by_id: dict[str, ComfortSetting], label: str = ""
    ) -> None:
        from quilt_hp.models.enums import HVACMode as _HM
        from quilt_hp.models.enums import LouverMode as _LM
        from quilt_hp.models.schedule import ScheduleDay

        if label:
            with contextlib.suppress(Exception):
                self.query_one("#sched-events-panel").border_title = label

        day_table: DataTable[str | Text] = self.query_one("#sched-day", DataTable)
        if not day_table.columns:
            day_table.add_columns("Time", "Mode", "Heat", "Cool", "Fan", "Preset")
        day_table.clear()

        # Gather events across day programs for this weekday, sorted by time.
        all_events = sorted(
            (ev for day in days if isinstance(day, ScheduleDay) for ev in day.events),
            key=lambda e: e.start_s,
        )

        if not all_events:
            day_table.add_row("--", "[dim]no events[/dim]", "--", "--", "--", "--")
            return

        for ev in all_events:
            ev_mode = _HM(ev.hvac_mode) if ev.hvac_mode else _HM.UNSPECIFIED
            preset_name = ""
            fan_str = "--"
            heat: float | None = ev.heating_setpoint_c
            cool: float | None = ev.cooling_setpoint_c

            if ev.comfort_setting_id:
                cs = cs_by_id.get(ev.comfort_setting_id)
                if cs:
                    preset_name = cs.name
                    ev_mode = cs.hvac_mode
                    heat = cs.heating_setpoint_c
                    cool = cs.cooling_setpoint_c
                    fan_str = cs.fan_speed.name.replace("FAN_SPEED_", "").title()
                    lm = cs.louver_mode
                    if lm not in (_LM.UNSPECIFIED, _LM.AUTO):
                        louver = (
                            f"FIXED {cs.louver_fixed_position:.0f}°"
                            if lm == _LM.FIXED and cs.louver_fixed_position
                            else lm.name
                        )
                        fan_str = f"{fan_str} / {louver}"

            mode_str = ev_mode.name.replace("HVAC_MODE_", "").replace("_", " ").title()
            # Only show the setpoints the mode uses; Standby and Fan events carry the system's
            # limits (e.g. 8 °C / 40 °C), which are not settings anyone chose.
            if ev_mode in (_HM.STANDBY, _HM.FAN, _HM.UNSPECIFIED) or ev_mode == _HM.DRY:
                heat = cool = None
            elif ev_mode == _HM.COOL:
                heat = None
            elif ev_mode == _HM.HEAT:
                cool = None
            day_table.add_row(
                ev.start_time or "--",
                mode_str,
                _tc(heat, self.use_f) if heat else "--",
                _tc(cool, self.use_f) if cool else "--",
                fan_str,
                preset_name or "--",
            )

    def _update_schedule_status(self, paused: bool) -> None:
        try:
            status = (
                "[yellow]PAUSED[/yellow]  [dim](resume from Home with P)[/dim]"
                if paused
                else "[green]▶ RUNNING[/green]"
            )
            self.query_one("#sched-status", Static).update(status)
        except NoMatches:
            pass

    # ── Energy ──────────────────────────────────────────────────

    @work
    async def _fetch_energy(self) -> None:
        """Fetch 30 days of hourly room energy data for summary totals."""
        try:
            self._set_energy_status("⟳ Loading energy data…")
            tz: datetime.tzinfo = datetime.UTC
            snap_tz = self.snapshot.timezone
            if snap_tz:
                try:
                    import zoneinfo

                    tz = zoneinfo.ZoneInfo(snap_tz)
                except Exception:
                    pass
            now = datetime.datetime.now(tz)
            start = (now - datetime.timedelta(days=30)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            metrics = await self._client.get_energy(start=start, end=now)
            space_metrics = next((m for m in metrics if m.space_id == self._space.id), None)
            self._populate_energy(space_metrics, tz)
            self._set_energy_status("")
        except Exception as exc:
            self._set_energy_status(f"[red]Energy fetch failed: {exc}[/red]")

    def _set_energy_status(self, msg: str) -> None:
        try:
            self.query_one("#energy-status", Static).update(msg)
        except NoMatches:
            pass

    def _populate_energy(self, metrics: object | None, tz: datetime.tzinfo) -> None:
        from quilt_hp.models.energy import SpaceEnergyMetrics

        table: DataTable[str | Text] = self.query_one("#e-table", DataTable)
        if not table.columns:
            table.add_columns("Date", "Hour", "kWh", "Status")

        if metrics is None or not isinstance(metrics, SpaceEnergyMetrics) or not metrics.buckets:
            self._kv("e-today", "Today", "no data")
            self._kv("e-yesterday", "Yesterday", "no data")
            self._kv("e-7day", "Last 7 days", "no data")
            self._kv("e-30day", "Last 30 days", "no data")
            try:
                self.query_one("#e-sparkline", Static).update("no energy data")
            except NoMatches:
                pass
            return

        now = datetime.datetime.now(tz)
        today = now.date()
        yesterday = today - datetime.timedelta(days=1)

        # Group buckets by local date.
        # Buckets are UTC-aware from the service; astimezone converts them.
        by_date: dict[
            datetime.date, list[tuple[datetime.datetime, float, MetricBucketStatus]]
        ] = {}
        for b in metrics.buckets:
            bt = b.start_time
            if bt.tzinfo is None:
                # Defensive: treat naive datetimes as UTC.
                bt = bt.replace(tzinfo=datetime.UTC)
            bt_local = bt.astimezone(tz)
            d = bt_local.date()
            by_date.setdefault(d, []).append((bt_local, b.energy_kwh, b.status))

        def _day_total(d: datetime.date) -> float:
            return sum(kwh for _, kwh, _ in by_date.get(d, []))

        today_kwh = _day_total(today)
        yest_kwh = _day_total(yesterday)
        week_kwh = sum(_day_total(today - datetime.timedelta(days=i)) for i in range(7))
        month_kwh = sum(_day_total(today - datetime.timedelta(days=i)) for i in range(30))

        self._kv("e-today", "Today", f"{today_kwh:.3f} kWh", "cyan")
        self._kv("e-yesterday", "Yesterday", f"{yest_kwh:.3f} kWh")
        self._kv("e-7day", "Last 7 days", f"{week_kwh:.3f} kWh")
        self._kv("e-30day", "Last 30 days", f"{month_kwh:.3f} kWh")

        # Sparkline — today so far, 24 fixed hourly slots (00–23 local time)
        cutoff = now - datetime.timedelta(hours=24)
        today_hours = by_date.get(today, [])
        spark: Text
        if today_hours:
            bars, axis = hourly_chart({bt.hour: kwh for bt, kwh, _ in today_hours})
            spark = Text.assemble(Text(bars, style="cyan"), "\n", Text(axis, style="dim"))
        else:
            spark = Text("no energy data for today", style="dim")

        try:
            self.query_one("#e-sparkline", Static).update(spark)
        except NoMatches:
            pass

        # Populate hourly table — last 24 hours only (most recent first)
        table.clear()
        status_labels = {0: "—", 1: "✓", 2: "~"}
        recent_buckets = [
            (bt, kwh, s) for buckets in by_date.values() for bt, kwh, s in buckets if bt >= cutoff
        ]
        for bt, kwh, status in sorted(recent_buckets, reverse=True):
            table.add_row(
                bt.strftime("%Y-%m-%d"),
                bt.strftime("%H:00"),
                f"{kwh:.4f}",
                status_labels.get(status, str(status)),
            )

    def _kv_empty(self, widget_id: str, placeholder: str) -> None:
        self._kv(widget_id, _FALLBACK_LABELS[widget_id], placeholder, "dim")

    def _kv(self, widget_id: str, key: str, value: str, val_style: str = "") -> None:
        try:
            w = self.query_one(f"#{widget_id}", _KVStatic)
            w.set_kv(key, value, val_style)
        except NoMatches:
            pass

    # ── Live update entry points ─────────────────────────────────

    def update_space(self, space: Space) -> None:
        self._space = space
        self._populate_status()

    def update_idu(self, idu: IndoorUnit) -> None:
        self._idu = idu
        self._odu = _odu_for_space(self.snapshot, self._space.id, idu)
        self._populate_status()
        self._populate_perf()

    def update_odu(self, odu: OutdoorUnit) -> None:
        self._odu = odu
        self._populate_status()
        self._populate_perf()

    def update_ctrl(self, ctrl: Controller) -> None:
        self._controller = ctrl
        self._populate_status()

    def update_qsm(self, qsm: QuiltSmartModule) -> None:
        self._qsm = qsm
        self._populate_status()

    # ── Actions ─────────────────────────────────────────────────

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_refresh_energy(self) -> None:
        self._fetch_energy()

    def action_toggle_units(self) -> None:
        app = self.app
        if isinstance(app, SnapshotHost):
            app.use_f = not app.use_f

    def refresh_units(self) -> None:
        """Re-render temperature-bearing panels after a °C/°F change."""
        self._populate_status()
        self._populate_perf()

    def action_cycle_mode(self) -> None:
        if not self._space or not self._space.controls:
            return
        # If the room is currently AWAY (STANDBY + comfort setting), the next
        # meaningful step is plain STANDBY (OFF), not skipping ahead to HEAT.
        if self._space.is_away:
            self._mutate_space(mode=HVACMode.STANDBY)
        else:
            nxt = _cycle_next(self._space.controls.hvac_mode, _MODE_CYCLE)
            self._mutate_space(mode=nxt)

    def action_heat_up(self) -> None:
        self._delta_setpoint("heat", +0.5)

    def action_heat_down(self) -> None:
        self._delta_setpoint("heat", -0.5)

    def action_cool_up(self) -> None:
        self._delta_setpoint("cool", +0.5)

    def action_cool_down(self) -> None:
        self._delta_setpoint("cool", -0.5)

    def _delta_setpoint(self, which: str, delta: float) -> None:
        if not self._space or not self._space.controls:
            return
        c = self._space.controls
        if which == "heat":
            val = clamp_setpoint_c((c.heating_setpoint_c or DEFAULT_HEAT_SETPOINT_C) + delta)
            self._mutate_space(heat_setpoint_c=val)
        else:
            val = clamp_setpoint_c((c.cooling_setpoint_c or DEFAULT_COOL_SETPOINT_C) + delta)
            self._mutate_space(cool_setpoint_c=val)

    def action_cycle_fan(self) -> None:
        if not self._idu:
            return
        nxt = _cycle_next(self._idu.controls.fan_speed, _FAN_CYCLE)
        self._mutate_idu(fan_speed=nxt)

    def action_cycle_louver(self) -> None:
        if not self._idu:
            return
        nxt = _cycle_next(self._idu.controls.louver_mode, _LOUVER_CYCLE)
        self._mutate_idu(louver_mode=nxt)

    def action_toggle_led(self) -> None:
        if not self._idu:
            return
        if self._idu.controls.light_on:
            self._mutate_idu(led_brightness=0.0)
            return
        # Restore the stored brightness (preserved server-side when off);
        # fall back to the configured default, then full brightness.
        restore = self._idu.controls.led_brightness
        if restore <= 0.0:
            restore = self._idu.settings.light_brightness_default_percent or 1.0
        self._mutate_idu(led_brightness=restore)

    _AWAY_TIMEOUT_STEP_S: float = 300.0  # 5 minutes
    _RETURN_TIMEOUT_STEP_S: float = 60.0  # 1 minute
    _TIMEOUT_MIN_S: float = 60.0  # 1 minute minimum

    def action_away_timeout_dec(self) -> None:
        if not self._space:
            return
        cur = self._space.settings.unoccupied_timeout_s
        self._mutate_settings(
            unoccupied_timeout_s=max(self._TIMEOUT_MIN_S, cur - self._AWAY_TIMEOUT_STEP_S)
        )

    def action_away_timeout_inc(self) -> None:
        if not self._space:
            return
        cur = self._space.settings.unoccupied_timeout_s
        self._mutate_settings(unoccupied_timeout_s=cur + self._AWAY_TIMEOUT_STEP_S)

    def action_return_timeout_dec(self) -> None:
        if not self._space:
            return
        cur = self._space.settings.occupied_timeout_s
        self._mutate_settings(
            occupied_timeout_s=max(self._TIMEOUT_MIN_S, cur - self._RETURN_TIMEOUT_STEP_S)
        )

    def action_return_timeout_inc(self) -> None:
        if not self._space:
            return
        cur = self._space.settings.occupied_timeout_s
        self._mutate_settings(occupied_timeout_s=cur + self._RETURN_TIMEOUT_STEP_S)

    @work
    async def _mutate_space(
        self,
        mode: HVACMode | None = None,
        heat_setpoint_c: float | None = None,
        cool_setpoint_c: float | None = None,
    ) -> None:
        try:
            updated = await self._client.set_space(
                self._space,
                mode=mode,
                heat_setpoint_c=heat_setpoint_c,
                cool_setpoint_c=cool_setpoint_c,
            )
            self._space = updated
            self._populate_status()
        except Exception as exc:
            self.notify(f"Error: {exc}", severity="error")

    @work
    async def _mutate_settings(
        self,
        unoccupied_timeout_s: float | None = None,
        occupied_timeout_s: float | None = None,
    ) -> None:
        """Update space auto-away / auto-return timeouts."""
        try:
            updated = await self._client.set_space_settings(
                self._space,
                unoccupied_timeout_s=unoccupied_timeout_s,
                occupied_timeout_s=occupied_timeout_s,
            )
            self._space = updated
            self._populate_status()
        except Exception as exc:
            self.notify(f"Error: {exc}", severity="error")

    @work
    async def _mutate_idu(
        self,
        fan_speed: FanSpeed | None = None,
        louver_mode: LouverMode | None = None,
        led_brightness: float | None = None,
    ) -> None:
        if not self._idu:
            return
        try:
            updated = await self._client.set_indoor_unit(
                self._idu,
                fan_speed=fan_speed,
                louver_mode=louver_mode,
                led_brightness=led_brightness,
            )
            self._idu = updated
            self._populate_status()
        except Exception as exc:
            self.notify(f"Error: {exc}", severity="error")

    _FENCE_STEP_M = 0.5

    def action_fence_fwd_inc(self) -> None:
        if self._idu:
            cur = self._idu.settings.presence_fence_forward_m
            self._mutate_idu_settings(fence_forward_m=round(cur + self._FENCE_STEP_M, 2))

    def action_fence_fwd_dec(self) -> None:
        if self._idu:
            cur = self._idu.settings.presence_fence_forward_m
            self._mutate_idu_settings(fence_forward_m=max(0.0, round(cur - self._FENCE_STEP_M, 2)))

    def action_fence_lr_inc(self) -> None:
        if self._idu:
            st = self._idu.settings
            step = self._FENCE_STEP_M
            self._mutate_idu_settings(
                fence_left_m=round(st.presence_fence_left_m + step, 2),
                fence_right_m=round(st.presence_fence_right_m + step, 2),
            )

    def action_fence_lr_dec(self) -> None:
        if self._idu:
            st = self._idu.settings
            step = self._FENCE_STEP_M
            self._mutate_idu_settings(
                fence_left_m=max(0.0, round(st.presence_fence_left_m - step, 2)),
                fence_right_m=max(0.0, round(st.presence_fence_right_m - step, 2)),
            )

    def action_radar_height_inc(self) -> None:
        if self._idu:
            cur = self._idu.settings.radar_sensor_distance_from_floor_m
            self._mutate_idu_settings(radar_height_m=round(cur + self._FENCE_STEP_M, 2))

    def action_radar_height_dec(self) -> None:
        if self._idu:
            cur = self._idu.settings.radar_sensor_distance_from_floor_m
            self._mutate_idu_settings(radar_height_m=max(0.0, round(cur - self._FENCE_STEP_M, 2)))

    @work
    async def _mutate_idu_settings(
        self,
        fence_left_m: float | None = None,
        fence_right_m: float | None = None,
        fence_forward_m: float | None = None,
        radar_height_m: float | None = None,
    ) -> None:
        if not self._idu:
            return
        try:
            updated = await self._client.set_indoor_unit_settings(
                self._idu,
                fence_left_m=fence_left_m,
                fence_right_m=fence_right_m,
                fence_forward_m=fence_forward_m,
                radar_height_m=radar_height_m,
            )
            self._idu = updated
            self._populate_status()
        except Exception as exc:
            self.notify(f"Fence update error: {exc}", severity="error")
