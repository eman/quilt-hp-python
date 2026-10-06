"""HomeActionService: apply climate and light actions to rooms, indoor units or the whole house.

Request building is pure (``build_*``) so it is tested without a server.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any, cast

from quilt_hp._proto import quilt_actions_pb2 as act
from quilt_hp._proto import quilt_actions_pb2_grpc as act_grpc
from quilt_hp.exceptions import QuiltActionError
from quilt_hp.models._helpers import enum_or
from quilt_hp.models.actions import ActionOutcome, RgbwColor
from quilt_hp.models.enums import (
    ActionResult,
    ClimateMode,
    FanAngle,
    FanSpeed,
    HVACMode,
    LedAnimation,
    LightPreset,
)
from quilt_hp.services import grpc_call

if TYPE_CHECKING:
    import grpc.aio

logger = logging.getLogger(__name__)

_HVAC_TO_CLIMATE = {
    HVACMode.STANDBY: ClimateMode.OFF,
    HVACMode.HEAT: ClimateMode.HEAT,
    HVACMode.COOL: ClimateMode.COOL,
    HVACMode.AUTO: ClimateMode.AUTO,
    HVACMode.FAN: ClimateMode.FAN,
    HVACMode.DRY: ClimateMode.DRY,
}


def build_targets(
    *, rooms: Iterable[str] = (), indoor_units: Iterable[str] = (), system_id: str | None = None
) -> list[act.ActionTarget]:
    """Targets for an action; ``system_id`` targets the whole house."""
    targets = [act.ActionTarget(space_id=r) for r in rooms]
    targets += [act.ActionTarget(indoor_unit_id=u) for u in indoor_units]
    if system_id is not None:
        targets.append(act.ActionTarget(system_id=system_id))
    if not targets:
        raise ValueError("An action needs at least one room, indoor unit or the whole house.")
    return targets


def build_mode(targets: list[act.ActionTarget], mode: ClimateMode | HVACMode) -> act.Action:
    if isinstance(mode, HVACMode):
        if mode not in _HVAC_TO_CLIMATE:
            raise ValueError(f"{mode.name} can't be set through the action API")
        mode = _HVAC_TO_CLIMATE[mode]
    if mode == ClimateMode.UNSPECIFIED:
        raise ValueError("Choose a mode.")
    return act.Action(
        climate=act.ClimateAction(set_mode=act.SetModeAction(targets=targets, mode=int(mode)))  # type: ignore[arg-type]
    )


def build_temperatures(
    targets: list[act.ActionTarget], heat_c: float | None, cool_c: float | None
) -> act.Action:
    if heat_c is None and cool_c is None:
        raise ValueError("Give a heating setpoint, a cooling setpoint, or both.")
    temps = act.SetTemperaturesAction(targets=targets)
    if heat_c is not None:
        temps.heat_setpoint_c = heat_c
    if cool_c is not None:
        temps.cool_setpoint_c = cool_c
    return act.Action(climate=act.ClimateAction(set_temperatures=temps))


def build_fan_speed(targets: list[act.ActionTarget], speed: FanSpeed) -> act.Action:
    level = act.FanSpeedLevel.Value(f"FAN_SPEED_LEVEL_{speed.name}")
    return act.Action(
        climate=act.ClimateAction(
            set_fan_speed=act.SetFanSpeedAction(
                targets=targets, fan_speed=act.FanSpeed(level=level)
            )
        )
    )


def build_fan_angle(targets: list[act.ActionTarget], angle: FanAngle) -> act.Action:
    if angle == FanAngle.UNSPECIFIED:
        raise ValueError("Choose a fan angle.")
    return act.Action(
        climate=act.ClimateAction(
            set_fan_angle=act.SetFanAngleAction(
                targets=targets,
                fan_angle=act.FanAngle(level=int(angle)),  # type: ignore[arg-type]
            )
        )
    )


def build_light(
    targets: list[act.ActionTarget],
    *,
    on: bool | None,
    brightness_percent: float | None,
    color: LightPreset | RgbwColor | None,
    animation: LedAnimation | None,
) -> act.Action:
    if on is None and brightness_percent is None and color is None and animation is None:
        raise ValueError("Give at least one of on, brightness_percent, color or animation.")
    controls = act.LightControls()
    if on is not None:
        controls.power = act.LIGHT_POWER_ON if on else act.LIGHT_POWER_OFF
    if brightness_percent is not None:
        if not 0 <= brightness_percent <= 100:
            raise ValueError("brightness_percent must be 0–100")
        # Despite its name, the wire field is a 0–1 fraction, like the indoor unit's own
        # led_color_brightness_percent: sending 10 stored 10.0 (verified live 2026-10-06).
        controls.brightness_percent = brightness_percent / 100
    if isinstance(color, RgbwColor):
        controls.color.custom.CopyFrom(
            act.RgbwColor(red=color.red, green=color.green, blue=color.blue, white=color.white)
        )
    elif color is not None:
        controls.color.preset = act.LightColorPreset.Value(f"LIGHT_COLOR_PRESET_{color.name}")
    if animation is not None:
        if animation == LedAnimation.UNSPECIFIED:
            raise ValueError("Choose an animation.")
        controls.animation = int(animation)  # type: ignore[assignment]
    return act.Action(
        light=act.LightAction(set_light=act.SetLightAction(targets=targets, controls=controls))
    )


def build_request(system_id: str, action: act.Action) -> act.SubmitActionRequest:
    """A request as the app sends it: a user source, plus an idempotency key."""
    return act.SubmitActionRequest(
        client_request_id=str(uuid.uuid4()),
        system_id=system_id,
        source=act.ActionSource(user=act.UserSource()),
        action=action,
    )


def outcome_from(reply: object) -> ActionOutcome:
    r = cast("Any", reply)
    outcome = ActionOutcome(
        result=enum_or(ActionResult, r.result, ActionResult.UNSPECIFIED),
        action_id=r.action_id or None,
        failure_reason=r.failure_reason or None,
    )
    if outcome.result == ActionResult.FAILED:
        raise QuiltActionError(outcome)
    return outcome


class ActionService:
    """Async wrapper for ``HomeActionService.SubmitAction``."""

    def __init__(self, channel: grpc.aio.Channel) -> None:
        factory = cast("Callable[[grpc.aio.Channel], Any]", act_grpc.HomeActionServiceStub)
        self._stub = factory(channel)

    async def submit(self, system_id: str, action: act.Action) -> ActionOutcome:
        request = build_request(system_id, action)
        logger.debug("SubmitAction %s", request.client_request_id)
        async with grpc_call("SubmitAction"):
            reply = await self._stub.SubmitAction(request)
        return outcome_from(reply)
