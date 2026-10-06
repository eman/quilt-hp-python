"""Pure view helpers for the TUI: ages, local times and the "needs attention" list.

Nothing here imports Textual, so it is unit-tested directly.
"""

from __future__ import annotations

import zoneinfo
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from enum import IntEnum
from typing import TYPE_CHECKING

from quilt_hp.models.enums import (
    ControllerViewState,
    FanSpeed,
    HVACMode,
    HVACState,
    IndoorUnitTestMode,
    LocalCommsHealthStatus,
    LouverMode,
    OccupancyMode,
    OccupancyState,
)
from quilt_hp.models.software_update import SoftwareUpdateInfo, SoftwareUpdateState

if TYPE_CHECKING:
    from quilt_hp.models.indoor_unit import IndoorUnit
    from quilt_hp.models.space import Space
    from quilt_hp.models.system import SystemSnapshot


class Severity(IntEnum):
    """Attention severity; lower sorts first."""

    CRITICAL = 0
    WARNING = 1
    INFO = 2


@dataclass(frozen=True, slots=True)
class AttentionItem:
    """One thing the user should know about, e.g. an offline device."""

    severity: Severity
    title: str
    detail: str = ""
    space_id: str | None = None


def age_text(then: datetime | None, now: datetime) -> str:
    """How long ago ``then`` was, coarsely: ``45 s``, ``12 min``, ``8 h``, ``3 d``."""
    if then is None:
        return "unknown"
    seconds = max(0.0, (now - then).total_seconds())
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 90 * 60:
        return f"{seconds / 60:.0f} min"
    if seconds < 48 * 3600:
        return f"{seconds / 3600:.0f} h"
    return f"{seconds / 86400:.0f} d"


def system_tz(snap: SystemSnapshot) -> tzinfo:
    """The system's own time zone (falls back to the machine's local zone)."""
    if snap.timezone:
        try:
            return zoneinfo.ZoneInfo(snap.timezone)
        except zoneinfo.ZoneInfoNotFoundError, ValueError:
            pass
    local = datetime.now().astimezone().tzinfo
    return local if local is not None else UTC


def local_hhmm(when: datetime, tz: tzinfo, now: datetime) -> str:
    """``09:52`` for today, ``Oct 4 09:52`` for an earlier day, in the system's zone."""
    local = when.astimezone(tz)
    if local.date() == now.astimezone(tz).date():
        return local.strftime("%H:%M")
    return f"{local.strftime('%b')} {local.day} {local.strftime('%H:%M')}"


def attention_items(snap: SystemSnapshot, now: datetime | None = None) -> list[AttentionItem]:
    """Everything that needs the user's attention, most severe first."""
    now = now or datetime.now(tz=UTC)
    tz = system_tz(snap)
    room_names = {s.id: s.name for s in snap.spaces}
    items: list[AttentionItem] = []

    for idu in snap.indoor_units:
        room = room_names.get(idu.space_id, "A room")
        if not idu.is_online:
            seen = idu.state.updated_at
            items.append(
                AttentionItem(
                    Severity.CRITICAL,
                    f"{room} indoor unit offline",
                    _last_seen(seen, tz, now),
                    idu.space_id,
                )
            )
        if idu.is_under_test:
            mode = idu.effective_test_mode
            label = (
                "test" if mode == IndoorUnitTestMode.UNSPECIFIED else _words(mode.name) + " test"
            )
            items.append(
                AttentionItem(
                    Severity.WARNING,
                    f"{room} indoor unit running a {label}",
                    "it ignores the room's controls until the test ends",
                    idu.space_id,
                )
            )

    for ctrl in snap.controllers:
        if not ctrl.is_online:
            room = room_names.get(ctrl.space_id, "A room")
            items.append(
                AttentionItem(
                    Severity.WARNING,
                    f"{room} Dial offline",
                    _last_seen(ctrl.state_updated_at, tz, now),
                    ctrl.space_id,
                )
            )

    for diag in snap.diagnostics().indoor_units:
        for condition in diag.active_faults:
            room = diag.space_name or "A room"
            items.append(
                AttentionItem(Severity.WARNING, f"{room}: {_words(condition)}", "", diag.space_id)
            )

    updating = [
        u
        for u in snap.software_update_infos
        if u.state not in (SoftwareUpdateState.UNSPECIFIED, SoftwareUpdateState.IDLE)
    ]
    if updating:
        noun = "update" if len(updating) == 1 else "updates"
        items.append(AttentionItem(Severity.INFO, f"{len(updating)} firmware {noun} in progress"))

    loc = snap.primary_location
    if loc is not None and loc.schedule_paused:
        items.append(AttentionItem(Severity.INFO, "Schedules paused for the whole house"))

    return sorted(items, key=lambda item: item.severity)


