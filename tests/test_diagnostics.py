"""Tests for the diagnostics feature (conditions helpers, SystemDiagnostics, CLI)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from quilt_hp.cli import main as cli_main
from quilt_hp.client import QuiltClient
from quilt_hp.models.diagnostics import (
    IndoorUnitDiagnostics,
    OutdoorUnitDiagnostics,
    SystemDiagnostics,
)
from quilt_hp.models.enums import (
    ComfortSettingOverride,
    ConditionState,
    FanSpeed,
    HVACMode,
    HVACState,
    LouverMode,
    OccupancyMode,
    SafetyHeatingMode,
)
from quilt_hp.models.indoor_unit import (
    IndoorUnit,
    IndoorUnitConditions,
    IndoorUnitControls,
    IndoorUnitPerformanceData,
    IndoorUnitPerformanceMetrics,
    IndoorUnitSettings,
    IndoorUnitState,
)
from quilt_hp.models.outdoor_unit import OutdoorUnit
from quilt_hp.models.space import Space, SpaceControls, SpaceSettings, SpaceState
from quilt_hp.models.system import SystemSnapshot

runner = CliRunner()


def _conditions(**active: bool) -> IndoorUnitConditions:
    """Build conditions with the named fields ACTIVE(2), the rest INACTIVE(1)."""
    values = dict.fromkeys(IndoorUnitConditions.FIELD_NAMES, int(ConditionState.INACTIVE))
    for name, is_active in active.items():
        values[name] = int(ConditionState.ACTIVE if is_active else ConditionState.INACTIVE)
    return IndoorUnitConditions(**values)


def _make_idu(
    idu_id: str = "idu-1",
    space_id: str = "space-1",
    *,
    online: bool = True,
    conditions: IndoorUnitConditions | None = None,
    with_perf: bool = True,
) -> IndoorUnit:
    perf = (
        IndoorUnitPerformanceData(
            measurement_interval_s=5.0,
            energy_measurement_j=11.0,
            hvac_mode=HVACMode.FAN,
            hvac_state=HVACState.STANDBY,
            actual_fan_speed_rpm=0.0,
            outlet_temperature_c=21.0,
            inlet_temperature_c=21.4,
            inlet_humidity_pct=65.0,
            coil_temperature_c=24.0,
            gas_pipe_temperature_c=16.0,
            liquid_pipe_temperature_c=16.0,
        )
        if with_perf
        else None
    )
    metrics = (
        IndoorUnitPerformanceMetrics(
            capacity_w=0.0,
            coefficient_of_performance=0.0,
            hvac_power_w=2.26,
            led_power_w=0.0,
            hvac_mode=HVACMode.FAN,
            hvac_state=HVACState.STANDBY,
        )
        if with_perf
        else None
    )
    return IndoorUnit(
        id=idu_id,
        system_id="sys-1",
        space_id=space_id,
        outdoor_unit_id=None,
        hardware_id="hw-1",
        qsm_id=None,
        settings=IndoorUnitSettings(
            name="IDU One",
            description="",
            light_brightness_default_percent=0.0,
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
            led_brightness=0.0,
            led_animation=1,
        ),
        state=IndoorUnitState(
            hvac_mode=HVACMode.FAN,
            hvac_state=HVACState.STANDBY,
            ambient_temperature_c=21.0,
            ambient_humidity_percent=65.0,
            fan_speed_rpm=0.0,
            fan_speed_setpoint_rpm=0.0,
            presence_detection_level=0.0,
            updated_at=datetime.now(tz=UTC) if online else None,
        ),
        hvac_inputs=None,
        conditions=conditions,
        performance_data=perf,
        performance_metrics=metrics,
        presence=None,
        occupancy=None,
        commands=None,
    )


def _make_odu(odu_id: str = "odu-1") -> OutdoorUnit:
    return OutdoorUnit(
        id=odu_id,
        system_id="sys-1",
        space_id="space-1",
        hvac_state=HVACState.UNSPECIFIED,
        model_sku="N/A",
        serial_number="QU1-TEST",
        firmware_version="46",
        firmware_update_info_id=None,
        performance_data=None,
    )


def _make_space() -> Space:
    return Space(
        id="space-1",
        system_id="sys-1",
        name="Living Room",
        parent_space_id="root",
        settings=SpaceSettings(
            name="Living Room",
            timezone="UTC",
            occupancy_mode=OccupancyMode.ENABLED,
            occupied_timeout_s=180.0,
            unoccupied_timeout_s=1200.0,
            safety_heating=SafetyHeatingMode.ENABLED,
        ),
        controls=SpaceControls(
            hvac_mode=HVACMode.FAN,
            temperature_setpoint_c=21.0,
            cooling_setpoint_c=24.0,
            heating_setpoint_c=20.0,
            comfort_setting_id="",
            comfort_setting_override=ComfortSettingOverride.NONE,
        ),
        state=SpaceState(
            ambient_temperature_c=21.0,
            hvac_state=HVACState.STANDBY,
            setpoint_c=21.0,
            comfort_setting_id="",
        ),
    )


def _snapshot(idus: list[IndoorUnit], odus: list[OutdoorUnit]) -> SystemSnapshot:
    return SystemSnapshot(
        spaces=[_make_space()],
        indoor_units=idus,
        outdoor_units=odus,
        controllers=[],
        quilt_smart_modules=[],
        comfort_settings=[],
        schedule_weeks=[],
        schedule_days=[],
        remote_sensors=[],
        controller_remote_sensors=[],
        software_update_infos=[],
        locations=[],
        timezone="UTC",
    )


# --- condition helpers -------------------------------------------------------


def test_conditions_active_and_states() -> None:
    conds = _conditions(defrost_cycle=True, outdoor_unit_communication_error=True)
    assert conds.any_active is True
    assert set(conds.active) == {"defrost_cycle", "outdoor_unit_communication_error"}
    states = conds.states()
    assert len(states) == len(IndoorUnitConditions.FIELD_NAMES)
    assert states["defrost_cycle"] is ConditionState.ACTIVE
    assert states["mode_conflict"] is ConditionState.INACTIVE


def test_conditions_healthy() -> None:
    conds = _conditions()
    assert conds.any_active is False
    assert conds.active == []


def test_conditions_tolerates_unknown_wire_value() -> None:
    # proto3 preserves unknown enum integers; states() must not raise.
    conds = _conditions()
    conds.defrost_cycle = 99  # value outside ConditionState
    states = conds.states()
    assert states["defrost_cycle"] is ConditionState.UNSPECIFIED
    # the unknown value is not ACTIVE, so it does not register as a fault
    assert conds.active == []
    assert conds.any_active is False


# --- IndoorUnitDiagnostics ---------------------------------------------------


def test_idu_diagnostics_from_populated_unit() -> None:
    idu = _make_idu(conditions=_conditions(oil_return=True))
    diag = IndoorUnitDiagnostics.from_indoor_unit(idu, space_name="Living Room")
    assert diag.indoor_unit_id == "idu-1"
    assert diag.name == "IDU One"
    assert diag.space_name == "Living Room"
    assert diag.online is True
    assert diag.active_faults == ["oil_return"]
    assert diag.coil_temperature_c == 24.0
    assert diag.gas_pipe_temperature_c == 16.0
    assert diag.hvac_power_w == 2.26


def test_idu_diagnostics_handles_absent_submessages() -> None:
    idu = _make_idu(conditions=None, with_perf=False, online=False)
    diag = IndoorUnitDiagnostics.from_indoor_unit(idu)
    assert diag.online is False
    assert diag.active_faults == []
    assert diag.conditions == {}
    assert diag.coil_temperature_c is None
    assert diag.hvac_power_w is None
    # name falls back to space_name when the IDU has one; here settings.name is set
    assert diag.name == "IDU One"


def test_idu_diagnostics_name_falls_back_to_space() -> None:
    idu = _make_idu()
    idu.settings.name = ""
    diag = IndoorUnitDiagnostics.from_indoor_unit(idu, space_name="Kitchen")
    assert diag.name == "Kitchen"


# --- SystemDiagnostics aggregate --------------------------------------------


def test_system_diagnostics_aggregate() -> None:
    healthy = IndoorUnitDiagnostics.from_indoor_unit(_make_idu("a", conditions=_conditions()))
    faulted = IndoorUnitDiagnostics.from_indoor_unit(
        _make_idu("b", conditions=_conditions(modbus_communication_error=True))
    )
    diag = SystemDiagnostics(
        indoor_units=[healthy, faulted],
        outdoor_units=[OutdoorUnitDiagnostics.from_outdoor_unit(_make_odu())],
    )
    assert diag.has_faults is True
    assert diag.active_faults == [("b", "modbus_communication_error")]
    assert diag.outdoor_units[0].raw_sensors_available is False


def test_system_diagnostics_no_faults() -> None:
    diag = SystemDiagnostics(
        indoor_units=[IndoorUnitDiagnostics.from_indoor_unit(_make_idu(conditions=_conditions()))],
        outdoor_units=[],
    )
    assert diag.has_faults is False
    assert diag.active_faults == []


# --- SystemSnapshot.diagnostics() -------------------------------------------


def test_snapshot_diagnostics_resolves_space_name() -> None:
    snap = _snapshot(
        idus=[_make_idu(conditions=_conditions(defrost_cycle=True))],
        odus=[_make_odu()],
    )
    diag = snap.diagnostics()
    assert len(diag.indoor_units) == 1
    assert diag.indoor_units[0].space_name == "Living Room"
    assert diag.active_faults == [("idu-1", "defrost_cycle")]
    assert diag.outdoor_units[0].outdoor_unit_id == "odu-1"


# --- QuiltClient.get_diagnostics --------------------------------------------


async def test_client_get_diagnostics_delegates() -> None:
    client = QuiltClient("user@example.com")
    snap = _snapshot(idus=[_make_idu()], odus=[_make_odu()])
    with patch.object(client, "get_snapshot", AsyncMock(return_value=snap)):
        diag = await client.get_diagnostics()
    assert isinstance(diag, SystemDiagnostics)
    assert len(diag.indoor_units) == 1


# --- CLI ---------------------------------------------------------------------


class _FakeDiagClient:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    async def __aenter__(self) -> _FakeDiagClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def login(self) -> None:
        return None

    async def get_snapshot(self) -> SystemSnapshot:
        return _snapshot(
            idus=[
                _make_idu("a", conditions=_conditions()),
                _make_idu("b", conditions=_conditions(outdoor_unit_communication_error=True)),
            ],
            odus=[_make_odu()],
        )


def test_cli_diagnostics_summary_and_faults_only_and_json() -> None:
    with (
        patch.object(cli_main, "_resolve", return_value=("user@example.com", "Home")),
        patch.object(cli_main, "QuiltClient", _FakeDiagClient),
    ):
        summary = runner.invoke(cli_main.app, ["diagnostics"])
        faults_only = runner.invoke(cli_main.app, ["diagnostics", "--faults-only"])
        as_json = runner.invoke(cli_main.app, ["diagnostics", "--output", "json"])

    assert summary.exit_code == 0
    assert "1 active fault(s)" in summary.stdout
    assert "outdoor_unit_communication_error" in summary.stdout
    assert "cloud-withheld" in summary.stdout

    assert faults_only.exit_code == 0
    assert "outdoor_unit_communication_error" in faults_only.stdout

    assert as_json.exit_code == 0
    assert '"outdoor_unit_communication_error"' in as_json.stdout
