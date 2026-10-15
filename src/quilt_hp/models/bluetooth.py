"""Models for the BLE direct-control protocol (``quilt_hp.bluetooth``).

These mirror ``quilt_bluetooth_control.proto``: the live state a Dial reports over its
Bluetooth control service, and the enums shared by reads and writes. The protocol was added
in app 1.0.34 and is reconstructed from the app; it is not yet verified against hardware.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from quilt_hp._proto import quilt_bluetooth_control_pb2 as ble
from quilt_hp.models._helpers import enum_or, proto_has_field


class ClimateMode(IntEnum):
    """Requested climate mode (the BLE codec's own enum, distinct from ``HVACMode``)."""

    UNSPECIFIED = 0
    COOL = 1
    HEAT = 2
    FAN = 3
    AUTO = 4

    def __str__(self) -> str:
        return self.name


class ClimatePower(IntEnum):
    """Whether the unit is powered on."""

    UNSPECIFIED = 0
    OFF = 1
    ON = 2

    def __str__(self) -> str:
        return self.name


class FanSpeedMode(IntEnum):
    """Fan-speed control mode; ``PERCENT`` pairs with ``fan_speed_percent``."""

    UNSPECIFIED = 0
    AUTO = 1
    PERCENT = 2

    def __str__(self) -> str:
        return self.name


class ClimateStatus(IntEnum):
    """High-level status of the climate controller."""

    UNSPECIFIED = 0
    OFF = 1
    RUNNING = 2
    DRIFTING = 3
    DEFERRED = 4
    PREPARING = 5

    def __str__(self) -> str:
        return self.name


class ClimateOperation(IntEnum):
    """What the unit is actually doing right now."""

    UNSPECIFIED = 0
    NONE = 1
    HEAT = 2
    COOL = 3
    FAN = 4

    def __str__(self) -> str:
        return self.name


class PresenceResult(IntEnum):
    """Per-damper presence verdict."""

    UNSPECIFIED = 0
    PRESENT = 1
    ABSENT = 2
    NO_VERDICT = 3
    UNSUPPORTED = 4
    UNAVAILABLE = 5

    def __str__(self) -> str:
        return self.name


class BluetoothActionResult(IntEnum):
    """The device's verdict on a submitted action."""

    UNSPECIFIED = 0
    OK = 1
    UNSUPPORTED = 2
    INVALID = 3
    UNAVAILABLE = 4
    INTERNAL = 5

    def __str__(self) -> str:
        return self.name


@dataclass(slots=True, frozen=True)
class ClimateControls:
    """The current control settings read from the ``climate_controls`` characteristic."""

    power: ClimatePower
    mode: ClimateMode
    fan_speed_mode: FanSpeedMode
    heat_setpoint_c: float | None = None
    cool_setpoint_c: float | None = None
    fan_speed_percent: int | None = None

    @classmethod
    def from_proto(cls, proto: ble.BluetoothClimateControls) -> ClimateControls:
        return cls(
            power=enum_or(ClimatePower, proto.power, ClimatePower.UNSPECIFIED),
            mode=enum_or(ClimateMode, proto.mode, ClimateMode.UNSPECIFIED),
            fan_speed_mode=enum_or(FanSpeedMode, proto.fan_speed_mode, FanSpeedMode.UNSPECIFIED),
            heat_setpoint_c=proto.heat_setpoint_c if proto_has_field(proto, "heat_setpoint_c") else None,
            cool_setpoint_c=proto.cool_setpoint_c if proto_has_field(proto, "cool_setpoint_c") else None,
            fan_speed_percent=(
                proto.fan_speed_percent if proto_has_field(proto, "fan_speed_percent") else None
            ),
        )


@dataclass(slots=True, frozen=True)
class ClimateState:
    """What the unit is doing now, read from the ``climate_state`` characteristic."""

    status: ClimateStatus
    operation: ClimateOperation
    ambient_temperature_c: float | None = None

    @classmethod
    def from_proto(cls, proto: ble.BluetoothClimateState) -> ClimateState:
        return cls(
            status=enum_or(ClimateStatus, proto.status, ClimateStatus.UNSPECIFIED),
            operation=enum_or(ClimateOperation, proto.operation, ClimateOperation.UNSPECIFIED),
            ambient_temperature_c=(
                proto.ambient_temperature_c
                if proto_has_field(proto, "ambient_temperature_c")
                else None
            ),
        )


@dataclass(slots=True, frozen=True)
class Damper:
    """One damper channel and its presence verdict."""

    channel_index: int
    presence: PresenceResult


@dataclass(slots=True, frozen=True)
class DamperState:
    """Ducted-zone dampers read from the ``damper_state`` characteristic."""

    dampers: list[Damper] = field(default_factory=list)

    @classmethod
    def from_proto(cls, proto: ble.BluetoothDamperState) -> DamperState:
        return cls(
            dampers=[
                Damper(
                    channel_index=d.channel_index,
                    presence=enum_or(PresenceResult, d.presence, PresenceResult.UNSPECIFIED),
                )
                for d in proto.dampers
            ]
        )


@dataclass(slots=True, frozen=True)
class ChangeCounters:
    """Counters from the ``change_counters`` notify characteristic.

    Each field increments when the matching read characteristic changes, so a client re-reads
    only what moved instead of polling everything.
    """

    climate_controls: int = 0
    climate_state: int = 0
    damper_state: int = 0

    @classmethod
    def from_proto(cls, proto: ble.BluetoothChangeCounters) -> ChangeCounters:
        return cls(
            climate_controls=proto.climate_controls,
            climate_state=proto.climate_state,
            damper_state=proto.damper_state,
        )
