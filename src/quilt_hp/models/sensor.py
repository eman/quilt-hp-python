"""Remote sensor and ControllerRemoteSensor models.

RemoteSensor: standalone BLE temperature/humidity puck linked to an IndoorUnit.
  - Proto field 12 in HomeDatastoreSystem (empty if no sensors paired).

ControllerRemoteSensor: sensor capability of a Controller (Dial) for zones.
  - Proto field 16 in HomeDatastoreSystem (empty if sensor mode not configured).
  - Shares RemoteSensorState and RemoteSensorAttributes with RemoteSensor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from quilt_hp.models._helpers import present_submsg
from quilt_hp.models.enums import RemoteSensorControlMode


def _parse_state(
    s: object | None,
) -> tuple[float | None, float | None, float | None, int | None]:
    """Return ambient temp, humidity, battery, and signal from proto state.

    ``s`` is ``None`` when the ``state`` sub-message was absent from the wire
    (sparse stream diff) — all readings are then ``None`` so that
    ``SystemSnapshot.apply_*`` preserves existing values.
    """
    if s is None:
        return (None, None, None, None)
    return (
        getattr(s, "ambient_temperature_c", None),
        getattr(s, "humidity_percent", None),
        getattr(s, "battery_level_percent", None),
        getattr(s, "signal_level_dbm", None),
    )


def _parse_control_mode(proto: object) -> RemoteSensorControlMode:
    controls = cast("Any", present_submsg(proto, "controls"))
    if controls is None:
        return RemoteSensorControlMode.UNSPECIFIED
    return RemoteSensorControlMode(controls.control_mode)


def _parse_mac(proto: object) -> str | None:
    attributes = cast("Any", present_submsg(proto, "attributes"))
    if attributes is None:
        return None
    return attributes.mac or None


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
        at, hum, bat, sig = _parse_state(present_submsg(proto, "state"))
        rel = cast("Any", present_submsg(proto, "relationships"))
        return cls(
            id=cast("Any", proto).header.object_id,
            indoor_unit_id=rel.indoor_unit_id if rel is not None else "",
            mac=_parse_mac(proto),
            ambient_temperature_c=at,
            humidity_percent=hum,
            battery_level_percent=bat,
            signal_level_dbm=sig,
            control_mode=_parse_control_mode(proto),
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
        at, hum, bat, sig = _parse_state(present_submsg(proto, "state"))
        rel = cast("Any", present_submsg(proto, "relationships"))
        return cls(
            id=cast("Any", proto).header.object_id,
            controller_id=rel.controller_id if rel is not None else "",
            mac=_parse_mac(proto),
            ambient_temperature_c=at,
            humidity_percent=hum,
            battery_level_percent=bat,
            signal_level_dbm=sig,
            control_mode=_parse_control_mode(proto),
        )
