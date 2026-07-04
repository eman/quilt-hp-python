"""Controller (Quilt Dial thermostat) model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from quilt_hp.models._helpers import (
    local_comms_last_session_change,
    lookup_hardware,
    parse_wifi_state,
    present_submsg,
    timestamp_or_none,
)
from quilt_hp.models.enums import (
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
    pcb_temperature_a_c: float | None  # temperature_f3 — PCB temp A (~30–50°C)
    pcb_temperature_b_c: float | None  # temperature_f4 — PCB temp B (hotter component, ~45–52°C)
    calibrated_ambient_c: float | None  # temperature_f5 — calibrated ext ambient sent to IDU
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
    state_updated_at: datetime | None = None  # ControllerState.updated_ts (field 1)
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

    @property
    def ambient_temperature_c(self) -> float | None:
        """Calibrated ambient temperature used for system control.

        Use this for display and logic.  See also ``raw_thermistor_c`` for the
        uncorrected on-chip reading (biased high by self-heating).  ``None``
        when no state reading is available (e.g. unmerged stream diff).
        """
        return self.calibrated_ambient_c

    @property
    def wifi_band(self) -> str | None:
        """'5 GHz' or '2.4 GHz' based on frequency, or None if unknown."""
        if self.wifi_freq_mhz is None:
            return None
        return "5 GHz" if self.wifi_freq_mhz > 5000 else "2.4 GHz"

    @property
    def is_online(self) -> bool:
        """True if the controller is known to be online.

        Uses ``ControllerState.updated_ts`` if available, with a 5-minute
        threshold.

        The server does not currently send ``ControllerState.updated_ts``
        (confirmed from wire captures — field 1 always absent).  When no
        timestamp is available we assume the controller is online; we only
        report offline when we have positive evidence of a stale timestamp.
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
            raw_thermistor_c=st.ambient_temperature_c if st is not None else None,
            pcb_temperature_a_c=st.temperature_f3 if st is not None else None,
            pcb_temperature_b_c=st.temperature_f4 if st is not None else None,
            calibrated_ambient_c=st.temperature_f5 if st is not None else None,
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
                getattr(getattr(p, "local_comms_status", None), "status", 0)
            ),
            local_comms_visible_devices=getattr(
                getattr(p, "local_comms_status", None), "visible_devices_count", None
            ),
            local_comms_expected_devices=getattr(
                getattr(p, "local_comms_status", None), "expected_devices_count", None
            ),
            local_comms_reason=LocalCommsHealthReason(
                getattr(getattr(p, "local_comms_status", None), "reason", 0)
            ),
            local_comms_last_session_change=local_comms_last_session_change(
                getattr(p, "local_comms_status", None)
            ),
        )
