"""Devices screen: every device in the house, its health, and its details on demand."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from rich.text import Text
from textual import on
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from quilt_hp.cli.tui.base import SnapshotHost
from quilt_hp.cli.tui.format import _tc
from quilt_hp.cli.tui.views import (
    DeviceKind,
    DeviceView,
    device_views,
    local_hhmm,
    system_tz,
)

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from quilt_hp.client import QuiltClient
    from quilt_hp.models.system import SystemSnapshot

_KIND_LABELS = {
    DeviceKind.INDOOR_UNIT: "Indoor unit",
    DeviceKind.DIAL: "Dial",
    DeviceKind.REMOTE_SENSOR: "Remote sensor",
    DeviceKind.OUTDOOR_UNIT: "Outdoor unit",
}
_COLUMNS = ("Device", "Room", "Status", "Link", "Firmware", "Update")


def _dial_sensor(uses_dial: bool | None) -> str:
    if uses_dial is None:
        return "–"
    return "controls the room" if uses_dial else "off (indoor unit's sensor used)"


class DevicesScreen(Screen[None]):
    """One row per device, grouped by room; the selected device's details below."""

    DEFAULT_CSS = """
    DevicesScreen #devices-table { height: auto; max-height: 60%; margin: 0 1; }
    DevicesScreen #devices-detail-wrap {
        height: 1fr; margin: 1 1 0 1; padding: 0 1;
        border: round $primary-darken-2; border-title-color: $text;
    }
    """
    BINDINGS: ClassVar = [
        Binding("escape,b", "back", "Back"),
        Binding("r", "toggle_raw", "Raw telemetry"),
        Binding("u", "toggle_units", "°C/°F"),
    ]

    def __init__(self, snapshot: SystemSnapshot, client: QuiltClient) -> None:
        super().__init__()
        self._snapshot = snapshot
        self._client = client
        self._rows: list[DeviceView] = []
        self._raw = False

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

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield DataTable(id="devices-table", cursor_type="row")
        with VerticalScroll(id="devices-detail-wrap"):
            yield Static(id="devices-detail")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Devices"
        table: DataTable[Any] = self.query_one("#devices-table", DataTable)
        for column in _COLUMNS:
            table.add_column(column, key=column)
        self.render_all()
        table.focus()

    # ── Rendering ───────────────────────────────────────────────

    def render_all(self) -> None:
        table: DataTable[Any] = self.query_one("#devices-table", DataTable)
        selected = self._selected_key()
        self._rows = device_views(self.snapshot, datetime.now(tz=UTC))
        table.clear()
        for row in self._rows:
            table.add_row(*_cells(row), key=f"{row.kind.name}:{row.device_id}")
        keys = [f"{r.kind.name}:{r.device_id}" for r in self._rows]
        if keys:
            table.move_cursor(row=keys.index(selected) if selected in keys else 0)
        self._render_detail()

    def _selected_key(self) -> str | None:
        table: DataTable[Any] = self.query_one("#devices-table", DataTable)
        if not table.row_count:
            return None
        with contextlib.suppress(Exception):
            return str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        return None

    def _render_detail(self) -> None:
        wrap = self.query_one("#devices-detail-wrap")
        key = self._selected_key()
        row = next((r for r in self._rows if f"{r.kind.name}:{r.device_id}" == key), None)
        if row is None:
            wrap.border_title = "Details"
            self.query_one("#devices-detail", Static).update(Text("No devices.", style="dim"))
            return
        title = _KIND_LABELS[row.kind] + (f" · {row.room}" if row.room else "")
        wrap.border_title = title + (" · raw telemetry" if self._raw else "")
        pairs = _details(self.snapshot, row, self.use_f, raw=self._raw)
        width = max((len(k) for k, _ in pairs), default=0) + 2
        lines = [Text.assemble((k.ljust(width), "dim"), v) for k, v in pairs]
        if not self._raw:
            lines.append(Text("\nr shows raw telemetry", style="dim italic"))
        self.query_one("#devices-detail", Static).update(Text("\n").join(lines))

    @on(DataTable.RowHighlighted, "#devices-table")
    def _on_highlight(self, _event: DataTable.RowHighlighted) -> None:
        self._render_detail()

    # ── Live updates and actions ────────────────────────────────

    def snapshot_changed(self, _kind: str, _entity: object) -> None:
        self.render_all()

    def on_screen_resume(self) -> None:
        # Catch up on updates that arrived while a dialog (e.g. help) was on top.
        self.render_all()

    def refresh_units(self) -> None:
        # Also called after stream recovery adopts a new snapshot: rebuild rows and details
        # together so the detail pane never reads a device that has gone.
        self.render_all()

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_toggle_raw(self) -> None:
        self._raw = not self._raw
        self._render_detail()

    def action_toggle_units(self) -> None:
        app = self.app
        if isinstance(app, SnapshotHost):
            app.use_f = not app.use_f


