"""Pythonic enums mirroring the Quilt protobuf enum values."""

from __future__ import annotations

from enum import IntEnum


class HVACMode(IntEnum):
    """HVAC operating mode."""

    UNSPECIFIED = 0
    STANDBY = 1
    COOL = 2
    HEAT = 3
    AUTO = 4
    FAN = 5
    FALLBACK_AUTO = 6
    FALLBACK_OFF = 7

    def __str__(self) -> str:
        return self.name


class HVACState(IntEnum):
    """Current HVAC state (what the system is actually doing)."""

    UNSPECIFIED = 0
    STANDBY = 1
    COOL = 2
    HEAT = 3
    DRIFT = 4
    FAN = 5
    COOL_DEFERRED = 6
    HEAT_DEFERRED = 7
    FAN_DEFERRED = 8
    COOL_PREPARING = 9
    HEAT_PREPARING = 10

    def __str__(self) -> str:
        return self.name


class FanSpeed(IntEnum):
    """Discrete fan speed labels (maps to mode + percent on the wire)."""

    AUTO = 0
    QUIET = 1
    LOW = 2
    MEDIUM = 3
    HIGH = 4
    BLAST = 5

    def __str__(self) -> str:
        return self.name

    def to_wire(self) -> tuple[int, float]:
        """Return (fan_speed_mode, fan_speed_percent) for the wire protocol."""
        _MAP: dict[FanSpeed, tuple[int, float]] = {
            FanSpeed.AUTO: (1, 0.0),  # FAN_SPEED_MODE_AUTO
            FanSpeed.QUIET: (2, 0.20),  # FAN_SPEED_MODE_SETPOINT
            FanSpeed.LOW: (2, 0.40),
            FanSpeed.MEDIUM: (2, 0.60),
            FanSpeed.HIGH: (2, 0.80),
            FanSpeed.BLAST: (2, 1.00),
        }
        return _MAP[self]

    @classmethod
    def from_wire(cls, mode: int, percent: float) -> FanSpeed:
        """Decode wire fan_speed_mode/fan_speed_percent to FanSpeed label."""
        if mode != 2:  # FAN_SPEED_MODE_SETPOINT
            return cls.AUTO
        if percent <= 0.21:
            return cls.QUIET
        if percent <= 0.41:
            return cls.LOW
        if percent <= 0.61:
            return cls.MEDIUM
        if percent <= 0.81:
            return cls.HIGH
        return cls.BLAST


class LouverMode(IntEnum):
    """Indoor unit louver mode."""

    UNSPECIFIED = 0
    CLOSED = 1
    SWEEP = 2
    FIXED = 3
    AUTO = 4

    def __str__(self) -> str:
        return self.name


_LOUVER_ANGLE_LABELS: dict[int, str] = {
    1: "Horizontal",
    2: "Slightly Down",
    3: "Down",
    4: "Mostly Down",
    5: "Straight Down",
}


class LouverAngle(IntEnum):
    """Discrete louver angle positions (when mode=FIXED).

    Positions run from most horizontal (ANGLE1) to most downward (ANGLE5).
    """

    ANGLE1 = 1
    ANGLE2 = 2
    ANGLE3 = 3
    ANGLE4 = 4
    ANGLE5 = 5

    @property
    def label(self) -> str:
        """Human-readable position name."""
        return _LOUVER_ANGLE_LABELS[self.value]

    def __str__(self) -> str:
        return self.label

    def to_wire(self) -> float:
        """Return the louver_fixed_position float for the wire."""
        return {1: 0.20, 2: 0.40, 3: 0.60, 4: 0.80, 5: 1.00}[self.value]

    @classmethod
    def from_wire(cls, position: float) -> LouverAngle:
        """Decode a wire louver_fixed_position to a LouverAngle."""
        if position <= 0.21:
            return cls.ANGLE1
        if position <= 0.41:
            return cls.ANGLE2
        if position <= 0.61:
            return cls.ANGLE3
        if position <= 0.81:
            return cls.ANGLE4
        return cls.ANGLE5


class LightPreset(IntEnum):
    """Built-in LED color presets (RGBW packed int32)."""

    DAYLIGHT = 0x000000FF
    WARM = 0xFF460064
    SUNSET = 0xFF460024
    SKY = 0x009CFF54

    def __str__(self) -> str:
        return self.name


