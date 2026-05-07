"""Tests for QuiltClient snapshot caching and mutation helpers."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from quilt_hp.client import QuiltClient
from quilt_hp.models.enums import (
    ComfortSettingOverride,
    FanSpeed,
    HVACMode,
    HVACState,
    LouverMode,
    OccupancyMode,
    SafetyHeatingMode,
)
from quilt_hp.models.indoor_unit import (
    IndoorUnit,
    IndoorUnitControls,
    IndoorUnitSettings,
    IndoorUnitState,
)
from quilt_hp.models.schedule import ScheduleDay, ScheduleEvent, ScheduleWeek, ScheduleWeekDay
from quilt_hp.models.space import (
    Space,
    SpaceControls,
    SpaceSettings,
    SpaceState,
)
from quilt_hp.models.system import Location, SystemSnapshot

# ─── helpers ────────────────────────────────────────────────────────────────


def _make_space(space_id: str = "space-1", name: str = "Room") -> Space:
    return Space(
        id=space_id,
        system_id="sys-1",
        name=name,
        parent_space_id="root-1",
        settings=SpaceSettings(
            name="Test Room",
            timezone="America/Los_Angeles",
            occupancy_mode=OccupancyMode.DISABLED,
            occupied_timeout_s=180.0,
            unoccupied_timeout_s=1200.0,
            safety_heating=SafetyHeatingMode.ENABLED,
        ),
        controls=SpaceControls(
            hvac_mode=HVACMode.HEAT,
            temperature_setpoint_c=21.0,
            cooling_setpoint_c=26.0,
            heating_setpoint_c=21.0,
            comfort_setting_id="",
            comfort_setting_override=ComfortSettingOverride.NONE,
        ),
        state=SpaceState(
            ambient_temperature_c=22.0,
            hvac_state=HVACState.HEAT,
            setpoint_c=21.0,
            comfort_setting_id="",
        ),
    )


def _make_idu(idu_id: str = "idu-1", space_id: str = "space-1") -> IndoorUnit:
    return IndoorUnit(
        id=idu_id,
        system_id="sys-1",
        space_id=space_id,
        outdoor_unit_id=None,
        hardware_id="hw-1",
        qsm_id=None,
        settings=IndoorUnitSettings(
            name="Test IDU",
            description="",
            light_brightness_default_percent=0.8,
            presence_fence_left_m=0.0,
            presence_fence_right_m=0.0,
            presence_fence_forward_m=0.0,
            radar_sensor_distance_from_floor_m=0.0,
        ),
        controls=IndoorUnitControls(
            fan_speed=FanSpeed.AUTO,
            louver_mode=LouverMode.SWEEP,
            louver_fixed_position=0.0,
            led_color_code=0,
            led_brightness=0.8,
            led_animation=1,
        ),
        state=IndoorUnitState(
            hvac_mode=HVACMode.HEAT,
            hvac_state=HVACState.HEAT,
            ambient_temperature_c=22.0,
            ambient_humidity_percent=45.0,
            fan_speed_rpm=850.0,
            fan_speed_setpoint_rpm=900.0,
            presence_detection_level=0.3,
        ),
        hvac_inputs=None,
        conditions=None,
        performance_data=None,
        performance_metrics=None,
        presence=None,
        occupancy=None,
        commands=None,
    )


def _make_snapshot(
    spaces: list[Space] | None = None, idus: list[IndoorUnit] | None = None
) -> SystemSnapshot:
    return SystemSnapshot(
        spaces=spaces or [_make_space()],
        indoor_units=idus or [_make_idu()],
        outdoor_units=[],
        controllers=[],
        quilt_smart_modules=[],
        comfort_settings=[],
        schedule_weeks=[],
        schedule_days=[],
        remote_sensors=[],
        controller_remote_sensors=[],
        software_update_infos=[],
        locations=[
            Location(
                id="loc-1",
                name="",
                system_id="sys-1",
                timezone="America/LA",
                schedule_paused=False,
            )
        ],
        timezone="America/LA",
    )


def _make_client(ttl: float = 0) -> tuple[QuiltClient, AsyncMock]:
    """Create a QuiltClient with mocked auth + service layer."""
    client = QuiltClient("test@test.com", snapshot_ttl_s=ttl)
    client._token = "test-token"
    client._system_id = "sys-1"
    mock_hds = MagicMock()
    client._hds = mock_hds
    client._sysinfo = MagicMock()
    client._channel = MagicMock()
    return client, mock_hds


# ─── snapshot caching ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_no_cache_calls_service_each_time() -> None:
    """With ttl=0, every get_snapshot call hits the service."""
    client, mock_hds = _make_client(ttl=0)
    snap = _make_snapshot()
    mock_hds.get_system = AsyncMock(return_value=snap)

    await client.get_snapshot()
    await client.get_snapshot()

    assert mock_hds.get_system.call_count == 2


@pytest.mark.asyncio
async def test_snapshot_cache_hit() -> None:
    """Within TTL, get_snapshot returns cached result."""
    client, mock_hds = _make_client(ttl=60)
    snap = _make_snapshot()
    mock_hds.get_system = AsyncMock(return_value=snap)

    result1 = await client.get_snapshot()
    result2 = await client.get_snapshot()

    # Only one network call
    assert mock_hds.get_system.call_count == 1
    assert result1 is result2


@pytest.mark.asyncio
async def test_snapshot_cache_miss_after_ttl() -> None:
    """After TTL expires, get_snapshot fetches fresh."""
    client, mock_hds = _make_client(ttl=0.01)  # 10ms TTL
    snap = _make_snapshot()
    mock_hds.get_system = AsyncMock(return_value=snap)

    await client.get_snapshot()
    time.sleep(0.05)  # wait for TTL to expire
    await client.get_snapshot()

    assert mock_hds.get_system.call_count == 2


@pytest.mark.asyncio
async def test_invalidate_snapshot_forces_refresh() -> None:
    """invalidate_snapshot() causes next call to re-fetch."""
    client, mock_hds = _make_client(ttl=60)
    snap = _make_snapshot()
    mock_hds.get_system = AsyncMock(return_value=snap)

    await client.get_snapshot()
    client.invalidate_snapshot()
    await client.get_snapshot()

    assert mock_hds.get_system.call_count == 2


@pytest.mark.asyncio
async def test_snapshot_explicit_system_id_bypasses_cache() -> None:
    """Explicit system_id arg bypasses the default-system cache."""
    client, mock_hds = _make_client(ttl=60)
    snap = _make_snapshot()
    mock_hds.get_system = AsyncMock(return_value=snap)

    # Populate cache for default system
    await client.get_snapshot()
    # Explicit different system_id should still hit the network
    await client.get_snapshot(system_id="other-sys")

    assert mock_hds.get_system.call_count == 2


# ─── set_space: object vs string ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_space_with_object_no_snapshot_fetch() -> None:
    """Passing a Space object directly skips snapshot fetch."""
    client, mock_hds = _make_client()
    space = _make_space()
    updated_space = _make_space()
    mock_hds.update_space = AsyncMock(return_value=updated_space)

    result = await client.set_space(space, mode=HVACMode.COOL)

    # No snapshot fetch needed
    assert mock_hds.get_system.call_count == 0
    mock_hds.update_space.assert_called_once()
    assert result is updated_space


@pytest.mark.asyncio
async def test_set_space_with_string_fetches_snapshot() -> None:
    """Passing a space ID string triggers a snapshot fetch to resolve it."""
    client, mock_hds = _make_client()
    space = _make_space("space-1")
    snap = _make_snapshot(spaces=[space])
    mock_hds.get_system = AsyncMock(return_value=snap)
    mock_hds.update_space = AsyncMock(return_value=space)

    await client.set_space("space-1", mode=HVACMode.COOL)

    assert mock_hds.get_system.call_count == 1
    mock_hds.update_space.assert_called_once()


@pytest.mark.asyncio
async def test_set_space_unknown_id_raises() -> None:
    """Unknown space ID raises QuiltError."""
    from quilt_hp.exceptions import QuiltError

    client, mock_hds = _make_client()
    snap = _make_snapshot(spaces=[_make_space("space-1")])
    mock_hds.get_system = AsyncMock(return_value=snap)

    with pytest.raises(QuiltError, match="not found"):
        await client.set_space("space-999", mode=HVACMode.COOL)


# ─── set_indoor_unit: object vs string ──────────────────────────────────────


@pytest.mark.asyncio
async def test_set_idu_with_object_no_snapshot_fetch() -> None:
    client, mock_hds = _make_client()
    idu = _make_idu()
    updated = _make_idu()
    mock_hds.update_indoor_unit = AsyncMock(return_value=updated)

    result = await client.set_indoor_unit(idu, fan_speed=FanSpeed.HIGH)

    assert mock_hds.get_system.call_count == 0
    assert result is updated


@pytest.mark.asyncio
async def test_set_idu_with_string_fetches_snapshot() -> None:
    client, mock_hds = _make_client()
    idu = _make_idu("idu-1")
    snap = _make_snapshot(idus=[idu])
    mock_hds.get_system = AsyncMock(return_value=snap)
    mock_hds.update_indoor_unit = AsyncMock(return_value=idu)

    await client.set_indoor_unit("idu-1", fan_speed=FanSpeed.LOW)

    assert mock_hds.get_system.call_count == 1


@pytest.mark.asyncio
async def test_set_idu_unknown_id_raises() -> None:
    from quilt_hp.exceptions import QuiltError

    client, mock_hds = _make_client()
    snap = _make_snapshot(idus=[_make_idu("idu-1")])
    mock_hds.get_system = AsyncMock(return_value=snap)

    with pytest.raises(QuiltError, match="not found"):
        await client.set_indoor_unit("idu-999", fan_speed=FanSpeed.HIGH)


# ─── set_schedule_execution ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_schedule_execution_uses_primary_location() -> None:
    client, mock_hds = _make_client(ttl=60)
    snap = _make_snapshot()
    mock_hds.get_system = AsyncMock(return_value=snap)
    mock_hds.update_location_schedule_execution = AsyncMock()

    await client.set_schedule_execution(paused=True)

    mock_hds.update_location_schedule_execution.assert_called_once_with(
        location_id="loc-1",
        system_id="sys-1",
        paused=True,
    )


@pytest.mark.asyncio
async def test_set_schedule_execution_no_location_raises() -> None:
    from quilt_hp.exceptions import QuiltError

    client, mock_hds = _make_client()
    snap = _make_snapshot()
    snap.locations = []
    snap.timezone = None
    mock_hds.get_system = AsyncMock(return_value=snap)

    with pytest.raises(QuiltError, match="No location"):
        await client.set_schedule_execution(paused=True)


@pytest.mark.asyncio
async def test_create_schedule_day_uses_domain_events() -> None:
    client, mock_hds = _make_client()
    mock_hds.create_schedule_day = AsyncMock(
        return_value=ScheduleDay(id="day-1", name="Weekday", space_id="space-1", events=[])
    )
    events = [
        ScheduleEvent(
            start_s=28800,
            comfort_setting_id="cs-1",
            hvac_mode=HVACMode.HEAT.value,
            heating_setpoint_c=21.0,
            cooling_setpoint_c=26.0,
            precondition=False,
        )
    ]

    await client.create_schedule_day("space-1", "Weekday", events)

    mock_hds.create_schedule_day.assert_called_once_with(
        system_id="sys-1",
        space_id="space-1",
        name="Weekday",
        events=events,
    )


@pytest.mark.asyncio
async def test_update_schedule_week_uses_domain_weekdays() -> None:
    client, mock_hds = _make_client()
    mock_hds.update_schedule_week = AsyncMock(
        return_value=ScheduleWeek(id="week-1", space_id="space-1", days=[])
    )
    days = [ScheduleWeekDay(weekday=1, day_id="day-1")]

    await client.update_schedule_week("week-1", "space-1", days)

    mock_hds.update_schedule_week.assert_called_once_with(
        schedule_week_id="week-1",
        system_id="sys-1",
        space_id="space-1",
        days=days,
    )


# ─── get_system_id caching ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_system_id_caches() -> None:
    from quilt_hp.models.system import SystemInfo

    client, mock_hds = _make_client()
    client._system_id = None  # reset cache

    mock_sysinfo = MagicMock()
    mock_sysinfo.list_systems = AsyncMock(
        return_value=[SystemInfo(id="sys-1", name="Home", timezone="UTC")]
    )
    client._sysinfo = mock_sysinfo

    sid1 = await client.get_system_id()
    sid2 = await client.get_system_id()

    assert sid1 == sid2 == "sys-1"
    # Second call should use cache — only one list_systems call
    assert mock_sysinfo.list_systems.call_count == 1


@pytest.mark.asyncio
async def test_get_system_id_home_filter() -> None:
    from quilt_hp.models.system import SystemInfo

    client, _ = _make_client()
    client._system_id = None
    client._home = "vacation"

    mock_sysinfo = MagicMock()
    mock_sysinfo.list_systems = AsyncMock(
        return_value=[
            SystemInfo(id="sys-1", name="Home", timezone="UTC"),
            SystemInfo(id="sys-2", name="Vacation Cabin", timezone="UTC"),
        ]
    )
    client._sysinfo = mock_sysinfo

    sid = await client.get_system_id()
    assert sid == "sys-2"
