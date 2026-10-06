"""System screen: outdoor units, Dials, remote sensors and updates."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual import work
from textual.binding import Binding
from textual.containers import (
    Horizontal,
    Vertical,
)
from textual.screen import Screen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Static,
)

from quilt_hp.cli.tui.base import SnapshotHost
from quilt_hp.cli.tui.format import _STATE_STYLE, _fmt_detected, _fmt_display, _sku_or_none, _tc
from quilt_hp.cli.tui.shared import _set_schedule_paused
from quilt_hp.client import QuiltClient
from quilt_hp.models.enums import (
    HVACState,
    RemoteSensorControlMode,
)
from quilt_hp.models.outdoor_unit import OutdoorUnit
from quilt_hp.models.sensor import RemoteSensor

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from quilt_hp.models.system import SystemSnapshot


logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# SystemScreen
# ──────────────────────────────────────────────────────────────────


class SystemScreen(Screen[None]):
    """System-wide overview: ODU, controllers, remote sensors."""

    BINDINGS: ClassVar = [
        Binding("escape,b", "back", "Back"),
        Binding("u", "toggle_units", "°C/°F"),
        Binding("p", "toggle_schedule", "Pause Sched"),
    ]

    def __init__(
        self,
        snapshot: SystemSnapshot,
        client: QuiltClient,
        *,
        use_f: bool = False,
    ) -> None:
        super().__init__()
        self._snapshot = snapshot  # fallback when not attached to a QuiltApp
        self._client = client
        self._use_f = use_f

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

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="system-container"):
            # System header
            with Vertical(classes="odu-panel") as v:
                v.border_title = "System"
                yield Static(id="sys-header")

            # ODU row — one panel per outdoor unit
            with Horizontal(id="odu-row"):
                if self.snapshot.outdoor_units:
                    for i in range(len(self.snapshot.outdoor_units)):
                        with Vertical(classes="odu-panel") as v:
                            v.border_title = (
                                f"Outdoor Unit {i + 1}"
                                if len(self.snapshot.outdoor_units) > 1
                                else "Outdoor Unit"
                            )
                            yield Static(id=f"sys-odu-{i}")
                else:
                    yield Static("[dim]No outdoor unit data[/dim]", id="sys-odu-0")

            # Controllers
            with Vertical(classes="odu-panel") as v:
                v.border_title = "Controllers (Dials)"
                yield DataTable(id="sys-ctrls")

            # Remote sensors
            with Vertical(classes="odu-panel") as v:
                v.border_title = "Remote Sensors"
                yield DataTable(id="sys-sensors")

            # Firmware / software update status
            with Vertical(classes="odu-panel") as v:
                v.border_title = "Firmware / Software Updates"
                yield DataTable(id="sys-firmware")
        yield Footer()

    def on_mount(self) -> None:
        self._populate()

    def _populate(self) -> None:
        snap = self.snapshot
        use_f = self.use_f

        # Header
        loc = snap.primary_location
        tz = snap.timezone or "?"
        sched = (
            "[yellow]⏸ PAUSED[/yellow]"
            if (loc and loc.schedule_paused)
            else "[green]▶ RUNNING[/green]"
        )
        loc_name = loc.name if loc and loc.name else ""
        header_parts = []
        if loc_name:
            header_parts.append(f"[bold]{loc_name}[/bold]")
        header_parts.append(f"[bold]Timezone:[/bold] {tz}")
        header_parts.append(f"[bold]Schedule:[/bold] {sched}")
        if snap.version_at is not None:
            changed = snap.version_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")
            header_parts.append(f"[bold]Config changed:[/bold] {changed}")
        self.query_one("#sys-header", Static).update("   ".join(header_parts))

        # ODU panels — one per unit
        for i, odu in enumerate(snap.outdoor_units):
            odu_lines: list[str] = []
            hs = HVACState(odu.hvac_state)
            state = hs.name if odu.hvac_state else "—"
            state_style = _STATE_STYLE.get(hs, "dim") if odu.hvac_state else "dim"
            odu_lines.append(f"[{state_style}]State: {state}[/{state_style}]")
            model = _sku_or_none(odu.model_sku)
            if model:
                odu_lines.append(f"Model:    {model}")
            if odu.serial_number:
                odu_lines.append(f"Serial:   {odu.serial_number}")
            if odu.firmware_version:
                odu_lines.append(f"Firmware: {odu.firmware_version}")
            if odu.performance_data:
                pd = odu.performance_data
                odu_lines.append(f"Compressor:  {pd.compressor_frequency_hz:.1f} Hz")
                odu_lines.append(f"ODU Coil:    {_tc(pd.coil_temperature_c, use_f)}")
                odu_lines.append(f"Exhaust:     {_tc(pd.exhaust_temperature_c, use_f)}")
                odu_lines.append(f"Hi Pressure: {pd.high_pressure_kpa:.1f} kPa")
                odu_lines.append(f"Lo Pressure: {pd.low_pressure_kpa:.1f} kPa")
                odu_lines.append(f"ODU Ambient: {_tc(pd.ambient_temperature_c, use_f)}")
            self.query_one(f"#sys-odu-{i}", Static).update("\n".join(odu_lines))

        # Controllers table
        ctrl_table: DataTable[str | Text] = self.query_one("#sys-ctrls", DataTable)
        if not ctrl_table.columns:
            ctrl_table.add_columns(
                "Name",
                "Model",
                "Serial",
                "Ambient",
                "Raw Thermistor",
                "Encoder",
                "SoC",
                "Display",
                "Radar",
                "Light",
                "WiFi SSID",
                "IP",
                "Signal",
            )
        ctrl_table.clear()
        for ctrl in snap.controllers:
            live = ctrl.is_online  # an offline Dial's last readings are not current
            name = Text(ctrl.name or ctrl.id[:8])
            if not live:
                name = Text.assemble(("⚠ ", "bold red"), name)
            ctrl_table.add_row(
                name,
                _sku_or_none(ctrl.model_sku) or "--",
                ctrl.serial_number or "--",
                _tc(ctrl.calibrated_ambient_c, use_f),
                _tc(ctrl.raw_thermistor_c, use_f),
                _tc(ctrl.pcb_temperature_a_c, use_f),
                _tc(ctrl.pcb_temperature_b_c, use_f),
                Text(*_fmt_display(ctrl)),
                _fmt_detected(ctrl.presence_detected if live else None)[0],
                f"{ctrl.ambient_light_lux:.0f} lx"
                if live and ctrl.ambient_light_lux is not None
                else "--",
                ctrl.wifi_ssid or "--",
                ctrl.wifi_ip or "--",
                f"{ctrl.wifi_signal_dbm} dBm" if ctrl.wifi_signal_dbm else "--",
            )

        # Remote sensors table
        sensor_table: DataTable[str | Text] = self.query_one("#sys-sensors", DataTable)
        if not sensor_table.columns:
            sensor_table.add_columns(
                "Sensor",
                "Room",
                "Mode",
                "Temp",
                "Humidity",
                "Battery",
                "Signal",
            )
        sensor_table.clear()
        # Build IDU→room name map for display
        idu_to_room: dict[str, str] = {}
        for room in snap.rooms:
            for idu in snap.indoor_units:
                if idu.space_id == room.id:
                    idu_to_room[idu.id] = room.name or room.id[:8]
        for rs in sorted(
            snap.remote_sensors,
            key=lambda r: idu_to_room.get(r.indoor_unit_id, ""),
        ):
            mode_str = "EN" if rs.control_mode == RemoteSensorControlMode.ENABLED else "DIS"
            mode_style = "green" if rs.control_mode == RemoteSensorControlMode.ENABLED else "dim"
            sensor_table.add_row(
                rs.mac or rs.id[:8],
                idu_to_room.get(rs.indoor_unit_id, rs.indoor_unit_id[:8]),
                Text(mode_str, style=mode_style),
                _tc(rs.ambient_temperature_c, use_f),
                f"{rs.humidity_percent:.0f}%" if rs.humidity_percent is not None else "--",
                f"{rs.battery_level_percent:.0f}%"
                if rs.battery_level_percent is not None
                else "--",
                f"{rs.signal_level_dbm} dBm" if rs.signal_level_dbm else "--",
            )
        for crs in snap.controller_remote_sensors:
            crs_ctrl = next((c for c in snap.controllers if c.id == crs.controller_id), None)
            label = (
                f"Dial {crs_ctrl.serial_number or crs_ctrl.name or crs.controller_id[:8]}"
                if crs_ctrl
                else crs.id[:8]
            )
            crs_space_id = next(
                (c.space_id for c in snap.controllers if c.id == crs.controller_id),
                None,
            )
            room_name = (
                next(
                    (s.name for s in snap.rooms if s.id == crs_space_id),
                    crs_space_id[:8] if crs_space_id else "--",
                )
                if crs_space_id
                else "--"
            )
            mode_str = "EN" if crs.control_mode == RemoteSensorControlMode.ENABLED else "DIS"
            mode_style = "green" if crs.control_mode == RemoteSensorControlMode.ENABLED else "dim"
            sensor_table.add_row(
                label,
                room_name,
                Text(mode_str, style=mode_style),
                _tc(crs.ambient_temperature_c, use_f),
                f"{crs.humidity_percent:.0f}%" if crs.humidity_percent is not None else "--",
                f"{crs.battery_level_percent:.0f}%"
                if crs.battery_level_percent is not None
                else "--",
                f"{crs.signal_level_dbm} dBm" if crs.signal_level_dbm else "--",
            )

        # Firmware / software update table
        fw_table: DataTable[str | Text] = self.query_one("#sys-firmware", DataTable)
        if not fw_table.columns:
            fw_table.add_columns(
                "Device",
                "Type",
                "Current Version",
                "Target Version",
                "Progress",
                "State",
            )
        fw_table.clear()
        sui_by_id = {s.id: s for s in snap.software_update_infos}

        def _fw_row(device_name: str, sw_id: str | None, fw_id: str | None) -> None:
            for label, uid in [("SW", sw_id), ("FW", fw_id)]:
                if not uid:
                    continue
                sui = sui_by_id.get(uid)
                if not sui:
                    continue
                ver = sui.current_version or "--"
                target = sui.target_version or "--"
                prog = (
                    f"{sui.current_progress:.0f}/{sui.total_progress:.0f}"
                    if sui.total_progress
                    else "--"
                )
                state = str(sui.state) if sui.state else "--"
                fw_table.add_row(device_name, label, ver, target, prog, state)

        for idu in snap.indoor_units:
            idu_room = next((s.name for s in snap.rooms if s.id == idu.space_id), idu.id[:8])
            _fw_row(f"IDU {idu_room}", None, idu.firmware_update_info_id)
        for odu in snap.outdoor_units:
            model = _sku_or_none(odu.model_sku)
            _fw_row(
                f"ODU {model or odu.serial_number or odu.id[:8]}",
                None,
                odu.firmware_update_info_id,
            )
        for ctrl in snap.controllers:
            model = _sku_or_none(ctrl.model_sku)
            _fw_row(
                f"Dial {model or ctrl.serial_number or ctrl.name or ctrl.id[:8]}",
                ctrl.software_update_info_id,
                ctrl.firmware_update_info_id,
            )
        for qsm in snap.quilt_smart_modules:
            _fw_row(
                f"QSM {qsm.id[:8]}",
                qsm.software_update_info_id,
                qsm.firmware_update_info_id,
            )

    def action_back(self) -> None:
        self.app.pop_screen()

    def update_odu(self, _odu: OutdoorUnit) -> None:
        """Called by QuiltApp stream dispatcher when an ODU update arrives.

        The updated ODU is already merged into the snapshot, which
        ``_populate`` reads directly.
        """
        self._populate()

    def update_remote_sensor(self, rs: RemoteSensor) -> None:
        """Called by QuiltApp stream dispatcher on RemoteSensor updates."""
        self._populate()

    def action_toggle_units(self) -> None:
        app = self.app
        if isinstance(app, SnapshotHost):
            app.use_f = not app.use_f

    def refresh_units(self) -> None:
        """Re-render the system panels after a °C/°F change."""
        self._populate()

    def action_toggle_schedule(self) -> None:
        loc = self.snapshot.primary_location
        if loc is None:
            self.notify("No location found", severity="error")
            return
        self._do_toggle_schedule(not loc.schedule_paused)

    @work
    async def _do_toggle_schedule(self, paused: bool) -> None:
        try:
            await _set_schedule_paused(self._client, self.snapshot, paused)
            self._populate()
            self.notify("Schedules " + ("paused" if paused else "resumed"), timeout=2)
        except Exception as exc:
            self.notify(f"Error: {exc}", severity="error")
