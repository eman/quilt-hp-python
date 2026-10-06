"""The action API (HomeActionService.SubmitAction): request building, outcomes, client methods."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from quilt_hp import QuiltActionError
from quilt_hp._proto import quilt_actions_pb2 as act
from quilt_hp.client import QuiltClient
from quilt_hp.models import (
    ActionResult,
    ClimateMode,
    FanAngle,
    FanSpeed,
    HVACMode,
    LedAnimation,
    LightPreset,
    RgbwColor,
)
from quilt_hp.services import actions


def _targets() -> list[act.ActionTarget]:
    return actions.build_targets(rooms=["room-1"], indoor_units=["idu-1"], system_id="sys-1")


def test_targets_mix_rooms_units_and_house() -> None:
    kinds = [t.WhichOneof("kind") for t in _targets()]
    assert kinds == ["space_id", "indoor_unit_id", "system_id"]
    with pytest.raises(ValueError, match="at least one"):
        actions.build_targets()


@pytest.mark.parametrize(
    ("mode", "wire"),
    [
        (ClimateMode.AWAY, act.CLIMATE_MODE_AWAY),
        (ClimateMode.AUTO, act.CLIMATE_MODE_DUAL_SETPOINT),
        (HVACMode.STANDBY, act.CLIMATE_MODE_OFF),
        (HVACMode.COOL, act.CLIMATE_MODE_COOL),  # HVACMode.COOL is 2; the action API's COOL is 3
        (HVACMode.AUTO, act.CLIMATE_MODE_DUAL_SETPOINT),
    ],
)
def test_mode_uses_the_action_api_numbering(mode: ClimateMode | HVACMode, wire: int) -> None:
    built = actions.build_mode(_targets(), mode)
    assert built.climate.set_mode.mode == wire
    assert len(built.climate.set_mode.targets) == 3


def test_modes_the_action_api_cannot_set() -> None:
    with pytest.raises(ValueError):
        actions.build_mode(_targets(), HVACMode.FALLBACK_AUTO)
    with pytest.raises(ValueError):
        actions.build_mode(_targets(), ClimateMode.UNSPECIFIED)


def test_temperatures_send_only_what_is_given() -> None:
    temps = actions.build_temperatures(_targets(), None, 23.5).climate.set_temperatures
    assert not temps.HasField("heat_setpoint_c")
    assert temps.cool_setpoint_c == pytest.approx(23.5)
    with pytest.raises(ValueError):
        actions.build_temperatures(_targets(), None, None)


def test_fan_speed_and_angle() -> None:
    speed = actions.build_fan_speed(_targets(), FanSpeed.QUIET).climate.set_fan_speed
    assert speed.fan_speed.level == act.FAN_SPEED_LEVEL_QUIET  # FanSpeed.QUIET is 1; wire is 2
    angle = actions.build_fan_angle(_targets(), FanAngle.FLOOR).climate.set_fan_angle
    assert angle.fan_angle.level == act.FAN_ANGLE_LEVEL_FLOOR


def test_light_preset_custom_colour_and_partial_controls() -> None:
    preset = actions.build_light(
        _targets(), on=True, brightness_percent=40, color=LightPreset.SUNSET, animation=None
    ).light.set_light.controls
    assert preset.power == act.LIGHT_POWER_ON
    assert preset.brightness_percent == pytest.approx(0.40)  # 40 % travels as a 0–1 fraction
    assert preset.color.preset == act.LIGHT_COLOR_PRESET_SUNSET
    assert preset.animation == act.LIGHT_ANIMATION_UNSPECIFIED  # left unchanged

    custom = actions.build_light(
        _targets(),
        on=None,
        brightness_percent=None,
        color=RgbwColor(255, 64, 0),
        animation=LedAnimation.CHASE,
    ).light.set_light.controls
    assert custom.power == act.LIGHT_POWER_UNSPECIFIED
    assert not custom.HasField("brightness_percent")
    assert (custom.color.custom.red, custom.color.custom.green, custom.color.custom.blue) == (
        255,
        64,
        0,
    )
    assert custom.animation == act.LIGHT_ANIMATION_CHASE


def test_light_validation() -> None:
    with pytest.raises(ValueError):
        actions.build_light(
            _targets(), on=None, brightness_percent=None, color=None, animation=None
        )
    with pytest.raises(ValueError):
        actions.build_light(
            _targets(), on=None, brightness_percent=150, color=None, animation=None
        )
    with pytest.raises(ValueError):
        RgbwColor(red=256)


def test_request_carries_a_user_source_and_an_idempotency_key() -> None:
    request = actions.build_request("sys-1", actions.build_mode(_targets(), ClimateMode.OFF))
    assert request.system_id == "sys-1"
    assert request.source.WhichOneof("source") == "user"
    first = request.client_request_id
    assert first and first != actions.build_request("sys-1", request.action).client_request_id
    assert act.SubmitActionRequest.FromString(request.SerializeToString()) == request


def test_outcomes() -> None:
    ok = actions.outcome_from(
        act.SubmitActionResponse(action_id="a-1", result=act.ACTION_RESULT_SUCCESS)
    )
    assert ok.ok and ok.action_id == "a-1"
    partial = actions.outcome_from(
        act.SubmitActionResponse(
            result=act.ACTION_RESULT_PARTIAL_FAILURE, failure_reason="one unit offline"
        )
    )
    assert partial.result is ActionResult.PARTIAL_FAILURE and not partial.ok
    with pytest.raises(QuiltActionError, match="target not found") as info:
        actions.outcome_from(
            act.SubmitActionResponse(
                result=act.ACTION_RESULT_FAILED, failure_reason="target not found"
            )
        )
    assert info.value.outcome.result is ActionResult.FAILED


async def test_client_targets_follow_the_app_and_refresh_the_cache() -> None:
    """Mode/temperatures address rooms; fan, louver and light address each room's indoor units;
    whole house expands to every room or unit (the system-wide target isn't used)."""
    from tests.tui_harness import load_snapshot

    snap = load_snapshot()
    client = QuiltClient("user@example.com")
    client._system_id = "sys-1"
    client.get_snapshot = AsyncMock(return_value=snap)  # type: ignore[method-assign]
    service = MagicMock(
        submit=AsyncMock(
            return_value=actions.outcome_from(
                act.SubmitActionResponse(result=act.ACTION_RESULT_SUCCESS)
            )
        )
    )
    client._actions = service
    client._snapshot_cache = object()  # type: ignore[assignment]

    def sent() -> list[tuple[str, str]]:
        action = service.submit.await_args.args[1]
        inner = getattr(action, action.WhichOneof("category"))
        targets = getattr(inner, inner.WhichOneof("action")).targets
        return [(t.WhichOneof("kind"), getattr(t, t.WhichOneof("kind"))) for t in targets]

    family = next(r for r in snap.rooms if r.name == "Family Room")
    family_unit = snap.indoor_units_for_space(family)[0]

    outcome = await client.apply_temperatures(cool_c=24.0, rooms=[family, "room-2"])
    assert outcome.ok
    assert sent() == [("space_id", family.id), ("space_id", "room-2")]
    assert client._snapshot_cache is None  # the next snapshot reflects the change

    await client.apply_fan_speed(FanSpeed.QUIET, rooms=[family])
    assert sent() == [("indoor_unit_id", family_unit.id)]  # a room expands to its unit

    await client.apply_mode(HVACMode.STANDBY, whole_house=True)
    assert sent() == [("space_id", r.id) for r in snap.rooms]

    await client.apply_light(on=False, whole_house=True)
    assert sorted(sent()) == sorted(("indoor_unit_id", u.id) for u in snap.indoor_units)

    await client.apply_fan_angle(FanAngle.AUTO, indoor_units=["idu-9"])
    assert sent() == [("indoor_unit_id", "idu-9")]
    assert all(kind != "system_id" for kind, _ in sent())

    with pytest.raises(ValueError, match="at least one"):
        await client.apply_mode(ClimateMode.OFF)
