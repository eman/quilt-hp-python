"""QuiltSmartModule (QSM) model — the WiFi compute module embedded in each IDU.

Each indoor unit contains one QSM that handles:
- Cloud/local NATS connectivity (three WiFi interfaces: hosted, AP, P2P)
- Presence detection (phase + target radar channels)
- Ambient light sensing (ALS: illuminance, IR, combined)
- Accelerometer (X/Y/Z — detects unit tilt/movement)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class WifiInfo:
    """WiFi interface snapshot (one of three on a QSM)."""

    ssid: str | None
    ip: str | None
    signal_dbm: int | None

    @property
    def connected(self) -> bool:
        return bool(self.ssid)

    @classmethod
    def from_proto(cls, proto: object) -> WifiInfo:
        ssid = getattr(proto, "ssid", None) or None
        ip = getattr(proto, "ipv4_address", None) or None
        sig = getattr(proto, "signal_level_dbm", None) or None
        return cls(ssid=ssid, ip=ip, signal_dbm=sig)


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
            software_update_info_id=proto.relationships.software_update_info_id or None,  # type: ignore[attr-defined]
            firmware_update_info_id=proto.relationships.firmware_update_info_id or None,  # type: ignore[attr-defined]
        )
