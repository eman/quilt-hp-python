"""Controller (Quilt Dial thermostat) model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from quilt_hp.const import PROTO_TIMESTAMP_UNSET_SECONDS
from quilt_hp.models.enums import RemoteSensorControlMode
from quilt_hp.models.qsm import WifiInfo

_ONLINE_THRESHOLD_S = 5 * 60  # 5 minutes, matching KMP IS_ONLINE_THRESHOLD_MINUTES


def _lookup_hw(hw_map: dict[str, object], hardware_id: str | None) -> object | None:
    if not hardware_id:
        return None
    raw = hardware_id.strip()
    if not raw:
        return None
    keys = (
        raw,
        raw.rsplit("/", 1)[-1],
        raw.rsplit(":", 1)[-1],
        raw.casefold(),
        raw.rsplit("/", 1)[-1].casefold(),
        raw.rsplit(":", 1)[-1].casefold(),
    )
    for key in keys:
        hw = hw_map.get(key)
        if hw is not None:
            return hw
    return None


@dataclass(slots=True)
class Controller:
    """A Quilt controller (Dial thermostat)."""

    id: str
    system_id: str
    space_id: str
    name: str
    raw_thermistor_c: float  # ambient_temperature_c from raw Dial thermistor
    pcb_temperature_a_c: float  # temperature_f3 — PCB temp A (~30–50°C)
    pcb_temperature_b_c: float  # temperature_f4 — PCB temp B (hotter component, ~45–52°C)
    calibrated_ambient_c: float  # temperature_f5 — calibrated ext ambient sent to IDU
    wifi_ssid: str | None
    wifi_ip: str | None
    wifi_signal_dbm: int | None
    wifi_freq_mhz: int | None = None  # e.g. 5745 → 5 GHz; 2437 → 2.4 GHz
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

    @property
    def ambient_temperature_c(self) -> float:
        """Calibrated ambient temperature used for system control.

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
        p = cast("Any", proto)
        w = p.hosted_wifi_state
        ts = p.state.updated_ts
        updated_at: datetime | None = None
        if ts.seconds != PROTO_TIMESTAMP_UNSET_SECONDS:
            updated_at = datetime.fromtimestamp(ts.seconds, tz=UTC)

        wifi_last_seen: datetime | None = None
        if w.updated_ts.seconds != PROTO_TIMESTAMP_UNSET_SECONDS:
            wifi_last_seen = datetime.fromtimestamp(w.updated_ts.seconds, tz=UTC)

        def _wifi(wstate: object) -> WifiInfo | None:
            info = WifiInfo.from_proto(wstate)
            return info if info.connected else None

        serial: str | None = None
        model_sku: str | None = None
        fw_ver: str | None = None
        if hw_map:
            hw = _lookup_hw(hw_map, p.relationships.hardware_id)
            if hw is not None:
                a = cast("Any", hw).attributes
                serial = a.serial_number or None
                model_sku = a.model_sku or None
                fw_ver = a.firmware_version or None

        return cls(
            id=p.header.object_id,
            system_id=p.header.system_id,
            space_id=p.relationships.space_id,
            name=p.settings.name,
            raw_thermistor_c=p.state.ambient_temperature_c,
            pcb_temperature_a_c=p.state.temperature_f3,
            pcb_temperature_b_c=p.state.temperature_f4,
            calibrated_ambient_c=p.state.temperature_f5,
            wifi_ssid=w.ssid or None,
            wifi_ip=w.ipv4_address or None,
            wifi_signal_dbm=w.signal_level_dbm or None,
            wifi_freq_mhz=w.frequency_mhz or None,
            wifi_last_seen=wifi_last_seen,
            ap_wifi=_wifi(p.ap_wifi_state),
            p2p_wifi=_wifi(p.p2p_wifi_state),
            remote_sensor_mode=RemoteSensorControlMode(p.controls.remote_sensor_control_mode),
            software_update_info_id=p.relationships.software_update_info_id or None,
            firmware_update_info_id=p.relationships.firmware_update_info_id or None,
            serial_number=serial,
            model_sku=model_sku,
            firmware_version=fw_ver,
            state_updated_at=updated_at,
        )
