"""Tests for model enums and wire encoding/decoding."""

from __future__ import annotations

from quilt_hp.models.enums import (
    FanSpeed,
    HVACMode,
    HVACState,
    LocalCommsHealthStatus,
    LouverAngle,
    LouverMode,
)


def test_hvac_mode_values() -> None:
    """Proto wire values match expected enum numbering."""
    assert HVACMode.STANDBY == 1
    assert HVACMode.COOL == 2
    assert HVACMode.HEAT == 3
    assert HVACMode.AUTO == 4
    assert HVACMode.FAN == 5
    assert HVACMode.FALLBACK_AUTO == 6
    assert HVACMode.FALLBACK_OFF == 7
    assert HVACMode.DRY == 8


def test_hvac_state_values() -> None:
    """HVACState wire values."""
    assert HVACState.STANDBY == 1
    assert HVACState.COOL == 2
    assert HVACState.HEAT == 3
    assert HVACState.DRIFT == 4
    assert HVACState.COOL_DEFERRED == 6
    assert HVACState.HEAT_PREPARING == 10
    assert HVACState.DRY == 11
    assert HVACState.DRY_DEFERRED == 12
    assert HVACState.DRY_PREPARING == 13


def test_local_comms_health_status_values() -> None:
    """LocalCommsHealthStatus wire values (proto field 8/9 on QSM/Controller)."""
    assert LocalCommsHealthStatus.UNSPECIFIED == 0
    assert LocalCommsHealthStatus.HEALTHY == 1
    assert LocalCommsHealthStatus.DEGRADED == 2
    assert LocalCommsHealthStatus.OFFLINE == 3
    assert LocalCommsHealthStatus.STARTING_UP == 4


def test_fan_speed_wire_roundtrip() -> None:
    """FanSpeed to wire and back should preserve the label."""
    for speed in FanSpeed:
        mode, pct = speed.to_wire()
        decoded = FanSpeed.from_wire(mode, pct)
        assert decoded == speed, f"Roundtrip failed for {speed}: got {decoded}"


def test_fan_speed_auto_from_wire() -> None:
    """Non-SETPOINT mode should decode to AUTO."""
    assert FanSpeed.from_wire(1, 0.5) == FanSpeed.AUTO
    assert FanSpeed.from_wire(0, 0.0) == FanSpeed.AUTO


def test_louver_angle_wire_roundtrip() -> None:
    """LouverAngle to wire and back."""
    for angle in LouverAngle:
        pos = angle.to_wire()
        decoded = LouverAngle.from_wire(pos)
        assert decoded == angle, f"Roundtrip failed for {angle}: got {decoded}"


def test_louver_mode_values() -> None:
    """LouverMode wire values match proto enum."""
    assert LouverMode.CLOSED == 1
    assert LouverMode.SWEEP == 2
    assert LouverMode.FIXED == 3
    assert LouverMode.AUTO == 4


def test_enum_str() -> None:
    """Enums have clean __str__."""
    assert str(HVACMode.COOL) == "COOL"
    assert str(HVACState.HEAT_PREPARING) == "HEAT_PREPARING"
    assert str(FanSpeed.MEDIUM) == "MEDIUM"
