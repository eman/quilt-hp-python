"""Controller (Quilt Dial thermostat) model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from quilt_hp.models._helpers import (
    enum_or,
    local_comms_last_session_change,
    lookup_hardware,
    parse_wifi_state,
    present_submsg,
    timestamp_or_none,
)
from quilt_hp.models.enums import (
    ControllerOrientation,
    ControllerViewState,
    LocalCommsHealthReason,
    LocalCommsHealthStatus,
    RemoteSensorControlMode,
)
from quilt_hp.models.qsm import WifiInfo

_ONLINE_THRESHOLD_S = 5 * 60  # 5-minute online detection window


@dataclass(slots=True)
class Controller:
    """A Quilt controller (Dial thermostat)."""

    id: str
    system_id: str
    space_id: str
    name: str
    # Temperatures are None when the ``state`` sub-message was absent from a
    # sparse stream diff; SystemSnapshot.apply_controller preserves them.
    raw_thermistor_c: float | None  # ambient_temperature_c from raw Dial thermistor
    pcb_temperature_a_c: float | None  # encoder_temperature_c — encoder board temp (~30–50°C)
    pcb_temperature_b_c: float | None  # soc_temperature_c — SoC temp (~45–52°C)
    calibrated_ambient_c: (
        float | None
    )  # calculated_ambient_temperature_c — calibrated ambient sent to IDU
    wifi_ssid: str | None
    wifi_ip: str | None
    wifi_signal_dbm: int | None
    wifi_freq_mhz: int | None = None  # e.g. 5745 → 5 GHz; 2437 → 2.4 GHz
    wifi_bssid: str | None = None  # AP MAC address the Dial is associated with
    wifi_last_seen: datetime | None = (
        None  # WifiState.updated_ts — when the dial last checked in over WiFi
    )
    ap_wifi: WifiInfo | None = None  # AP-mode interface (device provisioning)
    p2p_wifi: WifiInfo | None = None  # peer-to-peer / Wi-Fi Direct
    remote_sensor_mode: RemoteSensorControlMode = RemoteSensorControlMode.UNSPECIFIED
    software_update_info_id: str | None = None
    firmware_update_info_id: str | None = None
    serial_number: str | None = None  # ControllerHardware.attributes.serial_number
    model_sku: str | None = None  # ControllerHardware.attributes.model_sku
    firmware_version: str | None = None  # ControllerHardware.attributes.firmware_version
    state_updated_at: datetime | None = None  # ControllerState.updated_ts (field 15)
    local_comms_health: LocalCommsHealthStatus = LocalCommsHealthStatus.UNSPECIFIED
    """Local mesh health (proto field 9). Available on app 1.0.26+.

    Gate: ``mobile_local_control_health_enabled``.  UNSPECIFIED means the
    server has not yet reported a health value (pre-1.0.26 firmware or the
    gate is off).
    """
    local_comms_visible_devices: int | None = None
    """``LocalCommsStatus.visible_devices_count`` (proto field 3) — the number
    of mesh peers this node currently sees.  APK-confirmed (1.0.29).
    """
    local_comms_expected_devices: int | None = None
    """``LocalCommsStatus.expected_devices_count`` (proto field 4) — the number
    of mesh peers expected on this system.  APK-confirmed (1.0.29).
    """
    local_comms_reason: LocalCommsHealthReason = LocalCommsHealthReason.UNSPECIFIED
    """``LocalCommsStatus.reason`` (proto field 6) — diagnostic reason for the
    current ``local_comms_health`` status (e.g. ``PARTIAL_VISIBILITY`` when
    some but not all expected peers are visible).  APK-confirmed (1.0.29).
    """
    local_comms_last_session_change: datetime | None = None
    """``LocalCommsStatus.last_session_change_ts`` (proto field 5) — when the
    local mesh session last changed.
    """
    # Display, radar and light telemetry (ControllerState fields 6–22). All are None /
    # UNSPECIFIED when the ``state`` sub-message was absent (SystemSnapshot.apply_controller
    # preserves the previous values).
    view_state: ControllerViewState = ControllerViewState.UNSPECIFIED
    """What the display is showing: SLEEP, GLANCE, ACTIVE or INTERACTING."""
    screen_brightness: float | None = None
    """Display brightness, 0.0–1.0 (0.0 while asleep)."""
    radar_target_detected: bool | None = None
    """The Dial's own mmWave radar reports a target (``mmwave_target_detect``).

    This radar is separate from the indoor unit's (``IndoorUnit.presence``).
    """
    radar_phase_detected: bool | None = None
    """The Dial radar's phase channel (``mmwave_phase_detect``); not yet seen true live."""
    ambient_light_lux: float | None = None
    """Calibrated ambient light at the Dial, in lux (``als_illuminance_calib_lx``)."""
    orientation: ControllerOrientation = ControllerOrientation.UNSPECIFIED
    """Wall-mounted (VERTICAL) or lying flat (HORIZONTAL)."""
    humidity_percent: float | None = None
    """Relative humidity from the Dial's SHT4x sensor; None on Dials that don't report it."""
    power_w: float | None = None
    """The Dial's own power draw (``power_meter_w``), ~0.85–1.2 W observed."""
    main_board_temperature_c: float | None = None
    power_board_temperature_c: float | None = None
    accelerometer_raw: tuple[int, int, int] | None = None
    """Raw accelerometer X/Y/Z counts."""

    @property
    def ambient_temperature_c(self) -> float | None:
        """Calibrated ambient temperature used for system control.

        Use this for display and logic.  See also ``raw_thermistor_c`` for the
        uncorrected on-chip reading (biased high by self-heating).  ``None``
        when no state reading is available (e.g. unmerged stream diff).
        """
        return self.calibrated_ambient_c

    @property
    def display_on(self) -> bool | None:
        """True unless the display is asleep; None when the view state is unknown."""
        if self.view_state == ControllerViewState.UNSPECIFIED:
            return None
        return self.view_state != ControllerViewState.SLEEP

    @property
    def presence_detected(self) -> bool | None:
        """True if the Dial's radar sees someone (target or phase channel).

        None when no state reading is available. Independent of the indoor unit's
        radar (see ``IndoorUnit.presence_detected``).
        """
        if self.radar_target_detected is None:
            return None
        return bool(self.radar_target_detected or self.radar_phase_detected)

    @property
    def wifi_band(self) -> str | None:
        """'5 GHz' or '2.4 GHz' based on frequency, or None if unknown."""
        if self.wifi_freq_mhz is None:
            return None
        return "5 GHz" if self.wifi_freq_mhz > 5000 else "2.4 GHz"

    @property
    def is_online(self) -> bool:
        """True if the controller is known to be online.

        Uses ``ControllerState.updated_ts`` (proto field 15) with a 5-minute
        threshold. Online Dials report state about every 10 seconds; an offline
        Dial's timestamp stops advancing. Earlier releases read the timestamp from
        field 1, which the server never sends, so this always returned True.
        When no timestamp is available we assume the controller is online; we
        only report offline when we have positive evidence of a stale timestamp.
        """
        if self.state_updated_at is None:
            return True  # no timestamp → unknown → assume online (fail-open)
        age = (datetime.now(tz=UTC) - self.state_updated_at).total_seconds()
        return age < _ONLINE_THRESHOLD_S

    @classmethod
    def from_proto(cls, proto: object, hw_map: dict[str, object] | None = None) -> Controller:
        """Construct from a protobuf Controller message.

        ``hw_map`` maps hardware_id → ControllerHardware proto, built once from
        ``HomeDatastoreSystem.controller_hardware`` and passed in at snapshot
        load time.  Stream diffs won't have it; fields default to None.
        """
        p = cast("Any", proto)
        st = cast("Any", present_submsg(proto, "state"))
        updated_at = timestamp_or_none(getattr(st, "updated_ts", None)) if st is not None else None

        w = cast("Any", present_submsg(proto, "hosted_wifi_state"))
        wifi_last_seen = (
            timestamp_or_none(getattr(w, "updated_ts", None)) if w is not None else None
        )

        def _wifi(wstate: object | None) -> WifiInfo | None:
            if wstate is None:
                return None
            info = WifiInfo.from_proto(wstate)
            return info if info.connected else None

        if w is not None:
            wifi_ssid, wifi_ip, wifi_signal_dbm, wifi_bssid, wifi_freq_mhz = parse_wifi_state(w)
        else:
            wifi_ssid, wifi_ip, wifi_signal_dbm = None, None, None
            wifi_bssid, wifi_freq_mhz = None, None

        rel = cast("Any", present_submsg(proto, "relationships"))
        controls = cast("Any", present_submsg(proto, "controls"))
        settings = cast("Any", present_submsg(proto, "settings"))

        serial: str | None = None
        model_sku: str | None = None
        fw_ver: str | None = None
        if hw_map and rel is not None:
            hw = lookup_hardware(hw_map, rel.hardware_id)
            if hw is not None:
                a = cast("Any", hw).attributes
                serial = a.serial_number or None
                model_sku = a.model_sku or None
                fw_ver = a.firmware_version or None

        return cls(
            id=p.header.object_id,
            system_id=p.header.system_id,
            space_id=rel.space_id if rel is not None else "",
            name=settings.name if settings is not None else "",
            raw_thermistor_c=st.sht4x_temperature_c if st is not None else None,
            pcb_temperature_a_c=st.encoder_temperature_c if st is not None else None,
            pcb_temperature_b_c=st.soc_temperature_c if st is not None else None,
            calibrated_ambient_c=st.calculated_ambient_temperature_c if st is not None else None,
            wifi_ssid=wifi_ssid,
            wifi_ip=wifi_ip,
            wifi_signal_dbm=wifi_signal_dbm,
            wifi_freq_mhz=wifi_freq_mhz,
            wifi_bssid=wifi_bssid,
            wifi_last_seen=wifi_last_seen,
            ap_wifi=_wifi(present_submsg(proto, "ap_wifi_state")),
            p2p_wifi=_wifi(present_submsg(proto, "p2p_wifi_state")),
            remote_sensor_mode=(
                RemoteSensorControlMode(controls.remote_sensor_control_mode)
                if controls is not None
                else RemoteSensorControlMode.UNSPECIFIED
            ),
            software_update_info_id=(
                (rel.software_update_info_id or None) if rel is not None else None
            ),
            firmware_update_info_id=(
                (rel.firmware_update_info_id or None) if rel is not None else None
            ),
            serial_number=serial,
            model_sku=model_sku,
            firmware_version=fw_ver,
            state_updated_at=updated_at,
            local_comms_health=LocalCommsHealthStatus(
                getattr(getattr(p, "local_comms_health", None), "status", 0)
            ),
            local_comms_visible_devices=getattr(
                getattr(p, "local_comms_health", None), "visible_devices_count", None
            ),
            local_comms_expected_devices=getattr(
                getattr(p, "local_comms_health", None), "expected_devices_count", None
            ),
            local_comms_reason=LocalCommsHealthReason(
                getattr(getattr(p, "local_comms_health", None), "reason", 0)
            ),
            local_comms_last_session_change=local_comms_last_session_change(
                getattr(p, "local_comms_health", None)
            ),
            **_display_fields(st),
        )


