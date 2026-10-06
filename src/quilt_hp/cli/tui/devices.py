"""Devices screen: every device in the house, its health, and its details on demand."""

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from rich.text import Text
from textual import on, work
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from quilt_hp.cli.tui.base import SnapshotHost
from quilt_hp.cli.tui.dialogs import ConfirmScreen, TextDialog
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
    from quilt_hp.models.controller import Controller
    from quilt_hp.models.indoor_unit import IndoorUnit
    from quilt_hp.models.system import SystemSnapshot

logger = logging.getLogger(__name__)

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


def _self_test(idu: IndoorUnit) -> str:
    if not idu.is_under_test:
        return "not running"
    effective = idu.effective_test_mode
    mode = effective.name.replace("_", " ").lower()
    ts = idu.test_state
    # Coordination belongs to test_state; skip it when the current mode came from a newer
    # state.test_mode, so a stale coordination isn't paired with a different test.
    coordination = (
        ts.test_coordination.name.lower() if ts is not None and ts.test_mode == effective else ""
    )
    if coordination in ("", "unspecified", "none"):
        return f"running ({mode})"
    return f"running ({mode}, {coordination})"


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
        Binding("t", "self_test", "Self-test"),
        Binding("s", "dial_sensor", "Dial sensor"),
        Binding("n", "rename_dial", "Rename Dial"),
        Binding("r", "toggle_raw", "Raw telemetry"),
        Binding("u", "toggle_units", "°C/°F"),
    ]
    # Actions that only apply to one kind of device; dimmed in the footer otherwise.
    _ACTION_KINDS: ClassVar = {
        "self_test": DeviceKind.INDOOR_UNIT,
        "dial_sensor": DeviceKind.DIAL,
        "rename_dial": DeviceKind.DIAL,
    }

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
        pairs = _details(self.snapshot, row, self.use_f, raw=self._raw, hints=True)
        width = max((len(k) for k, _ in pairs), default=0) + 2
        lines = [Text.assemble((k.ljust(width), "dim"), v) for k, v in pairs]
        if not self._raw:
            lines.append(Text("\nr shows raw telemetry", style="dim italic"))
        self.query_one("#devices-detail", Static).update(Text("\n").join(lines))

    @on(DataTable.RowHighlighted, "#devices-table")
    def _on_highlight(self, _event: DataTable.RowHighlighted) -> None:
        self._render_detail()
        self.refresh_bindings()

    def _selected_row(self) -> DeviceView | None:
        key = self._selected_key()
        return next((r for r in self._rows if f"{r.kind.name}:{r.device_id}" == key), None)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        kind = self._ACTION_KINDS.get(action)
        if kind is None:
            return True
        row = self._selected_row()
        return True if row is not None and row.kind == kind else None

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

    def _selected_idu(self) -> IndoorUnit | None:
        row = self._selected_row()
        if row is None or row.kind != DeviceKind.INDOOR_UNIT:
            return None
        return next((u for u in self.snapshot.indoor_units if u.id == row.device_id), None)

    def _selected_dial(self) -> Controller | None:
        row = self._selected_row()
        if row is None or row.kind != DeviceKind.DIAL:
            return None
        return next((c for c in self.snapshot.controllers if c.id == row.device_id), None)

    def _room_name(self, space_id: str) -> str:
        return next((s.name for s in self.snapshot.rooms if s.id == space_id), "this room")

    def action_self_test(self) -> None:
        idu = self._selected_idu()
        if idu is None:
            self.notify("Select an indoor unit to run its self-test.")
            return
        room = self._room_name(idu.space_id)
        if idu.is_under_test:
            question = f"Cancel the self-test on the {room} indoor unit?"
            detail = f"{room} goes back to its own settings."
            label = "Cancel test"
        else:
            question = f"Run a self-test on the {room} indoor unit?"
            detail = (
                f"It takes up to 30 minutes. During this time, {room} won't be available "
                "for heating or cooling. Quilt (and your certified partner, if you have one) "
                "will see the results."
            )
            odu = self.snapshot.odu_for_idu(idu)
            sharing = sorted(
                self._room_name(u.space_id)
                for u in self.snapshot.indoor_units
                if u.id != idu.id and odu is not None and self.snapshot.odu_for_idu(u) is odu
            )
            if sharing:
                detail += (
                    f" {', '.join(sharing)} share{'s' if len(sharing) == 1 else ''} its "
                    "outdoor unit and may have to wait."
                )
            label = "Run test"

        def done(confirmed: bool | None) -> None:
            if confirmed:
                self._run_self_test(idu, cancel=idu.is_under_test)

        self.app.push_screen(ConfirmScreen(question, detail, label), done)

    @work(group="devices-control")
    async def _run_self_test(self, idu: IndoorUnit, *, cancel: bool) -> None:
        room = self._room_name(idu.space_id)
        try:
            if cancel:
                await self._client.cancel_self_test(idu)
            else:
                await self._client.start_self_test(idu)
        except Exception as exc:
            self.notify(
                f"Couldn't {'cancel' if cancel else 'start'} the test: {exc}", severity="error"
            )
            return
        self.notify(
            f"Cancelling the {room} self-test" if cancel else f"Self-test starting in {room}",
            timeout=4,
        )
        await self._reload()

    def action_dial_sensor(self) -> None:
        dial = self._selected_dial()
        if dial is None:
            self.notify("Select a Dial to change its temperature sensor.")
            return
        room = self._room_name(dial.space_id)
        use_dial = not dial.uses_dial_temperature
        if use_dial:
            question = f"Control {room} to its Dial's temperature?"
            detail = "The room is heated and cooled to what the Dial measures where it's mounted."
            label = "Use the Dial"
        else:
            question = f"Control {room} to the indoor unit's sensor?"
            detail = (
                "The room is heated and cooled to the indoor unit's built-in sensor, which "
                "sits high on the wall and can read a little warm."
            )
            label = "Use the indoor unit"

        def done(confirmed: bool | None) -> None:
            if confirmed:
                self._update_dial(dial, uses_dial_temperature=use_dial)

        self.app.push_screen(ConfirmScreen(question, detail, label), done)

    def action_rename_dial(self) -> None:
        dial = self._selected_dial()
        if dial is None:
            self.notify("Select a Dial to rename it.")
            return

        def done(name: str | None) -> None:
            if name and name != dial.name:
                self._update_dial(dial, name=name)

        self.app.push_screen(
            TextDialog(f"Rename the {self._room_name(dial.space_id)} Dial", dial.name), done
        )

    @work(group="devices-control")
    async def _update_dial(
        self,
        dial: Controller,
        *,
        name: str | None = None,
        uses_dial_temperature: bool | None = None,
    ) -> None:
        try:
            await self._client.set_controller(
                dial, name=name, uses_dial_temperature=uses_dial_temperature
            )
        except Exception as exc:
            self.notify(f"Couldn't update the Dial: {exc}", severity="error")
            return
        if name is not None:
            self.notify(f"Dial renamed to {name}", timeout=3)
        else:
            self.notify(
                "The room follows its Dial's temperature"
                if uses_dial_temperature
                else "The room follows the indoor unit's sensor",
                timeout=3,
            )
        await self._reload()

    async def _reload(self) -> None:
        """Adopt a fresh snapshot so the change shows without waiting for the stream."""
        try:
            snap = await self._client.get_snapshot()
        except Exception as exc:
            logger.warning("Devices refresh failed: %s", exc)
            return
        self._snapshot = snap
        app = self.app
        if isinstance(app, SnapshotHost):
            app.update_snapshot(snap)
        self.render_all()

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
    snap: SystemSnapshot, row: DeviceView, use_f: bool, *, raw: bool, hints: bool = False
) -> list[tuple[str, str]]:
    """Key/value lines for one device; ``raw`` adds diagnostic telemetry, ``hints`` the
    Devices screen's keys for the settings shown."""

    def hint(text: str) -> str:
        return f" · {text}" if hints else ""

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
            (
                "Self-test",
                _self_test(idu) + (hint("t cancels") if idu.is_under_test else hint("t runs it")),
            ),
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
            (
                "Temperature sensor",
                _dial_sensor(ctrl.uses_dial_temperature) + hint("s switches, n renames"),
            ),
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