def _cells(row: DeviceView) -> tuple[Text, ...]:
    if row.online is None:
        status = Text("–", style="dim")  # the detail pane says why
    elif row.online:
        status = Text("● online", style="green")
    else:
        status = Text(f"⚠ offline {row.age}", style="bold red")
    return (
        Text(_KIND_LABELS[row.kind]),
        Text(row.room or "–", style="" if row.room else "dim"),
        status,
        Text(row.link or "–", style="" if row.link else "dim"),
        Text(row.firmware or "–", style="" if row.firmware else "dim"),
        Text(row.update or "–", style="yellow" if row.update else "dim"),
    )


def _details(
    snap: SystemSnapshot, row: DeviceView, use_f: bool, *, raw: bool
) -> list[tuple[str, str]]:
    """Key/value lines for one device; ``raw`` adds diagnostic telemetry."""
    tz = system_tz(snap)
    now = datetime.now(tz=UTC)

    def when(value: datetime | None) -> str:
        return local_hhmm(value, tz, now) if value else "–"

    def temp(value: float | None) -> str:
        return _tc(value, use_f)

    pairs: list[tuple[str, str]] = []
    if row.kind == DeviceKind.INDOOR_UNIT:
        idu = next((u for u in snap.indoor_units if u.id == row.device_id), None)
        if idu is None:
            return _gone()
        qsm = snap.qsm_for_idu(idu)
        odu = snap.odu_for_idu(idu)  # tolerates path-prefixed and bare ids
        stale = "" if idu.is_online else " (last known)"
        pairs += [
            ("Serial", idu.unit_serial_number or idu.serial_number or "–"),
            ("Smart module", idu.smart_module_serial_number or "–"),
            ("Firmware", row.firmware or "–"),
            ("Made", _date(idu.manufactured_at)),
            ("Last report", when(idu.state.updated_at)),
            ("Outdoor unit", odu.serial_number or odu.id[:8] if odu else "–"),
        ]
        if qsm is not None:
            if qsm.hosted_wifi is not None:
                w = qsm.hosted_wifi
                pairs.append(("Wi-Fi", _wifi(w.ssid, w.ip, w.signal_dbm, w.snr_db) + stale))
            pairs.append(
                (
                    "Local mesh",
                    _mesh(
                        qsm.local_comms_health.name,
                        qsm.local_comms_visible_devices,
                        qsm.local_comms_expected_devices,
                    )
                    + stale,
                )
            )
        if raw:
            p = idu.presence
            pairs += [
                (
                    "Radar channels",
                    f"{p.sensor0_presence.name.lower()} / {p.sensor1_presence.name.lower()}"
                    if p
                    else "–",
                ),
                (
                    "Coil",
                    temp(idu.performance_data.coil_temperature_c) if idu.performance_data else "–",
                ),
            ]
            if idu.hvac_inputs is not None:
                hi = idu.hvac_inputs
                pairs += [
                    (
                        "Controller input",
                        f"{temp(hi.external_ambient_temperature_c)} → {temp(hi.temperature_setpoint_c)}",
                    ),
                    ("Controller type", str(getattr(hi, "hvac_controller_type", "–"))),
                ]
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
            if qsm is not None and qsm.ap_wifi is not None:
                pairs.append(
                    (
                        "Wi-Fi (setup AP)",
                        _wifi(qsm.ap_wifi.ssid, qsm.ap_wifi.ip, qsm.ap_wifi.signal_dbm),
                    )
                )
    elif row.kind == DeviceKind.DIAL:
        ctrl = next((c for c in snap.controllers if c.id == row.device_id), None)
        if ctrl is None:
            return _gone()
        live = ctrl.is_online
        pairs += [
            ("Serial", ctrl.serial_number or "–"),
            ("Firmware", row.firmware or "–"),
            ("Made", _date(ctrl.manufactured_at)),
            ("Last report", when(ctrl.state_updated_at) + ("" if live else f"  ({row.age} ago)")),
            ("Room temperature", temp(ctrl.calibrated_ambient_c)),
            (
                "Wi-Fi",
                _wifi(
                    ctrl.wifi_ssid,
                    ctrl.wifi_ip,
                    ctrl.wifi_signal_dbm,
                    ctrl.hosted_wifi.snr_db if ctrl.hosted_wifi else None,
                )
                + (" (last known)" if not live else ""),
            ),
            (
                "Local mesh",
                _mesh(
                    ctrl.local_comms_health.name,
                    ctrl.local_comms_visible_devices,
                    ctrl.local_comms_expected_devices,
                )
                + (" (last known)" if not live else ""),
            ),
            ("Temperature sensor", _dial_sensor(ctrl.uses_dial_temperature)),
        ]
        if raw:
            pairs += [
                ("Thermistor (raw)", temp(ctrl.raw_thermistor_c)),
                (
                    "Encoder / SoC",
                    f"{temp(ctrl.pcb_temperature_a_c)} / {temp(ctrl.pcb_temperature_b_c)}",
                ),
                (
                    "Main / power board",
                    f"{temp(ctrl.main_board_temperature_c)} / {temp(ctrl.power_board_temperature_c)}",
                ),
                (
                    "Humidity",
                    f"{ctrl.humidity_percent:.0f}%" if ctrl.humidity_percent is not None else "–",
                ),
                (
                    "Display",
                    f"{ctrl.view_state.name.lower()} {ctrl.screen_brightness:.0%}"
                    if ctrl.screen_brightness is not None
                    else ctrl.view_state.name.lower(),
                ),
                (
                    "Radar target / phase",
                    f"{_yes(ctrl.radar_target_detected)} / {_yes(ctrl.radar_phase_detected)}",
                ),
                (
                    "Ambient light",
                    f"{ctrl.ambient_light_lux:.0f} lx"
                    if ctrl.ambient_light_lux is not None
                    else "–",
                ),
                ("Power", f"{ctrl.power_w:.2f} W" if ctrl.power_w is not None else "–"),
                ("Orientation", ctrl.orientation.name.lower()),
                (
                    "Accelerometer",
                    " / ".join(str(a) for a in ctrl.accelerometer_raw)
                    if ctrl.accelerometer_raw
                    else "–",
                ),
                ("Wi-Fi BSSID / MHz", f"{ctrl.wifi_bssid or '–'} / {ctrl.wifi_freq_mhz or '–'}"),
            ]
            if not live:
                pairs.append(("", "These are the last values the Dial reported."))
    elif row.kind == DeviceKind.REMOTE_SENSOR:
        rs = next((r for r in snap.remote_sensors if r.id == row.device_id), None)
        if rs is None:
            return _gone()
        pairs += [
            ("Temperature", temp(rs.ambient_temperature_c)),
            (
                "Humidity",
                f"{rs.humidity_percent:.0f}%" if rs.humidity_percent is not None else "–",
            ),
            (
                "Battery",
                f"{rs.battery_level_percent:.0f}%"
                if rs.battery_level_percent is not None
                else "–",
            ),
            ("Signal", f"{rs.signal_level_dbm} dBm" if rs.signal_level_dbm else "–"),
            ("Mode", rs.control_mode.name.replace("_", " ").lower()),
        ]
        if raw:
            pairs.append(("MAC", rs.mac or "–"))
    else:
        odu = next((o for o in snap.outdoor_units if o.id == row.device_id), None)
        if odu is None:
            return _gone()
        rooms = [
            next((s.name for s in snap.rooms if s.id == u.space_id), "?")
            for u in snap.indoor_units
            if snap.odu_for_idu(u) is odu
        ]
        pairs += [
            ("Serial", odu.serial_number or "–"),
            ("Firmware", row.firmware or "–"),
            ("Made", _date(odu.manufactured_at)),
            ("Serves", ", ".join(rooms) or "–")
            if odu.port_count is None
            else (
                "Serves",
                f"{', '.join(rooms) or '–'}  ({len(rooms)} of {odu.port_count} ports)",
            ),
            ("Status", "the cloud does not report outdoor-unit status or sensors"),
        ]
        if raw and odu.performance_data is not None:
            pd = odu.performance_data
            pairs += [
                ("Compressor", f"{pd.compressor_frequency_hz:.1f} Hz"),
                (
                    "Coil / exhaust",
                    f"{temp(pd.coil_temperature_c)} / {temp(pd.exhaust_temperature_c)}",
                ),
                (
                    "Pressure hi / lo",
                    f"{pd.high_pressure_kpa:.0f} / {pd.low_pressure_kpa:.0f} kPa",
                ),
            ]
    if row.update:
        pairs.append(("Update", row.update))
    return pairs


def _gone() -> list[tuple[str, str]]:
    return [("", "This device is no longer part of the system.")]


def _yes(value: bool | None) -> str:
    return "–" if value is None else ("yes" if value else "no")


def _wifi(ssid: str | None, ip: str | None, signal: int | None, snr: int | None = None) -> str:
    level = f"{signal} dBm" if signal else None
    if level and snr is not None:
        level += f" (SNR {snr} dB)"
    parts = [p for p in (ssid, ip, level) if p]
    return " · ".join(parts) or "–"


def _date(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d") if value else "–"


def _mesh(health: str, visible: int | None, expected: int | None) -> str:
    text = health.replace("_", " ").lower()
    if text == "unspecified":
        text = "–"
    if visible is not None and expected:
        text += f" ({visible} of {expected} peers)"
    return text