def _display_fields(st: Any | None) -> dict[str, Any]:
    """Map ControllerState fields 6–22 to model fields (empty when state was absent)."""
    if st is None:
        return {}

    def g(name: str, default: Any = 0) -> Any:
        return getattr(st, name, default)

    return {
        "view_state": enum_or(
            ControllerViewState, g("view_state"), ControllerViewState.UNSPECIFIED
        ),
        "screen_brightness": g("screen_brightness", 0.0),
        "radar_target_detected": bool(g("mmwave_target_detect", False)),
        "radar_phase_detected": bool(g("mmwave_phase_detect", False)),
        "ambient_light_lux": g("als_illuminance_calib_lx", 0.0),
        "orientation": enum_or(
            ControllerOrientation, g("orientation"), ControllerOrientation.UNSPECIFIED
        ),
        # 0 % RH is not a real indoor reading: Dials without the sensor send 0.
        "humidity_percent": g("sht4x_humidity_percent", 0.0) or None,
        "power_w": g("power_meter_w", 0.0),
        "main_board_temperature_c": g("main_board_temperature_c", 0.0),
        "power_board_temperature_c": g("power_board_temperature_c", 0.0),
        "accelerometer_raw": (g("accel_x_raw"), g("accel_y_raw"), g("accel_z_raw")),
    }
