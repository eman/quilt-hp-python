"""Remote sensor and ControllerRemoteSensor models.

RemoteSensor: standalone BLE temperature/humidity puck linked to an IndoorUnit.
  - Proto field 12 in HomeDatastoreSystem (empty if no sensors paired).
  - APK: C5534qL.java (proto), C3056e81.java (KMP model).

ControllerRemoteSensor: sensor capability of a Controller (Dial) for zones.
  - Proto field 16 in HomeDatastoreSystem (empty if sensor mode not configured).
  - APK: CI.java (proto), JD.java (KMP model).
  - Shares RemoteSensorState and RemoteSensorAttributes with RemoteSensor.
"""

from __future__ import annotations

from dataclasses import dataclass

from quilt_hp.models.enums import RemoteSensorControlMode


def _parse_state(
    s: object,
) -> tuple[float | None, float | None, float | None, int | None]:
    """Return ambient temp, humidity, battery, and signal from proto state."""
    return (
        s.ambient_temperature_c or None,  # type: ignore[attr-defined]
        s.humidity_percent or None,  # type: ignore[attr-defined]
        s.battery_level_percent or None,  # type: ignore[attr-defined]
        s.signal_level_dbm or None,  # type: ignore[attr-defined]
    )


@dataclass(slots=True)
class RemoteSensor:
    """A standalone BLE remote sensor linked to an IndoorUnit."""

    id: str
    indoor_unit_id: str
    mac: str | None
    ambient_temperature_c: float | None
    humidity_percent: float | None
    battery_level_percent: float | None
    signal_level_dbm: int | None
    control_mode: RemoteSensorControlMode

    @classmethod
    def from_proto(cls, proto: object) -> RemoteSensor:
        """Construct from a protobuf RemoteSensor message."""
        at, hum, bat, sig = _parse_state(proto.state)  # type: ignore[attr-defined]
        return cls(
            id=proto.header.object_id,  # type: ignore[attr-defined]
            indoor_unit_id=proto.relationships.indoor_unit_id,  # type: ignore[attr-defined]
            mac=proto.attributes.mac or None,  # type: ignore[attr-defined]
            ambient_temperature_c=at,
            humidity_percent=hum,
            battery_level_percent=bat,
            signal_level_dbm=sig,
            control_mode=RemoteSensorControlMode(proto.controls.control_mode),  # type: ignore[attr-defined]
        )


@dataclass(slots=True)
class ControllerRemoteSensor:
    """The remote-sensor capability of a Controller (Dial).

    When a Dial's remote_sensor_control_mode is ENABLED, the system creates a
    ControllerRemoteSensor entity to expose its temperature/humidity readings
    as a zone control input. Linked to a Controller via controller_id.
    """

    id: str
    controller_id: str
    mac: str | None
    ambient_temperature_c: float | None
    humidity_percent: float | None
    battery_level_percent: float | None
    signal_level_dbm: int | None
    control_mode: RemoteSensorControlMode

    @classmethod
    def from_proto(cls, proto: object) -> ControllerRemoteSensor:
        """Construct from a protobuf ControllerRemoteSensor message."""
        at, hum, bat, sig = _parse_state(proto.state)  # type: ignore[attr-defined]
        return cls(
            id=proto.header.object_id,  # type: ignore[attr-defined]
            controller_id=proto.relationships.controller_id,  # type: ignore[attr-defined]
            mac=proto.attributes.mac or None,  # type: ignore[attr-defined]
            ambient_temperature_c=at,
            humidity_percent=hum,
            battery_level_percent=bat,
            signal_level_dbm=sig,
            control_mode=RemoteSensorControlMode(proto.controls.control_mode),  # type: ignore[attr-defined]
        )
