"""QuiltSmartModule (QSM) model — the WiFi compute module embedded in each IDU.

Each indoor unit contains one QSM that handles:
- Cloud connectivity + local Zenoh mesh connectivity (three WiFi interfaces:
  hosted, AP, P2P)
- Presence detection (phase + target radar channels)
- Ambient light sensing (ALS: illuminance, IR, combined)
- Accelerometer (X/Y/Z — detects unit tilt/movement)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

from quilt_hp.models._helpers import (
    local_comms_last_session_change,
    parse_wifi_state,
    present_submsg,
)
from quilt_hp.models.enums import LocalCommsHealthReason, LocalCommsHealthStatus


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

    @classmethod
    def from_proto(cls, proto: object) -> QuiltSmartModule:
        """Construct from a protobuf QuiltSmartModule message.

        Sub-messages absent from a sparse stream diff parse to ``None`` /
        sentinel defaults; ``SystemSnapshot.apply_qsm`` preserves existing
        snapshot data for them.
        """
        p = cast("Any", proto)
        c = cast("Any", present_submsg(proto, "controls"))
        s = cast("Any", present_submsg(proto, "state"))

        sensors: QsmSensors | None = None
        if s is not None:
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

        def _wifi(w: object | None) -> WifiInfo | None:
            if w is None:
                return None
            info = WifiInfo.from_proto(w)
            return info if info.connected else None

        rel = cast("Any", present_submsg(proto, "relationships"))
        return cls(
            id=p.header.object_id,
            system_id=p.header.system_id,
            led_color_code=c.led_color_code if c is not None else 0,
            sensors=sensors,
            hosted_wifi=_wifi(present_submsg(proto, "hosted_wifi_state")),
            ap_wifi=_wifi(present_submsg(proto, "ap_wifi_state")),
            p2p_wifi=_wifi(present_submsg(proto, "p2p_wifi_state")),
            software_update_info_id=(
                (rel.software_update_info_id or None) if rel is not None else None
            ),
            firmware_update_info_id=(
                (rel.firmware_update_info_id or None) if rel is not None else None
            ),
            local_comms_health=LocalCommsHealthStatus(
                getattr(getattr(proto, "local_comms_status", None), "status", 0)
            ),
            local_comms_visible_devices=getattr(
                getattr(proto, "local_comms_status", None), "visible_devices_count", None
            ),
            local_comms_expected_devices=getattr(
                getattr(proto, "local_comms_status", None), "expected_devices_count", None
            ),
            local_comms_reason=LocalCommsHealthReason(
                getattr(getattr(proto, "local_comms_status", None), "reason", 0)
            ),
            local_comms_last_session_change=local_comms_last_session_change(
                getattr(proto, "local_comms_status", None)
            ),
        )
