from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import grpc
import pytest

from quilt_hp.exceptions import QuiltError, QuiltNotFoundError
from quilt_hp.models.enums import HVACMode
from quilt_hp.services import hds as hds_service


class _FakeRpcError(grpc.aio.AioRpcError):
    def __init__(self, code: grpc.StatusCode, details: str = "") -> None:
        self._code = code
        self._details = details

    def code(self) -> grpc.StatusCode:  # type: ignore[override]
        return self._code

    def details(self) -> str:  # type: ignore[override]
        return self._details


@pytest.mark.asyncio
async def test_hds_success_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = MagicMock(
        GetHomeDatastoreSystem=AsyncMock(return_value=SimpleNamespace()),
        UpdateSpace=AsyncMock(return_value=SimpleNamespace()),
        UpdateIndoorUnit=AsyncMock(return_value=SimpleNamespace()),
        UpdateComfortSetting=AsyncMock(return_value=SimpleNamespace()),
        CreateScheduleDay=AsyncMock(return_value=SimpleNamespace()),
        CreateScheduleWeek=AsyncMock(return_value=SimpleNamespace()),
        UpdateScheduleWeek=AsyncMock(return_value=SimpleNamespace()),
        DeleteScheduleDay=AsyncMock(return_value=None),
        UpdateScheduleDay=AsyncMock(return_value=SimpleNamespace()),
        DeleteScheduleWeek=AsyncMock(return_value=None),
        UpdateLocation=AsyncMock(return_value=None),
    )
    monkeypatch.setattr(hds_service.hds_grpc, "HomeDatastoreServiceStub", lambda _ch: stub)
    monkeypatch.setattr(hds_service.SystemSnapshot, "from_proto", lambda _obj: "snapshot")
    monkeypatch.setattr(hds_service.Space, "from_proto", lambda _obj: "space")
    monkeypatch.setattr(hds_service.IndoorUnit, "from_proto", lambda _obj: "idu")
    monkeypatch.setattr(hds_service.ComfortSetting, "from_proto", lambda _obj: "comfort")
    monkeypatch.setattr(hds_service.ScheduleDay, "from_proto", lambda _obj: "day")
    monkeypatch.setattr(hds_service.ScheduleWeek, "from_proto", lambda _obj: "week")

    svc = hds_service.HomeDatastoreService(MagicMock())
    assert await svc.get_system("sys-1") == "snapshot"

    space = SimpleNamespace(
        id="space-1",
        system_id="sys-1",
        controls=SimpleNamespace(
            hvac_mode=HVACMode.HEAT,
            heating_setpoint_c=20.0,
            cooling_setpoint_c=24.0,
            comfort_setting_id="comfort",
        ),
        settings=SimpleNamespace(
            name="Living",
            timezone="UTC",
            occupied_timeout_s=10.0,
            unoccupied_timeout_s=20.0,
            occupancy_mode=SimpleNamespace(value=1),
            safety_heating=SimpleNamespace(value=1),
        ),
    )
    assert await svc.update_space(space, mode=HVACMode.STANDBY) == "space"
    assert await svc.update_space_settings(space, occupied_timeout_s=11.0) == "space"

    idu = SimpleNamespace(
        id="idu-1",
        system_id="sys-1",
        controls=SimpleNamespace(
            fan_speed=SimpleNamespace(to_wire=lambda: (1, 20)),
            louver_mode=SimpleNamespace(value=1),
            louver_fixed_position=0.0,
            led_color_code=1,
            led_brightness=0.5,
            led_animation=1,
        ),
        settings=SimpleNamespace(
            name="IDU",
            description="",
            light_brightness_default_percent=0.5,
            presence_fence_left_m=0.0,
            presence_fence_right_m=0.0,
            presence_fence_forward_m=0.0,
            radar_sensor_distance_from_floor_m=0.0,
        ),
    )
    assert await svc.update_indoor_unit(idu, led_color_code=2) == "idu"
    assert await svc.update_indoor_unit_settings(idu, fence_left_m=1.0) == "idu"

    comfort = SimpleNamespace(
        id="comfort-1",
        system_id="sys-1",
        name="Home",
        hvac_mode=SimpleNamespace(value=3),
        heating_setpoint_c=20.0,
        cooling_setpoint_c=24.0,
        fan_speed=SimpleNamespace(to_wire=lambda: (1, 25)),
        fan_speed_mode_raw=1,
        fan_speed_percent_raw=25.0,
        type=SimpleNamespace(value=1),
    )
    assert await svc.update_comfort_setting(comfort, name="Sleep") == "comfort"

    event = SimpleNamespace(
        start_s=3600,
        comfort_setting_id="comfort-1",
        hvac_mode=3,
        heating_setpoint_c=20.0,
        cooling_setpoint_c=24.0,
        precondition=False,
    )
    week_day = SimpleNamespace(weekday=1, day_id="day-1")
    assert await svc.create_schedule_day("sys-1", "space-1", "weekday", [event]) == "day"
    assert await svc.create_schedule_week("sys-1", "space-1", [week_day]) == "week"
    assert await svc.update_schedule_week("week-1", "sys-1", "space-1", [week_day]) == "week"
    await svc.delete_schedule_day("day-1")
    assert await svc.update_schedule_day("day-1", "sys-1", "space-1", "new", [event]) == "day"
    await svc.delete_schedule_week("week-1")
    await svc.update_location_schedule_execution("loc-1", "sys-1", paused=True)
    await svc.update_location_schedule_execution("loc-1", "sys-1", paused=False)


@pytest.mark.asyncio
async def test_hds_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = MagicMock(
        GetHomeDatastoreSystem=AsyncMock(
            side_effect=_FakeRpcError(grpc.StatusCode.NOT_FOUND, "missing")
        ),
        UpdateSpace=AsyncMock(side_effect=_FakeRpcError(grpc.StatusCode.INTERNAL, "boom")),
    )
    monkeypatch.setattr(hds_service.hds_grpc, "HomeDatastoreServiceStub", lambda _ch: stub)

    svc = hds_service.HomeDatastoreService(MagicMock())
    with pytest.raises(QuiltNotFoundError):
        await svc.get_system("missing")

    space = SimpleNamespace(
        id="space-1",
        system_id="sys-1",
        controls=SimpleNamespace(
            hvac_mode=HVACMode.HEAT,
            heating_setpoint_c=20.0,
            cooling_setpoint_c=24.0,
            comfort_setting_id="comfort",
        ),
        settings=SimpleNamespace(
            name="Living",
            timezone="UTC",
            occupied_timeout_s=10.0,
            unoccupied_timeout_s=20.0,
            occupancy_mode=SimpleNamespace(value=1),
            safety_heating=SimpleNamespace(value=1),
        ),
    )

    with pytest.raises(QuiltError, match="UpdateSpace failed"):
        await svc.update_space(space)
