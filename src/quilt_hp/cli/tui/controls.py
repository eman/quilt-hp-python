"""Room control decisions shared by the Home and Room screens.

The decisions are pure (what mode comes next, which setpoint ``+``/``−`` changes); the async
helpers send the change and merge the result into the shared snapshot.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from quilt_hp.cli.constants import (
    DEFAULT_COOL_SETPOINT_C,
    DEFAULT_HEAT_SETPOINT_C,
    clamp_setpoint_c,
)
from quilt_hp.cli.tui.format import _FAN_CYCLE, _LOUVER_CYCLE, _MODE_CYCLE, _cycle_next
from quilt_hp.models.enums import FanSpeed, HVACMode, LouverMode

if TYPE_CHECKING:
    from quilt_hp.client import QuiltClient
    from quilt_hp.models.indoor_unit import IndoorUnit
    from quilt_hp.models.space import Space
    from quilt_hp.models.system import SystemSnapshot

STEP_C = 0.5
STEP_F_IN_C = 5 / 9  # one degree Fahrenheit


def step_cycle[T](current: T, cycle: list[T], direction: int) -> T:
    """The next (``direction`` 1) or previous (-1) value in ``cycle``, wrapping around."""
    if current not in cycle:
        return cycle[0]
    return cycle[(cycle.index(current) + direction) % len(cycle)]


def next_mode(space: Space) -> HVACMode:
    """The mode ``m`` switches to. A room in Away goes to Standby first."""
    if space.is_away:
        return HVACMode.STANDBY
    return _cycle_next(space.controls.hvac_mode, _MODE_CYCLE)


@dataclass(frozen=True, slots=True)
class SetpointChange:
    """A setpoint to send; exactly one of the two is set."""

    heat_c: float | None = None
    cool_c: float | None = None


def nudge_setpoint(space: Space, direction: int, use_f: bool = False) -> SetpointChange | None:
    """The change ``+`` (direction 1) or ``−`` (-1) makes, or None when the mode has no setpoint.

    Cool adjusts the cooling setpoint and Heat the heating one. Auto adjusts whichever setpoint is
    nearer the room temperature, the one the room is working towards. Dry, Fan and Standby have
    no setpoint (the service doesn't send one for Dry), so they return None.
    """
    c = space.controls
    step = (STEP_F_IN_C if use_f else STEP_C) * direction
    heat = c.heating_setpoint_c or DEFAULT_HEAT_SETPOINT_C
    cool = c.cooling_setpoint_c or DEFAULT_COOL_SETPOINT_C
    if c.hvac_mode == HVACMode.COOL:
        return SetpointChange(cool_c=clamp_setpoint_c(cool + step))
    if c.hvac_mode == HVACMode.HEAT:
        return SetpointChange(heat_c=clamp_setpoint_c(heat + step))
    if c.hvac_mode == HVACMode.AUTO:
        room = space.state.ambient_temperature_c if space.state else None
        if room is not None and abs(room - heat) < abs(room - cool):
            return SetpointChange(heat_c=clamp_setpoint_c(heat + step))
        return SetpointChange(cool_c=clamp_setpoint_c(cool + step))
    return None


async def send_space_change(
    client: QuiltClient,
    snapshot: SystemSnapshot | None,
    space: Space,
    *,
    mode: HVACMode | None = None,
    change: SetpointChange | None = None,
) -> Space:
    """Send a mode and/or setpoint change and merge the result into the shared snapshot."""
    updated = await client.set_space(
        space,
        mode=mode,
        heat_setpoint_c=change.heat_c if change else None,
        cool_setpoint_c=change.cool_c if change else None,
    )
    if snapshot is not None:
        updated = snapshot.apply_space(updated)
    return updated


def next_fan(idu: IndoorUnit) -> FanSpeed:
    """The fan speed ``f`` switches to."""
    return _cycle_next(idu.controls.fan_speed, _FAN_CYCLE)


def next_louver(idu: IndoorUnit) -> LouverMode:
    """The louver mode ``v`` switches to."""
    return _cycle_next(idu.controls.louver_mode, _LOUVER_CYCLE)


def light_toggle_brightness(idu: IndoorUnit) -> float:
    """The LED brightness that toggles the light: 0 when on, else the last level used.

    The server keeps the stored brightness while the light is off; when that is 0 the room's
    default level is used, then full brightness.
    """
    if idu.controls.light_on:
        return 0.0
    if idu.controls.led_brightness > 0.0:
        return idu.controls.led_brightness
    return idu.settings.light_brightness_default_percent or 1.0


async def send_idu_change(
    client: QuiltClient, snapshot: SystemSnapshot | None, idu: IndoorUnit, **changes: Any
) -> IndoorUnit:
    """Send indoor-unit control changes and merge the result into the shared snapshot."""
    updated = await client.set_indoor_unit(idu, **changes)
    if snapshot is not None:
        updated = snapshot.apply_indoor_unit(updated)
    return updated


def room_lock(app: object, space_id: str) -> asyncio.Lock:
    """The lock that serialises control changes for one room across every screen.

    Changes for a room run one at a time and each computes its target from the room as the
    previous change left it, so two quick ``+`` presses from 24 °C reach 25 °C. The locks live
    on the app (an ``asyncio.Lock`` belongs to one event loop).
    """
    locks: dict[str, asyncio.Lock] | None = getattr(app, "control_locks", None)
    if locks is None:
        locks = {}
        with contextlib.suppress(AttributeError):
            app.control_locks = locks  # type: ignore[attr-defined]
    return locks.setdefault(space_id, asyncio.Lock())