def _last_seen(seen: datetime | None, tz: tzinfo, now: datetime) -> str:
    if seen is None:
        return "never reported"
    return f"last reading {age_text(seen, now)} ago ({local_hhmm(seen, tz, now)})"


def _words(name: str) -> str:
    return name.replace("_", " ").lower()


# ── Rooms ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class RoomView:
    """One room as the Home screen shows it. Values are ``None`` when not reported."""

    space_id: str
    name: str
    temp_c: float | None
    humidity_percent: float | None
    dew_point_c: float | None
    mode: HVACMode
    away: bool
    heat_c: float | None  # only the setpoints the mode uses
    cool_c: float | None
    hvac_state: HVACState
    occupancy: OccupancyState | None
    fan: FanSpeed | None
    fan_rpm: float | None
    louver: LouverMode | None
    power_w: float | None
    cop: float | None
    odu_share: float | None
    dial_online: bool | None  # None: the room has no Dial
    dial_display: ControllerViewState | None
    dial_brightness: float | None
    dial_presence: bool | None
    dial_age: str | None  # set when the Dial is offline
    alerts: tuple[AttentionItem, ...] = ()


def room_views(
    snap: SystemSnapshot, now: datetime | None = None, alerts: list[AttentionItem] | None = None
) -> list[RoomView]:
    """A view of every room, in the snapshot's order."""
    now = now or datetime.now(tz=UTC)
    alerts = attention_items(snap, now) if alerts is None else alerts
    views = []
    for space in snap.rooms:
        idu = next((u for u in snap.indoor_units if u.space_id == space.id), None)
        ctrl = next((c for c in snap.controllers if c.space_id == space.id), None)
        c, s = space.controls, space.state
        mode = c.hvac_mode if c else HVACMode.UNSPECIFIED
        heat = c.heating_setpoint_c if c and mode in (HVACMode.HEAT, HVACMode.AUTO) else None
        cool = c.cooling_setpoint_c if c and mode in (HVACMode.COOL, HVACMode.AUTO) else None
        pm = idu.performance_metrics if idu else None
        dial_live = ctrl.is_online if ctrl else None
        humidity = ctrl.humidity_percent if ctrl and dial_live else None
        if humidity is None and idu and idu.is_online:
            humidity = idu.state.ambient_humidity_percent or None
        views.append(
            RoomView(
                space_id=space.id,
                name=space.name,
                temp_c=s.ambient_temperature_c if s else None,
                humidity_percent=humidity,
                dew_point_c=idu.dew_point_c if idu and idu.is_online else None,
                mode=mode,
                away=space.is_away,
                heat_c=heat,
                cool_c=cool,
                hvac_state=s.hvac_state if s else HVACState.UNSPECIFIED,
                occupancy=_occupancy(space, idu),
                fan=idu.controls.fan_speed if idu else None,
                fan_rpm=(idu.state.fan_speed_rpm or None) if idu and idu.is_online else None,
                louver=idu.controls.louver_mode if idu else None,
                power_w=pm.hvac_power_w if pm and idu and idu.is_online else None,
                cop=(pm.coefficient_of_performance or None) if pm else None,
                odu_share=(pm.odu_usage_fraction or None) if pm else None,
                dial_online=dial_live,
                dial_display=ctrl.view_state if ctrl and dial_live else None,
                dial_brightness=ctrl.screen_brightness if ctrl and dial_live else None,
                dial_presence=ctrl.presence_detected if ctrl and dial_live else None,
                dial_age=age_text(ctrl.state_updated_at, now) if ctrl and not dial_live else None,
                alerts=tuple(a for a in alerts if a.space_id == space.id),
            )
        )
    return views


def _occupancy(space: Space, idu: IndoorUnit | None) -> OccupancyState | None:
    """Room occupancy, or None when auto-away is off or nothing reports it."""
    if space.settings.occupancy_mode != OccupancyMode.ENABLED:
        return None
    if space.occupancy_state is not None:
        return space.occupancy_state
    if idu is None or idu.effective_occupancy_state is None:
        return None
    try:
        return OccupancyState(idu.effective_occupancy_state)
    except ValueError:
        return None


# ── Devices ─────────────────────────────────────────────────────────────────


class DeviceKind(IntEnum):
    """Device types, in the order the Devices screen lists them within a room."""

    INDOOR_UNIT = 0
    DIAL = 1
    REMOTE_SENSOR = 2
    OUTDOOR_UNIT = 3


