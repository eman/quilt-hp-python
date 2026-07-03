"""Sparse-diff merge tests using REAL generated protobuf messages.

These tests reproduce exactly what ``NotifierStream._parse_event`` does:
build a real ``hds.*`` proto, ``SerializeToString`` → ``ParseFromString``,
convert with ``from_proto``, and merge with ``SystemSnapshot.apply_*``.

They exist because proto3 absence cannot be detected with truthiness or
``getattr`` defaults — only ``HasField`` works — and ``SimpleNamespace``
stubs cannot catch that class of bug.
"""

from __future__ import annotations

import pytest

from quilt_hp._proto import quilt_hds_pb2 as hds
from quilt_hp.models.controller import Controller
from quilt_hp.models.enums import HVACMode, HVACState, LightState, LouverMode
from quilt_hp.models.indoor_unit import IndoorUnit
from quilt_hp.models.outdoor_unit import OutdoorUnit
from quilt_hp.models.qsm import QuiltSmartModule
from quilt_hp.models.sensor import RemoteSensor
from quilt_hp.models.space import Space
from quilt_hp.models.system import SystemSnapshot


def _roundtrip[T](msg: T) -> T:
    """Serialize and re-parse a proto, as the notifier stream does."""
    fresh = type(msg)()
    fresh.ParseFromString(msg.SerializeToString())  # type: ignore[attr-defined]
    return fresh


def _empty_snapshot() -> SystemSnapshot:
    return SystemSnapshot(
        spaces=[],
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
        locations=[],
        timezone=None,
    )


def _full_space_proto() -> hds.Space:
    return hds.Space(
        header=hds.EntityMetadata(object_id="space-1", system_id="sys-1"),
        relationships=hds.SpaceRelationships(parent_space_id="root-1"),
        settings=hds.SpaceSettings(name="Living Room", timezone="UTC"),
        controls=hds.SpaceControls(
            hvac_mode=hds.HVAC_MODE_HEAT,
            temperature_setpoint_c=21.0,
            heating_temperature_setpoint_c=21.0,
            cooling_temperature_setpoint_c=26.0,
            comfort_setting_id_string="cs-1",
        ),
        state=hds.SpaceState(
            ambient_temperature_c=21.7,
            hvac_state=hds.HVAC_STATE_HEAT,
            setpoint_temperature_c=21.0,
        ),
    )


def test_real_proto_unset_submessages_parse_as_absent() -> None:
    """A diff with only controls set must not fabricate state/settings."""
    diff = _roundtrip(
        hds.Space(
            header=hds.EntityMetadata(object_id="space-1", system_id="sys-1"),
            controls=hds.SpaceControls(hvac_mode=hds.HVAC_MODE_COOL),
        )
    )
    space = Space.from_proto(diff)
    assert space.state.ambient_temperature_c is None
    assert space.state.setpoint_c is None
    assert space.settings.name == ""
    assert space.controls.hvac_mode == HVACMode.COOL


def test_apply_space_controls_only_diff_preserves_state_and_identity() -> None:
    snapshot = _empty_snapshot()
    full = Space.from_proto(_roundtrip(_full_space_proto()))
    snapshot.spaces.append(full)
    assert snapshot.rooms  # sanity: identity fields intact

    # Controls-only diff (user changed a setpoint)
    diff = _roundtrip(
        hds.Space(
            header=hds.EntityMetadata(object_id="space-1", system_id="sys-1"),
            controls=hds.SpaceControls(
                hvac_mode=hds.HVAC_MODE_HEAT,
                temperature_setpoint_c=22.0,
                heating_temperature_setpoint_c=22.0,
                cooling_temperature_setpoint_c=26.0,
                comfort_setting_id_string="cs-1",
            ),
        )
    )
    merged = snapshot.apply_space(Space.from_proto(diff))

    assert merged.controls.heating_setpoint_c == 22.0  # diff applied
    assert merged.state.ambient_temperature_c == pytest.approx(21.7)  # state preserved
    assert merged.state.hvac_state == HVACState.HEAT
    assert merged.name == "Living Room"  # settings preserved
    assert merged.parent_space_id == "root-1"  # relationships preserved
    assert merged.is_room is True
    assert snapshot.rooms  # room did not vanish


def test_apply_space_state_only_diff_preserves_controls() -> None:
    snapshot = _empty_snapshot()
    snapshot.spaces.append(Space.from_proto(_roundtrip(_full_space_proto())))

    diff = _roundtrip(
        hds.Space(
            header=hds.EntityMetadata(object_id="space-1", system_id="sys-1"),
            state=hds.SpaceState(
                ambient_temperature_c=23.4,
                hvac_state=hds.HVAC_STATE_STANDBY,
            ),
        )
    )
    merged = snapshot.apply_space(Space.from_proto(diff))

    assert merged.state.ambient_temperature_c == pytest.approx(23.4)  # diff applied
    assert merged.controls.hvac_mode == HVACMode.HEAT  # controls preserved
    assert merged.controls.heating_setpoint_c == 21.0
    assert merged.name == "Living Room"


