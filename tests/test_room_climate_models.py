"""Space occupancy, ODU usage share, IDU climate state and IDU test state."""

from __future__ import annotations

import pytest

from quilt_hp._proto import quilt_hds_pb2 as hds
from quilt_hp.models import (
    IndoorUnit,
    IndoorUnitTestCoordination,
    IndoorUnitTestMode,
    IndoorUnitTestPhase,
    OccupancyState,
    Space,
    SystemSnapshot,
)
from quilt_hp.models.diagnostics import IndoorUnitDiagnostics

# ─── Space occupancy ─────────────────────────────────────────────────────────


def _space(occupancy: int | None = None, space_id: str = "space-1") -> hds.Space:
    proto = hds.Space(header=hds.EntityMetadata(object_id=space_id))
    proto.settings.name = "Dining Room"
    proto.relationships.parent_space_id = "home-1"
    if occupancy is not None:
        proto.occupancy.occupancy_state = occupancy  # type: ignore[assignment]
        proto.occupancy.updated_ts.FromSeconds(1_780_000_000)
    return proto


def test_space_occupancy_parsed() -> None:
    space = Space.from_proto(_space(hds.OCCUPANCY_DETECTED))
    assert space.occupancy is not None
    assert space.occupancy_state is OccupancyState.DETECTED
    assert space.occupancy.updated_at is not None


def test_space_without_occupancy_reports_none() -> None:
    space = Space.from_proto(_space())
    assert space.occupancy is None
    assert space.occupancy_state is None


def test_space_unknown_occupancy_value_is_unspecified() -> None:
    assert Space.from_proto(_space(99)).occupancy_state is OccupancyState.UNSPECIFIED


def test_apply_space_preserves_occupancy_when_diff_omits_it() -> None:
    system = hds.HomeDatastoreSystem()
    system.spaces.append(_space(hds.OCCUPANCY_DETECTED))
    snap = SystemSnapshot.from_proto(system)

    merged = snap.apply_space(Space.from_proto(_space()))
    assert merged.occupancy_state is OccupancyState.DETECTED

    merged = snap.apply_space(Space.from_proto(_space(hds.OCCUPANCY_UNDETECTED)))
    assert merged.occupancy_state is OccupancyState.UNDETECTED


# ─── Indoor unit: ODU share, climate, test state ─────────────────────────────


def _idu(
    *,
    odu_fraction: float | None = None,
    climate: hds.IndoorUnitClimateState | None = None,
    test: hds.IndoorUnitTestState | None = None,
    state_test_mode: int | None = None,
) -> hds.IndoorUnit:
    proto = hds.IndoorUnit(header=hds.EntityMetadata(object_id="idu-1"))
    proto.relationships.space_id = "space-1"
    if odu_fraction is not None:
        proto.performance_metrics.odu_usage_fraction = odu_fraction
        proto.performance_metrics.hvac_power_w = 2.26
    if climate is not None:
        proto.climate_state.CopyFrom(climate)
    if test is not None:
        proto.test_state.CopyFrom(test)
    if state_test_mode is not None:
        proto.state.test_mode = state_test_mode  # type: ignore[assignment]
        proto.state.ambient_temperature_c = 21.0
    return proto


def test_odu_usage_fraction_parsed() -> None:
    idu = IndoorUnit.from_proto(_idu(odu_fraction=0.5))
    assert idu.performance_metrics is not None
    assert idu.performance_metrics.odu_usage_fraction == pytest.approx(0.5)


def test_climate_state_and_dew_point() -> None:
    climate = hds.IndoorUnitClimateState(
        is_valid=True, inlet_dew_point_c=15.9, calculated_ambient_temperature_c=25.9
    )
    climate.updated_ts.FromSeconds(1_780_000_000)
    idu = IndoorUnit.from_proto(_idu(climate=climate))
    assert idu.climate is not None
    assert idu.climate.calculated_ambient_temperature_c == pytest.approx(25.9)
    assert idu.climate.updated_at is not None
    assert idu.dew_point_c == pytest.approx(15.9)