class LedAnimation(IntEnum):
    """Indoor unit LED animation modes.

    Note: NONE = 1 (not 0).  UNSPECIFIED = 0 means the field was absent from
    the wire diff; NONE means the server explicitly set "no animation" (solid
    colour).  Callers should treat UNSPECIFIED the same as NONE for display.
    """

    UNSPECIFIED = 0
    NONE = 1
    SPARKLE_FADE = 2
    TWINKLE_FADE = 3
    DANCE = 4
    CHASE = 5

    def __str__(self) -> str:
        return self.name


class ComfortSettingType(IntEnum):
    """Type of comfort preset."""

    UNSPECIFIED = 0
    ACTIVE = 1
    SLEEP = 2
    AWAY = 3
    STANDBY = 4
    CUSTOM = 5

    def __str__(self) -> str:
        return self.name


class OccupancyMode(IntEnum):
    """Space-level auto-away/return occupancy mode."""

    UNSPECIFIED = 0
    DISABLED = 1
    ENABLED = 2

    def __str__(self) -> str:
        return self.name


class SafetyHeatingMode(IntEnum):
    """Freeze protection mode for a space."""

    UNSPECIFIED = 0  # treated as ENABLED by the device
    DISABLED = 1
    ENABLED = 2

    def __str__(self) -> str:
        return self.name


class OccupancyState(IntEnum):
    """Occupancy detection state."""

    UNSPECIFIED = 0
    UNDETECTED = 1
    DETECTED = 2

    def __str__(self) -> str:
        return self.name


class Presence(IntEnum):
    """Raw radar sensor presence detection."""

    UNSPECIFIED = 0
    UNDETECTED = 1
    DETECTED = 2

    def __str__(self) -> str:
        return self.name


class LightState(IntEnum):
    """Explicit LED on/off state (field 13 of IndoorUnitControls).

    Sent when the ``mobile_led_scheduling_enabled`` Statsig gate is on.
    When state=OFF, brightness is **preserved** server-side (not zeroed) so
    toggling back on restores the prior brightness.  When UNSPECIFIED, fall
    back to brightness-based detection.
    """

    UNSPECIFIED = 0
    ON = 1
    OFF = 2

    def __str__(self) -> str:
        return self.name


class ConditionState(IntEnum):
    """Fault condition state."""

    UNSPECIFIED = 0
    INACTIVE = 1
    ACTIVE = 2

    def __str__(self) -> str:
        return self.name


class HvacControllerType(IntEnum):
    """Algorithm variant used by the controller to drive the IDU."""

    UNSPECIFIED = 0
    PASS_THROUGH_TEMPERATURE = 1
    INTEGRAL_TEMPERATURE_V1 = 2
    INTEGRAL_TEMPERATURE_V2 = 3

    def __str__(self) -> str:
        return self.name


class MetricBucketStatus(IntEnum):
    """Energy-metric bucket completeness state."""

    UNSPECIFIED = 0
    COMPLETE = 1
    INCOMPLETE = 2

    def __str__(self) -> str:
        return self.name


class BoostMode(IntEnum):
    """Boost (turbo) mode override for a space."""

    UNSPECIFIED = 0
    OFF = 1
    ON = 2

    def __str__(self) -> str:
        return self.name


class ComfortSettingOverride(IntEnum):
    """Why the active comfort setting differs from the schedule."""

    UNSPECIFIED = 0
    NONE = 1
    UNTIL_NEXT_SCHEDULE = 2
    INDEFINITE = 3
    SCHEDULE = 4
    UNOCCUPIED = 5
    OCCUPIED = 6

    def __str__(self) -> str:
        return self.name


class FallbackControlCommand(IntEnum):
    """Command sent when the Dial loses cloud connectivity."""

    UNSPECIFIED = 0
    COMPLETE = 1
    EXIT = 2

    def __str__(self) -> str:
        return self.name


class RemoteSensorControlMode(IntEnum):
    """Whether the Dial acts as the zone temperature sensor."""

    UNSPECIFIED = 0
    DISABLED = 1
    ENABLED = 2

    def __str__(self) -> str:
        return self.name
