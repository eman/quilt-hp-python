"""QuiltSmartModule (QSM) model — the WiFi compute module embedded in each IDU.

Each indoor unit contains one QSM that handles:
- Cloud/local NATS connectivity (three WiFi interfaces: hosted, AP, P2P)
- Presence detection (phase + target radar channels)
- Ambient light sensing (ALS: illuminance, IR, combined)
- Accelerometer (X/Y/Z — detects unit tilt/movement)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from quilt_hp.models._helpers import parse_wifi_state
from quilt_hp.models.enums import LocalCommsHealthStatus


@dataclass(slots=True)
class WifiInfo:
    """WiFi interface snapshot (one of three on a QSM)."""

    ssid: str | None
    ip: str | None
    signal_dbm: int | None
    bssid: str | None = None
    frequency_mhz: int | None = None

    @property
    def connected(self) -> bool:
        return bool(self.ssid)

    @property
    def band(self) -> str | None:
        """'5 GHz' or '2.4 GHz' based on frequency, or None if unknown."""
        if self.frequency_mhz is None:
            return None
        return "5 GHz" if self.frequency_mhz > 5000 else "2.4 GHz"

    @classmethod
    def from_proto(cls, proto: object) -> WifiInfo:
        ssid, ip, signal_dbm, bssid, frequency_mhz = parse_wifi_state(proto)
        return cls(
            ssid=ssid,
            ip=ip,
            signal_dbm=signal_dbm,
            bssid=bssid,
            frequency_mhz=frequency_mhz,
        )


@dataclass(slots=True)
class QsmSensors:
    """Raw sensor data from the QSM (updated every few seconds)."""

    # Radar presence sensor (mm-wave)
    phase_detected_raw: float  # phase-channel detection strength
    target_detected_raw: float  # target-channel detection strength

    # Ambient light sensor
    als_illuminance_raw: int  # broadband illuminance
    als_ir_raw: int  # IR channel
    als_both_raw: int  # combined

    # Accelerometer (detects unit orientation/tilt)
    accel_x_raw: int
    accel_y_raw: int
    accel_z_raw: int


@dataclass(slots=True)
class QuiltSmartModule:
    """A QSM — the WiFi compute module embedded in every Quilt indoor unit."""

    id: str
    system_id: str
    led_color_code: int
    sensors: QsmSensors | None
    hosted_wifi: WifiInfo | None  # normal station mode (connects to home network)
    ap_wifi: WifiInfo | None  # access-point mode (direct device provisioning)
    p2p_wifi: WifiInfo | None  # peer-to-peer / Wi-Fi Direct (usually empty)
    software_update_info_id: str | None = None
    firmware_update_info_id: str | None = None
    local_comms_health: LocalCommsHealthStatus = field(default=LocalCommsHealthStatus.UNSPECIFIED)
    """Local mesh health (proto field 8). Available on app 1.0.26+.

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

    @classmethod
    def from_proto(cls, proto: object) -> QuiltSmartModule:
        """Construct from a protobuf QuiltSmartModule message."""
        c = proto.controls  # type: ignore[attr-defined]
        s = proto.state  # type: ignore[attr-defined]

        sensors: QsmSensors | None = None
        if s.updated_ts:
            sensors = QsmSensors(
                phase_detected_raw=s.phase_detected_raw,
                target_detected_raw=s.target_detected_raw,
                als_illuminance_raw=s.als_illuminance_raw,
                als_ir_raw=s.als_ir_raw,
                als_both_raw=s.als_both_raw,
                accel_x_raw=s.accel_x_raw,
                accel_y_raw=s.accel_y_raw,
                accel_z_raw=s.accel_z_raw,
            )

        def _wifi(w: object) -> WifiInfo | None:
            info = WifiInfo.from_proto(w)
            return info if info.connected else None

        return cls(
            id=proto.header.object_id,  # type: ignore[attr-defined]
            system_id=proto.header.system_id,  # type: ignore[attr-defined]
            led_color_code=c.led_color_code,
            sensors=sensors,
            hosted_wifi=_wifi(proto.hosted_wifi_state),  # type: ignore[attr-defined]
            ap_wifi=_wifi(proto.ap_wifi_state),  # type: ignore[attr-defined]
            p2p_wifi=_wifi(proto.p2p_wifi_state),  # type: ignore[attr-defined]
            software_update_info_id=(
                proto.relationships.software_update_info_id or None  # type: ignore[attr-defined]
            ),
            firmware_update_info_id=(
                proto.relationships.firmware_update_info_id or None  # type: ignore[attr-defined]
            ),
            local_comms_health=LocalCommsHealthStatus(
                getattr(getattr(proto, "local_comms_status", None), "health", 0)
            ),
            local_comms_link_state=getattr(
                getattr(proto, "local_comms_status", None), "link_state", None
            ),
            local_comms_connection_state=getattr(
                getattr(proto, "local_comms_status", None), "connection_state", None
            ),
            local_comms_version=getattr(
                getattr(proto, "local_comms_status", None), "version", None
            ),
        )
