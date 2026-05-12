"""Shared test fixtures."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from quilt_hp.models.enums import (
    ComfortSettingOverride,
    ComfortSettingType,
    HVACMode,
    HVACState,
    OccupancyMode,
    SafetyHeatingMode,
)
from quilt_hp.models.space import Space, SpaceControls, SpaceSettings, SpaceState
from quilt_hp.models.system import Location, SystemSnapshot


def _ns(**kwargs: object) -> SimpleNamespace:
    """Build a SimpleNamespace recursively from keyword args."""
    return SimpleNamespace(**kwargs)


def _make_header(object_id: str = "obj-1", system_id: str = "sys-1") -> SimpleNamespace:
    return _ns(object_id=object_id, system_id=system_id)


@pytest.fixture
def fake_space() -> Space:
    return Space(
        id="space-1",
        system_id="sys-1",
        name="Living Room",
        parent_space_id="root-1",
        settings=SpaceSettings(
            name="Living Room",
            timezone="UTC",
            occupancy_mode=OccupancyMode.ENABLED,
            occupied_timeout_s=180.0,
            unoccupied_timeout_s=1200.0,
            safety_heating=SafetyHeatingMode.ENABLED,
        ),
        controls=SpaceControls(
            hvac_mode=HVACMode.HEAT,
            temperature_setpoint_c=20.0,
            cooling_setpoint_c=24.0,
            heating_setpoint_c=20.0,
            comfort_setting_id="comfort-1",
            comfort_setting_override=ComfortSettingOverride.NONE,
        ),
        state=SpaceState(
            ambient_temperature_c=21.0,
            hvac_state=HVACState.HEAT,
            setpoint_c=20.0,
            comfort_setting_id="comfort-1",
        ),
        active_comfort_setting_type=ComfortSettingType.ACTIVE,
    )


@pytest.fixture
def fake_snapshot(fake_space: Space) -> SystemSnapshot:
    return SystemSnapshot(
        spaces=[fake_space],
        indoor_units=[],
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
                name="Home",
                system_id="sys-1",
                timezone="UTC",
                schedule_paused=False,
            )
        ],
        timezone="UTC",
    )