def _full_idu_proto() -> hds.IndoorUnit:
    import time

    from google.protobuf.timestamp_pb2 import Timestamp

    ts = Timestamp()
    ts.FromSeconds(int(time.time()))
    return hds.IndoorUnit(
        header=hds.EntityMetadata(object_id="idu-1", system_id="sys-1"),
        relationships=hds.IndoorUnitRelationships(
            space_id="space-1",
            hardware_id="hw-1",
            quilt_smart_module_id="qsm-1",
            outdoor_unit_id="odu-1",
        ),
        settings=hds.IndoorUnitSettings(name="Living Room IDU"),
        controls=hds.IndoorUnitControls(
            fan_speed_mode=2,
            fan_speed_percent=0.6,
            louver_mode=hds.LOUVER_MODE_SWEEP,
            led_color_code=255,
            led_color_brightness_percent=0.8,
            led_state=hds.LIGHT_STATE_ON,
        ),
        state=hds.IndoorUnitState(
            updated_ts=ts,
            hvac_mode=hds.HVAC_MODE_HEAT,
            hvac_state=hds.HVAC_STATE_HEAT,
            ambient_temperature_c=21.5,
            fan_speed_rpm=800.0,
        ),
        hvac_inputs=hds.IndoorUnitHvacInputs(
            external_ambient_temperature_c=20.0,
            temperature_setpoint_c=21.0,
        ),
    )


def test_apply_idu_presence_only_diff_preserves_everything() -> None:
    """A presence-only diff must not clobber controls/state/links (C1+H3+H5)."""
    snapshot = _empty_snapshot()
    snapshot.indoor_units.append(IndoorUnit.from_proto(_roundtrip(_full_idu_proto())))

    diff = _roundtrip(
        hds.IndoorUnit(
            header=hds.EntityMetadata(object_id="idu-1", system_id="sys-1"),
            presence=hds.IndoorUnitPresenceState(sensor0_presence=1, sensor1_presence=2),
        )
    )
    merged = snapshot.apply_indoor_unit(IndoorUnit.from_proto(diff))

    assert merged.presence is not None  # diff applied
    # Controls preserved (no state present in the diff either — the old
    # merge logic required state to be present and failed here)
    assert merged.controls.led_color_code == 255
    assert merged.controls.led_state == LightState.ON
    assert merged.controls.louver_mode == LouverMode.SWEEP
    assert merged.controls.fan_speed_percent_raw == pytest.approx(0.6)
    # State, links, settings preserved
    assert merged.state.ambient_temperature_c == 21.5
    assert merged.state.updated_at is not None
    assert merged.space_id == "space-1"
    assert merged.hardware_id == "hw-1"
    assert merged.qsm_id == "qsm-1"
    assert merged.outdoor_unit_id == "odu-1"
    assert merged.settings.name == "Living Room IDU"
    # hvac_inputs preserved (all-zero fabricated object would be a bug)
    assert merged.hvac_inputs is not None
    assert merged.hvac_inputs.external_ambient_temperature_c == 20.0


def test_apply_controller_sparse_diff_preserves_temperatures() -> None:
    full = _roundtrip(
        hds.Controller(
            header=hds.EntityMetadata(object_id="ctrl-1", system_id="sys-1"),
            relationships=hds.ControllerRelationships(space_id="space-1"),
            settings=hds.ControllerSettings(name="Dial"),
            state=hds.ControllerState(
                ambient_temperature_c=24.0,
                temperature_f3=35.0,
                temperature_f4=45.0,
                temperature_f5=19.5,
            ),
        )
    )
    snapshot = _empty_snapshot()
    snapshot.controllers.append(Controller.from_proto(full))

    # Controls-only diff (remote sensor mode toggle)
    diff = _roundtrip(
        hds.Controller(
            header=hds.EntityMetadata(object_id="ctrl-1", system_id="sys-1"),
            controls=hds.ControllerControls(remote_sensor_control_mode=2),
        )
    )
    merged = snapshot.apply_controller(Controller.from_proto(diff))

    assert merged.calibrated_ambient_c == 19.5  # preserved, not zeroed
    assert merged.ambient_temperature_c == 19.5
    assert merged.raw_thermistor_c == 24.0
    assert merged.name == "Dial"
    assert merged.space_id == "space-1"