@dataclass(frozen=True, slots=True)
class DeviceView:
    """One row of the Devices screen."""

    kind: DeviceKind
    device_id: str
    room: str  # "" for outdoor units
    online: bool | None  # None: the device reports no status
    age: str | None  # how long since an offline device last reported
    link: str
    serial: str | None
    firmware: str | None
    update: str | None  # e.g. "downloading 40%"; None when idle


def device_views(snap: SystemSnapshot, now: datetime | None = None) -> list[DeviceView]:
    """Every device, grouped by room (rooms in snapshot order), outdoor units last."""
    now = now or datetime.now(tz=UTC)
    rooms = {s.id: s.name for s in snap.spaces}
    order = {s.id: i for i, s in enumerate(snap.rooms)}
    updates = {u.id: u for u in snap.software_update_infos}
    qsms = {q.id: q for q in snap.quilt_smart_modules}
    rows: list[DeviceView] = []

    for idu in snap.indoor_units:
        qsm = qsms.get(idu.qsm_id or "")
        signal = qsm.hosted_wifi.signal_dbm if qsm and qsm.hosted_wifi else None
        mesh = qsm.local_comms_health if qsm else None
        rows.append(
            DeviceView(
                DeviceKind.INDOOR_UNIT,
                idu.id,
                rooms.get(idu.space_id, ""),
                idu.is_online,
                None if idu.is_online else age_text(idu.state.updated_at, now),
                _link(signal, mesh) if idu.is_online else "",
                idu.serial_number,
                _known(idu.firmware_version),
                _update(updates, idu.firmware_update_info_id),
            )
        )
    for ctrl in snap.controllers:
        rows.append(
            DeviceView(
                DeviceKind.DIAL,
                ctrl.id,
                rooms.get(ctrl.space_id, ""),
                ctrl.is_online,
                None if ctrl.is_online else age_text(ctrl.state_updated_at, now),
                # An offline Dial's last Wi-Fi and mesh report is not its current state.
                _link(ctrl.wifi_signal_dbm or None, ctrl.local_comms_health)
                if ctrl.is_online
                else "",
                ctrl.serial_number,
                _known(ctrl.firmware_version),
                _update(updates, ctrl.software_update_info_id, ctrl.firmware_update_info_id),
            )
        )
    idu_rooms = {u.id: rooms.get(u.space_id, "") for u in snap.indoor_units}
    for rs in snap.remote_sensors:
        battery = f"battery {rs.battery_level_percent:.0f}%" if rs.battery_level_percent else ""
        rows.append(
            DeviceView(
                DeviceKind.REMOTE_SENSOR,
                rs.id,
                idu_rooms.get(rs.indoor_unit_id, ""),
                None,
                None,
                " · ".join(p for p in (_link(rs.signal_level_dbm, None), battery) if p),
                None,
                None,
                None,
            )
        )
    room_rank = {name: order[sid] for sid, name in rooms.items() if sid in order}
    rows.sort(key=lambda r: (room_rank.get(r.room, len(order)), r.kind))
    for odu in snap.outdoor_units:
        rows.append(
            DeviceView(
                DeviceKind.OUTDOOR_UNIT,
                odu.id,
                "",
                None,
                None,
                "",
                odu.serial_number,
                _known(odu.firmware_version),
                _update(updates, None, odu.firmware_update_info_id),
            )
        )
    return rows


def _known(value: str | None) -> str | None:
    """Drop the server's placeholders for an unknown value."""
    return None if not value or value.strip().upper() in ("N/A", "NA", "UNKNOWN") else value


def _link(signal_dbm: int | None, mesh: LocalCommsHealthStatus | None) -> str:
    parts = []
    if signal_dbm:
        parts.append(f"{signal_dbm} dBm")
    if mesh is not None and mesh != LocalCommsHealthStatus.UNSPECIFIED:
        parts.append(mesh.name.replace("_", " ").lower())
    return " · ".join(parts)


def _update(updates: dict[str, SoftwareUpdateInfo], *ids: str | None) -> str | None:
    for update_id in ids:
        info = updates.get(update_id or "")
        if info is None or info.state in (
            SoftwareUpdateState.UNSPECIFIED,
            SoftwareUpdateState.IDLE,
        ):
            continue
        text = info.state.name.lower()
        if info.total_progress > 0:
            text += f" {info.current_progress / info.total_progress:.0%}"
        if info.target_version:
            text += f" → {info.target_version}"
        return text
    return None
