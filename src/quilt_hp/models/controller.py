"""Controller (Quilt Dial thermostat) model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from quilt_hp.models.enums import RemoteSensorControlMode
from quilt_hp.models.qsm import WifiInfo

_ONLINE_THRESHOLD_S = 5 * 60  # 5 minutes, matching KMP IS_ONLINE_THRESHOLD_MINUTES


@dataclass(slots=True)
class Controller:
    """A Quilt controller (Dial thermostat)."""

    id: str
    system_id: str
    space_id: str
    name: str
    raw_thermistor_c: float      # ambient_temperature_c — raw Dial thermistor; biased ~4–8°C high due to self-heating
    pcb_temperature_a_c: float   # temperature_f3 — PCB temp A (~30–50°C)
    pcb_temperature_b_c: float   # temperature_f4 — PCB temp B (hotter component, ~45–52°C)
    calibrated_ambient_c: float  # temperature_f5 — calibrated ext amb sent to IDU (~16–20°C); use this for display
    wifi_ssid: str | None
    wifi_ip: str | None
    wifi_signal_dbm: int | None
    wifi_freq_mhz: int | None = None        # e.g. 5745 → 5 GHz; 2437 → 2.4 GHz
    wifi_last_seen: datetime | None = None  # WifiState.updated_ts — when the dial last checked in over WiFi
    ap_wifi: WifiInfo | None = None         # AP-mode interface (device provisioning)
    p2p_wifi: WifiInfo | None = None        # peer-to-peer / Wi-Fi Direct
    remote_sensor_mode: RemoteSensorControlMode = RemoteSensorControlMode.UNSPECIFIED
    software_update_info_id: str | None = None
    firmware_update_info_id: str | None = None
    serial_number: str | None = None        # ControllerHardware.attributes.serial_number (e.g. "QD1-1B001451S")
    model_sku: str | None = None            # ControllerHardware.attributes.model_sku
    firmware_version: str | None = None     # ControllerHardware.attributes.firmware_version
    state_updated_at: datetime | None = None  # ControllerState.updated_ts (field 1)

    @property
    def ambient_temperature_c(self) -> float:
        """The calibrated ambient temperature — what the system actually uses for control.

        Use this for display and logic.  See also ``raw_thermistor_c`` for the
        uncorrected on-chip reading (biased high by self-heating).
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
        threshold matching KMP ``IS_ONLINE_THRESHOLD_MINUTES = 5``.

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
        w = proto.hosted_wifi_state  # type: ignore[attr-defined]
        ts = proto.state.updated_ts  # type: ignore[attr-defined]
        updated_at: datetime | None = None
        if ts.seconds != 0:
            updated_at = datetime.fromtimestamp(ts.seconds, tz=UTC)

        wifi_last_seen: datetime | None = None
        if w.updated_ts.seconds != 0:  # type: ignore[attr-defined]
            wifi_last_seen = datetime.fromtimestamp(w.updated_ts.seconds, tz=UTC)  # type: ignore[attr-defined]

        def _wifi(wstate: object) -> WifiInfo | None:
            info = WifiInfo.from_proto(wstate)
            return info if info.connected else None

        serial: str | None = None
        model_sku: str | None = None
        fw_ver: str | None = None
        if hw_map:
            hw_id = proto.relationships.hardware_id  # type: ignore[attr-defined]
            hw = hw_map.get(hw_id)
            if hw is not None:
                a = hw.attributes  # type: ignore[attr-defined]
                serial = a.serial_number or None
                model_sku = a.model_sku or None
                fw_ver = a.firmware_version or None

        return cls(
            id=proto.header.object_id,  # type: ignore[attr-defined]
            system_id=proto.header.system_id,  # type: ignore[attr-defined]
            space_id=proto.relationships.space_id,  # type: ignore[attr-defined]
            name=proto.settings.name,  # type: ignore[attr-defined]
            raw_thermistor_c=proto.state.ambient_temperature_c,  # type: ignore[attr-defined]
            pcb_temperature_a_c=proto.state.temperature_f3,  # type: ignore[attr-defined]
            pcb_temperature_b_c=proto.state.temperature_f4,  # type: ignore[attr-defined]
            calibrated_ambient_c=proto.state.temperature_f5,  # type: ignore[attr-defined]
            wifi_ssid=w.ssid or None,
            wifi_ip=w.ipv4_address or None,
            wifi_signal_dbm=w.signal_level_dbm or None,
            wifi_freq_mhz=w.frequency_mhz or None,
            wifi_last_seen=wifi_last_seen,
            ap_wifi=_wifi(proto.ap_wifi_state),    # type: ignore[attr-defined]
            p2p_wifi=_wifi(proto.p2p_wifi_state),  # type: ignore[attr-defined]
            remote_sensor_mode=RemoteSensorControlMode(proto.controls.remote_sensor_control_mode),  # type: ignore[attr-defined]
            software_update_info_id=proto.relationships.software_update_info_id or None,  # type: ignore[attr-defined]
            firmware_update_info_id=proto.relationships.firmware_update_info_id or None,  # type: ignore[attr-defined]
            serial_number=serial,
            model_sku=model_sku,
            firmware_version=fw_ver,
            state_updated_at=updated_at,
        )