def test_apply_remote_sensor_controls_only_diff_preserves_readings() -> None:
    full = _roundtrip(
        hds.RemoteSensor(
            header=hds.EntityMetadata(object_id="rs-1", system_id="sys-1"),
            relationships=hds.RemoteSensorRelationships(indoor_unit_id="idu-1"),
            attributes=hds.RemoteSensorAttributes(mac="AA:BB"),
            state=hds.RemoteSensorState(
                ambient_temperature_c=22.5,
                humidity_percent=45.0,
                battery_level_percent=80.0,
            ),
        )
    )
    snapshot = _empty_snapshot()
    snapshot.remote_sensors.append(RemoteSensor.from_proto(full))

    diff = _roundtrip(
        hds.RemoteSensor(
            header=hds.EntityMetadata(object_id="rs-1", system_id="sys-1"),
            controls=hds.RemoteSensorControls(control_mode=2),
        )
    )
    merged = snapshot.apply_remote_sensor(RemoteSensor.from_proto(diff))

    assert merged.ambient_temperature_c == 22.5  # preserved, not zeroed
    assert merged.humidity_percent == 45.0
    assert merged.battery_level_percent == 80.0
    assert merged.indoor_unit_id == "idu-1"
    assert merged.mac == "AA:BB"


def test_apply_qsm_controls_only_diff_preserves_sensors() -> None:
    full = _roundtrip(
        hds.QuiltSmartModule(
            header=hds.EntityMetadata(object_id="qsm-1", system_id="sys-1"),
            controls=hds.QuiltSmartModuleControls(led_color_code=255),
            state=hds.QuiltSmartModuleState(
                phase_detected_raw=1.5,
                als_illuminance_raw=320,
            ),
        )
    )
    snapshot = _empty_snapshot()
    snapshot.quilt_smart_modules.append(QuiltSmartModule.from_proto(full))

    # State-only diff
    diff = _roundtrip(
        hds.QuiltSmartModule(
            header=hds.EntityMetadata(object_id="qsm-1", system_id="sys-1"),
            state=hds.QuiltSmartModuleState(phase_detected_raw=2.0),
        )
    )
    merged = snapshot.apply_qsm(QuiltSmartModule.from_proto(diff))
    assert merged.sensors is not None
    assert merged.sensors.phase_detected_raw == 2.0  # diff applied
    assert merged.led_color_code == 255  # controls preserved

    # Controls-only diff must preserve sensors
    diff2 = _roundtrip(
        hds.QuiltSmartModule(
            header=hds.EntityMetadata(object_id="qsm-1", system_id="sys-1"),
            controls=hds.QuiltSmartModuleControls(led_color_code=128),
        )
    )
    merged2 = snapshot.apply_qsm(QuiltSmartModule.from_proto(diff2))
    assert merged2.led_color_code == 128
    assert merged2.sensors is not None
    assert merged2.sensors.phase_detected_raw == 2.0


def test_apply_odu_state_only_diff_preserves_performance_data() -> None:
    full = _roundtrip(
        hds.OutdoorUnit(
            header=hds.EntityMetadata(object_id="odu-1", system_id="sys-1"),
            relationships=hds.OutdoorUnitRelationships(space_id="root-1"),
            state=hds.OutdoorUnitState(hvac_state=hds.HVAC_STATE_HEAT),
            performance_data=hds.OutdoorUnitPerformanceData(
                compressor_frequency_hz=42.0,
                ambient_temperature_c=5.0,
            ),
        )
    )
    snapshot = _empty_snapshot()
    snapshot.outdoor_units.append(OutdoorUnit.from_proto(full))

    diff = _roundtrip(
        hds.OutdoorUnit(
            header=hds.EntityMetadata(object_id="odu-1", system_id="sys-1"),
            state=hds.OutdoorUnitState(hvac_state=hds.HVAC_STATE_STANDBY),
        )
    )
    merged = snapshot.apply_outdoor_unit(OutdoorUnit.from_proto(diff))

    assert merged.hvac_state == HVACState.STANDBY  # diff applied
    assert merged.performance_data is not None  # telemetry preserved
    assert merged.performance_data.compressor_frequency_hz == 42.0
    assert merged.space_id == "root-1"


def test_full_snapshot_parse_from_real_protos_unaffected() -> None:
    """Snapshot-path values still parse correctly with presence gating."""
    space = Space.from_proto(_roundtrip(_full_space_proto()))
    assert space.state.ambient_temperature_c == pytest.approx(21.7)
    assert space.controls.hvac_mode == HVACMode.HEAT
    assert space.settings.timezone == "UTC"
    assert space.is_room is True

    idu = IndoorUnit.from_proto(_roundtrip(_full_idu_proto()))
    assert idu.state.ambient_temperature_c == 21.5
    assert idu.controls.led_color_code == 255
    assert idu.is_online is True
