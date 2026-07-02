"""Comfort setting (named preset) model."""

from __future__ import annotations

from dataclasses import dataclass

from quilt_hp.const import (
    LOUVER_FIXED_POSITION_SENTINEL,
    STANDBY_COOL_SENTINEL_C,
    STANDBY_HEAT_SENTINEL_C,
    UNSPECIFIED_COOL_SETPOINT_SENTINEL_C,
    UNSPECIFIED_HEAT_SETPOINT_SENTINEL_C,
)
from quilt_hp.models.enums import (
    ComfortSettingType,
    FanSpeed,
    HVACMode,
    LouverMode,
)


@dataclass(slots=True)
class ComfortSetting:
    """A named comfort preset (Active, Sleep, Away, etc.)."""

    id: str
    system_id: str
    space_id: str
    name: str
    type: ComfortSettingType
    hvac_mode: HVACMode
    heating_setpoint_c: float
    cooling_setpoint_c: float
    fan_speed: FanSpeed
    louver_mode: LouverMode = LouverMode.UNSPECIFIED
    # Position fraction 0.20–1.00 (see LouverAngle.to_wire), used when
    # louver_mode=FIXED.  0.0 is the "not applicable" placeholder.
    louver_fixed_position: float = 0.0
    # Raw wire FAN_SPEED_MODE / FAN_SPEED_PERCENT values.  Needed because
    # FanSpeed.from_wire(0, 0.0) (absent) and from_wire(1, 0.0) (AUTO) both
    # decode to FanSpeed.AUTO; echoing the raw values back on update avoids
    # converting "absent" into an explicit AUTO write.
    fan_speed_mode_raw: int = 0
    fan_speed_percent_raw: float = 0.0

    @property
    def has_standby_sentinel_setpoints(self) -> bool:
        """True when this preset carries the STANDBY 8°C/40°C sentinel pair."""
        return (
            self.heating_setpoint_c == STANDBY_HEAT_SENTINEL_C
            and self.cooling_setpoint_c == STANDBY_COOL_SENTINEL_C
        )

    @property
    def has_unspecified_setpoint_sentinels(self) -> bool:
        """True when an UNSPECIFIED comfort type carries the 0°C/0°C placeholders."""
        return (
            self.type == ComfortSettingType.UNSPECIFIED
            and self.heating_setpoint_c == UNSPECIFIED_HEAT_SETPOINT_SENTINEL_C
            and self.cooling_setpoint_c == UNSPECIFIED_COOL_SETPOINT_SENTINEL_C
        )

    @property
    def has_placeholder_setpoints(self) -> bool:
        """True when setpoints are placeholder values, not user targets."""
        return self.has_standby_sentinel_setpoints or self.has_unspecified_setpoint_sentinels

    @property
    def louver_position_is_placeholder(self) -> bool:
        """True when fixed-position is the 0.0 placeholder for non-FIXED louver modes."""
        return (
            self.louver_mode != LouverMode.FIXED
            and self.louver_fixed_position == LOUVER_FIXED_POSITION_SENTINEL
        )

    @classmethod
    def from_proto(cls, proto: object) -> ComfortSetting:
        """Construct from a protobuf ComfortSetting message."""
        a = proto.attributes  # type: ignore[attr-defined]
        return cls(
            id=proto.header.object_id,  # type: ignore[attr-defined]
            system_id=proto.header.system_id,  # type: ignore[attr-defined]
            space_id=proto.relationships.space_id,  # type: ignore[attr-defined]
            name=a.name,
            type=ComfortSettingType(a.type),
            hvac_mode=HVACMode(a.hvac_mode),
            heating_setpoint_c=a.heating_temperature_setpoint_c,
            cooling_setpoint_c=a.cooling_temperature_setpoint_c,
            fan_speed=FanSpeed.from_wire(a.fan_speed_mode, a.fan_speed_percent),
            fan_speed_mode_raw=a.fan_speed_mode,
            fan_speed_percent_raw=a.fan_speed_percent,
            louver_mode=LouverMode(a.louver_mode) if a.louver_mode else LouverMode.UNSPECIFIED,
            louver_fixed_position=a.louver_fixed_position,
        )
