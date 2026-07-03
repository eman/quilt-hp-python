"""Shared CLI/TUI constants.

Setpoint bounds
---------------
Quilt uses 8.0 °C as the STANDBY heat sentinel (``STANDBY_HEAT_SENTINEL_C``
in ``quilt_hp.models.space``), which is the lowest temperature the system
will ever hold. 32 °C is a sensible upper bound for a user-facing comfort
setpoint (the 40 °C STANDBY cool sentinel is a placeholder, not a real
setpoint). User-supplied heating/cooling setpoints are validated/clamped to
this range.
"""

from __future__ import annotations

SETPOINT_MIN_C = 8.0
SETPOINT_MAX_C = 32.0

# Fallbacks used when a space has no current setpoint to step from.
DEFAULT_HEAT_SETPOINT_C = 20.0
DEFAULT_COOL_SETPOINT_C = 26.0


def clamp_setpoint_c(value_c: float) -> float:
    """Clamp a setpoint to the supported [SETPOINT_MIN_C, SETPOINT_MAX_C] range."""
    return max(SETPOINT_MIN_C, min(SETPOINT_MAX_C, value_c))