def test_dew_point_none_when_invalid_or_absent() -> None:
    invalid = hds.IndoorUnitClimateState(is_valid=False, inlet_dew_point_c=15.9)
    assert IndoorUnit.from_proto(_idu(climate=invalid)).dew_point_c is None
    assert IndoorUnit.from_proto(_idu()).dew_point_c is None


def test_test_state_inactive_is_not_under_test() -> None:
    test = hds.IndoorUnitTestState(
        test_mode=hds.INDOOR_UNIT_TEST_MODE_INACTIVE,
        test_coordination=hds.INDOOR_UNIT_TEST_COORDINATION_NONE,
        test_phase=hds.INDOOR_UNIT_TEST_PHASE_NONE,
    )
    idu = IndoorUnit.from_proto(
        _idu(test=test, state_test_mode=hds.INDOOR_UNIT_TEST_MODE_INACTIVE)
    )
    assert idu.test_state is not None
    assert idu.test_state.test_mode is IndoorUnitTestMode.INACTIVE
    assert idu.state.test_mode is IndoorUnitTestMode.INACTIVE
    assert idu.is_under_test is False


def test_commissioning_is_under_test() -> None:
    test = hds.IndoorUnitTestState(
        test_mode=hds.INDOOR_UNIT_TEST_MODE_COMMISSIONING,
        test_coordination=hds.INDOOR_UNIT_TEST_COORDINATION_EXCLUSIVE,
        test_phase=hds.INDOOR_UNIT_TEST_PHASE_COOLING,
    )
    idu = IndoorUnit.from_proto(_idu(test=test))
    assert idu.is_under_test is True
    assert idu.test_state is not None
    assert idu.test_state.test_coordination is IndoorUnitTestCoordination.EXCLUSIVE
    assert idu.test_state.test_phase is IndoorUnitTestPhase.COOLING


def test_unknown_test_values_fall_back_to_unspecified() -> None:
    test = hds.IndoorUnitTestState(test_mode=77, test_coordination=78, test_phase=79)  # type: ignore[arg-type]
    idu = IndoorUnit.from_proto(_idu(test=test))
    assert idu.test_state is not None
    assert idu.test_state.test_mode is IndoorUnitTestMode.UNSPECIFIED
    assert idu.test_state.test_coordination is IndoorUnitTestCoordination.UNSPECIFIED
    assert idu.test_state.test_phase is IndoorUnitTestPhase.UNSPECIFIED
    assert idu.is_under_test is False


def test_apply_indoor_unit_preserves_climate_and_test_state() -> None:
    climate = hds.IndoorUnitClimateState(is_valid=True, inlet_dew_point_c=15.9)
    test = hds.IndoorUnitTestState(test_mode=hds.INDOOR_UNIT_TEST_MODE_INACTIVE)
    system = hds.HomeDatastoreSystem()
    system.indoor_units.append(_idu(climate=climate, test=test))
    snap = SystemSnapshot.from_proto(system)

    merged = snap.apply_indoor_unit(IndoorUnit.from_proto(_idu()))
    assert merged.dew_point_c == pytest.approx(15.9)
    assert merged.test_state is not None


def test_diagnostics_include_new_fields() -> None:
    test = hds.IndoorUnitTestState(
        test_mode=hds.INDOOR_UNIT_TEST_MODE_HEALTH_CHECK,
        test_phase=hds.INDOOR_UNIT_TEST_PHASE_SELF_TEST,
        test_coordination=hds.INDOOR_UNIT_TEST_COORDINATION_PARALLEL,
    )
    climate = hds.IndoorUnitClimateState(is_valid=True, inlet_dew_point_c=16.1)
    diag = IndoorUnitDiagnostics.from_indoor_unit(
        IndoorUnit.from_proto(_idu(odu_fraction=0.5, climate=climate, test=test)), "Dining Room"
    )
    assert diag.inlet_dew_point_c == pytest.approx(16.1)
    assert diag.odu_usage_fraction == pytest.approx(0.5)
    assert diag.under_test is True
    assert diag.test == {"mode": "HEALTH_CHECK", "coordination": "PARALLEL", "phase": "SELF_TEST"}


