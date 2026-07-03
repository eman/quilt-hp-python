"""Controller (Quilt Dial thermostat) model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from quilt_hp.const import PROTO_TIMESTAMP_UNSET_SECONDS
from quilt_hp.models._helpers import lookup_hardware, parse_wifi_state
from quilt_hp.models.enums import LocalCommsHealthStatus, RemoteSensorControlMode
from quilt_hp.models.qsm import WifiInfo

_ONLINE_THRESHOLD_S = 5 * 60  # 5-minute online detection window


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
    local_comms_link_state: int | None = None
    """Raw ``LocalCommsStatus.link_state`` value (wire-confirmed 2026-07-03,
    meaning not yet decoded — observed constant at 9 across all healthy
    devices in captures so far). Exposed raw pending enum discovery.
    """
    local_comms_connection_state: int | None = None
    """Raw ``LocalCommsStatus.connection_state`` value (wire-confirmed
    2026-07-03, observed constant at 1 across all healthy devices).
    """
    local_comms_version: int | None = None
    """Raw ``LocalCommsStatus.version`` value (wire-confirmed 2026-07-03,
    observed constant at 9 across all healthy devices — likely the local
    mesh protocol/schema version).
    """

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

        wifi_ssid, wifi_ip, wifi_signal_dbm, wifi_bssid, wifi_freq_mhz = parse_wifi_state(w)

        serial: str | None = None
        model_sku: str | None = None
        fw_ver: str | None = None
        if hw_map:
            hw = lookup_hardware(hw_map, p.relationships.hardware_id)
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
            wifi_ssid=wifi_ssid,
            wifi_ip=wifi_ip,
            wifi_signal_dbm=wifi_signal_dbm,
            wifi_freq_mhz=wifi_freq_mhz,
            wifi_bssid=wifi_bssid,
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
            local_comms_health=LocalCommsHealthStatus(
                getattr(getattr(p, "local_comms_status", None), "health", 0)
            ),
            local_comms_link_state=getattr(
                getattr(p, "local_comms_status", None), "link_state", None
            ),
            local_comms_connection_state=getattr(
                getattr(p, "local_comms_status", None), "connection_state", None
            ),
            local_comms_version=getattr(
                getattr(p, "local_comms_status", None), "version", None
            ),
        )