def test_state_test_mode_alone_marks_unit_under_test() -> None:
    """Only IndoorUnitState.test_mode reported (no test_state sub-message)."""
    idu = IndoorUnit.from_proto(_idu(state_test_mode=hds.INDOOR_UNIT_TEST_MODE_HEALTH_CHECK))
    assert idu.test_state is None
    assert idu.effective_test_mode is IndoorUnitTestMode.HEALTH_CHECK
    assert idu.is_under_test is True

    diag = IndoorUnitDiagnostics.from_indoor_unit(idu, "Dining Room")
    assert diag.under_test is True
    assert diag.test == {"mode": "HEALTH_CHECK"}


def test_effective_test_mode_prefers_test_state() -> None:
    test = hds.IndoorUnitTestState(test_mode=hds.INDOOR_UNIT_TEST_MODE_COMMISSIONING)
    idu = IndoorUnit.from_proto(
        _idu(test=test, state_test_mode=hds.INDOOR_UNIT_TEST_MODE_INACTIVE)
    )
    assert idu.effective_test_mode is IndoorUnitTestMode.COMMISSIONING
    assert idu.is_under_test is True


def test_effective_test_mode_falls_back_when_test_state_unspecified() -> None:
    test = hds.IndoorUnitTestState()  # present but test_mode UNSPECIFIED
    idu = IndoorUnit.from_proto(_idu(test=test, state_test_mode=hds.INDOOR_UNIT_TEST_MODE_STANDBY))
    assert idu.effective_test_mode is IndoorUnitTestMode.STANDBY
    assert idu.is_under_test is True


def test_newer_state_test_mode_beats_stale_test_state() -> None:
    """A merged snapshot can keep an old test_state while state carries a newer mode."""
    test = hds.IndoorUnitTestState(test_mode=hds.INDOOR_UNIT_TEST_MODE_HEALTH_CHECK)
    test.updated_ts.FromSeconds(1_000)
    proto = _idu(test=test, state_test_mode=hds.INDOOR_UNIT_TEST_MODE_INACTIVE)
    proto.state.updated_ts.FromSeconds(2_000)
    idu = IndoorUnit.from_proto(proto)
    assert idu.effective_test_mode is IndoorUnitTestMode.INACTIVE
    assert idu.is_under_test is False

    proto.state.updated_ts.FromSeconds(500)  # now test_state is newer
    assert IndoorUnit.from_proto(proto).effective_test_mode is IndoorUnitTestMode.HEALTH_CHECK


def test_indoor_unit_state_positional_fields_unchanged() -> None:
    """New IndoorUnitState fields are appended, so positional construction keeps working."""
    from dataclasses import fields
    from datetime import UTC, datetime

    from quilt_hp.models import HVACMode, HVACState, IndoorUnitState

    names = [f.name for f in fields(IndoorUnitState)]
    assert names.index("updated_at") < names.index("test_mode")
    when = datetime(2026, 10, 5, tzinfo=UTC)
    state = IndoorUnitState(
        HVACMode.COOL,
        HVACState.COOL,
        21.0,
        45.0,
        0.0,
        0.0,
        0.0,
        22.0,
        0.5,
        21.0,
        20.0,
        21.0,
        0.0,
        when,
    )
    assert state.updated_at == when
    assert state.test_mode is IndoorUnitTestMode.UNSPECIFIED


def test_diagnostics_zero_odu_share_is_not_reported() -> None:
    """0.0 is the proto3 default, so diagnostics report None rather than a 0% share."""
    diag = IndoorUnitDiagnostics.from_indoor_unit(
        IndoorUnit.from_proto(_idu(odu_fraction=0.0)), "Dining Room"
    )
    assert diag.hvac_power_w == pytest.approx(2.26)  # performance_metrics present
    assert diag.odu_usage_fraction is None
