"""Tests for model from_proto constructors using mocked proto objects."""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime
from types import SimpleNamespace

from quilt_hp.const import (
    EMPTY_COMFORT_SETTING_ID_SENTINEL,
    STANDBY_COOL_SENTINEL_C,
    STANDBY_HEAT_SENTINEL_C,
    UNKNOWN_SCHEDULE_SORT_ORDER_SENTINEL,
)
from quilt_hp.models.comfort import ComfortSetting
from quilt_hp.models.controller import Controller
from quilt_hp.models.energy import EnergyBucket, SpaceEnergyMetrics
from quilt_hp.models.enums import (
    ComfortSettingType,
    FanSpeed,
    HVACMode,
    HVACState,
    LouverMode,
    OccupancyMode,
    RemoteSensorControlMode,
    SafetyHeatingMode,
)
from quilt_hp.models.indoor_unit import IndoorUnit
from quilt_hp.models.qsm import QuiltSmartModule
from quilt_hp.models.schedule import ScheduleDay, ScheduleEvent, ScheduleWeek
from quilt_hp.models.sensor import RemoteSensor
from quilt_hp.models.space import Space, SpaceControls, SpaceSettings
from quilt_hp.models.system import Location, SystemSnapshot

# ─── helpers ────────────────────────────────────────────────────────────────


def _ns(**kwargs: object) -> SimpleNamespace:
    """Build a SimpleNamespace recursively from keyword args."""
    return SimpleNamespace(**kwargs)


def _make_header(object_id: str = "obj-1", system_id: str = "sys-1") -> SimpleNamespace:
    return _ns(object_id=object_id, system_id=system_id)


# ─── Space ──────────────────────────────────────────────────────────────────


def _make_space_proto(
    space_id: str = "space-1",
    name: str = "Living Room",
    parent_space_id: str = "root-1",
    hvac_mode: int = HVACMode.HEAT,
    hvac_state: int = HVACState.HEAT,
    ambient_c: float = 22.5,
) -> SimpleNamespace:
    return _ns(
        header=_make_header(space_id),
        settings=_ns(
            name=name,
            timezone="America/Los_Angeles",
            occupancy=OccupancyMode.ENABLED,
            occupied_timeout_s=180.0,
            unoccupied_timeout_s=1200.0,
            safety_heating=SafetyHeatingMode.ENABLED,
            hvac_controller_type=0,
        ),
        relationships=_ns(parent_space_id=parent_space_id),
        controls=_ns(
            hvac_mode=hvac_mode,
            temperature_setpoint_c=21.0,
            cooling_temperature_setpoint_c=26.0,
            heating_temperature_setpoint_c=21.0,
            comfort_setting_id_string="cs-1",
            comfort_setting_override=0,
            boost_mode=0,
        ),
        state=_ns(
            updated_ts=object(),  # truthy → state fields are valid
            ambient_temperature_c=ambient_c,
            hvac_state=hvac_state,
            setpoint_temperature_c=21.0,
            comfort_setting_id="cs-1",
        ),
    )


def test_space_from_proto_basic() -> None:
    proto = _make_space_proto()
    space = Space.from_proto(proto)
    assert space.id == "space-1"
    assert space.name == "Living Room"
    assert space.parent_space_id == "root-1"
    assert space.is_room is True


def test_space_from_proto_enums() -> None:
    proto = _make_space_proto(hvac_mode=HVACMode.COOL, hvac_state=HVACState.COOL)
    space = Space.from_proto(proto)
    assert isinstance(space.controls.hvac_mode, HVACMode)
    assert space.controls.hvac_mode == HVACMode.COOL
    assert isinstance(space.state.hvac_state, HVACState)
    assert space.state.hvac_state == HVACState.COOL


def test_space_from_proto_settings() -> None:
    proto = _make_space_proto()
    space = Space.from_proto(proto)
    assert isinstance(space.settings, SpaceSettings)
    assert space.settings.name == "Living Room"
    assert space.settings.timezone == "America/Los_Angeles"
    assert space.settings.occupancy_mode == OccupancyMode.ENABLED
    assert space.settings.safety_heating == SafetyHeatingMode.ENABLED
    assert space.settings.occupied_timeout_s == 180.0
    assert space.settings.unoccupied_timeout_s == 1200.0


def test_space_is_room_false_for_root() -> None:
    proto = _make_space_proto(parent_space_id="")
    space = Space.from_proto(proto)
    assert space.is_room is False


def test_space_is_off_when_controls_standby() -> None:
    """is_off (no comfort setting type): STANDBY ctrl+state → OFF."""
    from quilt_hp.models.enums import HVACMode, HVACState

    proto = _make_space_proto(hvac_mode=HVACMode.STANDBY, hvac_state=HVACState.STANDBY)
    space = Space.from_proto(proto)
    assert space.is_off is True
    assert space.is_away is False


def test_space_is_away_via_comfort_setting_type() -> None:
    """is_away (with cs type): STANDBY ctrl+state but cs type=AWAY → AWAY."""
    from quilt_hp.models.enums import ComfortSettingType, HVACMode, HVACState

    proto = _make_space_proto(hvac_mode=HVACMode.STANDBY, hvac_state=HVACState.STANDBY)
    space = Space.from_proto(proto)
    space.active_comfort_setting_type = ComfortSettingType.AWAY
    assert space.is_away is True
    assert space.is_off is False


def test_space_is_off_via_comfort_setting_type_standby() -> None:
    """is_off (with cs type): STANDBY ctrl and cs type=STANDBY → OFF."""
    from quilt_hp.models.enums import ComfortSettingType, HVACMode, HVACState

    proto = _make_space_proto(hvac_mode=HVACMode.STANDBY, hvac_state=HVACState.STANDBY)
    space = Space.from_proto(proto)
    space.active_comfort_setting_type = ComfortSettingType.STANDBY
    assert space.is_off is True
    assert space.is_away is False


def test_space_is_away_fallback_when_controls_active_but_state_standby() -> None:
    """is_away fallback (no cs type): active ctrl mode but STANDBY state."""
    from quilt_hp.models.enums import HVACMode, HVACState

    proto = _make_space_proto(hvac_mode=HVACMode.HEAT, hvac_state=HVACState.STANDBY)
    space = Space.from_proto(proto)
    assert space.is_away is True
    assert space.is_off is False


def test_space_not_away_when_actively_heating() -> None:
    """is_away is False when state matches controls (room heating)."""
    from quilt_hp.models.enums import HVACMode, HVACState

    proto = _make_space_proto(hvac_mode=HVACMode.HEAT, hvac_state=HVACState.HEAT)
    space = Space.from_proto(proto)
    assert space.is_away is False
    assert space.is_off is False


def test_space_is_off_not_away_when_both_standby_no_cs() -> None:
    """No cs type: STANDBY ctrl+state → OFF not AWAY."""
    from quilt_hp.models.enums import HVACMode, HVACState

    proto = _make_space_proto(hvac_mode=HVACMode.STANDBY, hvac_state=HVACState.STANDBY)
    space = Space.from_proto(proto)
    assert space.is_off is True
    assert space.is_away is False


def test_space_ambient_temperature_f() -> None:
    # Note: 0.0 is proto3 default (missing), so we use non-zero values here.
    proto = _make_space_proto(ambient_c=20.0)
    space = Space.from_proto(proto)
    assert space.ambient_temperature_f == pytest.approx(68.0)

    proto2 = _make_space_proto(ambient_c=100.0)
    space2 = Space.from_proto(proto2)
    assert space2.ambient_temperature_f == pytest.approx(212.0)


def test_space_ambient_none() -> None:
    # When state.updated_ts is falsy (no server state data), temps are None.
    proto = _make_space_proto(ambient_c=22.0)
    proto.state.updated_ts = None  # simulate empty state sub-message
    space = Space.from_proto(proto)
    assert space.state.ambient_temperature_c is None
    assert space.ambient_temperature_f is None


def test_space_ambient_zero_celsius() -> None:
    # 0.0°C is valid when updated_ts is truthy; must not be coerced to None.
    proto = _make_space_proto(ambient_c=0.0)
    space = Space.from_proto(proto)
    assert space.state.ambient_temperature_c == 0.0
    assert space.ambient_temperature_f == pytest.approx(32.0)


# ─── SpaceControls.display_setpoint ─────────────────────────────────────────


def test_display_setpoint_heat() -> None:
    c = SpaceControls(
        hvac_mode=HVACMode.HEAT,
        temperature_setpoint_c=21.0,
        cooling_setpoint_c=26.0,
        heating_setpoint_c=21.0,
        comfort_setting_id="",
        comfort_setting_override=0,
    )
    assert c.display_setpoint == "21.0°C"


def test_display_setpoint_cool() -> None:
    c = SpaceControls(
        hvac_mode=HVACMode.COOL,
        temperature_setpoint_c=0.0,
        cooling_setpoint_c=24.5,
        heating_setpoint_c=0.0,
        comfort_setting_id="",
        comfort_setting_override=0,
    )
    assert c.display_setpoint == "24.5°C"


def test_display_setpoint_auto() -> None:
    c = SpaceControls(
        hvac_mode=HVACMode.AUTO,
        temperature_setpoint_c=0.0,
        cooling_setpoint_c=26.0,
        heating_setpoint_c=21.0,
        comfort_setting_id="",
        comfort_setting_override=0,
    )
    assert c.display_setpoint == "21.0°C–26.0°C"


def test_display_setpoint_standby() -> None:
    c = SpaceControls(
        hvac_mode=HVACMode.STANDBY,
        temperature_setpoint_c=0.0,
        cooling_setpoint_c=0.0,
        heating_setpoint_c=0.0,
        comfort_setting_id="",
        comfort_setting_override=0,
    )
    assert c.display_setpoint == "--"


def test_space_controls_comfort_setting_id_sentinel() -> None:
    c = SpaceControls(
        hvac_mode=HVACMode.COOL,
        temperature_setpoint_c=24.0,
        cooling_setpoint_c=24.0,
        heating_setpoint_c=20.0,
        comfort_setting_id=EMPTY_COMFORT_SETTING_ID_SENTINEL,
        comfort_setting_override=0,
    )
    assert c.has_linked_comfort_setting is False
    assert c.comfort_setting_id_or_none is None


def test_space_controls_standby_sentinel_pair() -> None:
    c = SpaceControls(
        hvac_mode=HVACMode.STANDBY,
        temperature_setpoint_c=STANDBY_COOL_SENTINEL_C,
        cooling_setpoint_c=STANDBY_COOL_SENTINEL_C,
        heating_setpoint_c=STANDBY_HEAT_SENTINEL_C,
        comfort_setting_id=EMPTY_COMFORT_SETTING_ID_SENTINEL,
        comfort_setting_override=0,
    )
    assert c.has_standby_sentinel_setpoints is True


def test_space_state_missing_temperature_nan() -> None:
    proto = _make_space_proto()
    proto.state.ambient_temperature_c = math.nan
    space = Space.from_proto(proto)
    assert space.state.has_missing_ambient_temperature is True


# ─── IndoorUnit ─────────────────────────────────────────────────────────────


def _make_idu_proto(
    idu_id: str = "idu-1",
    space_id: str = "space-1",
    hvac_mode: int = HVACMode.HEAT,
    hvac_state: int = HVACState.HEAT,
) -> SimpleNamespace:
    return _ns(
        header=_make_header(idu_id),
        relationships=_ns(
            space_id=space_id,
            outdoor_unit_id="odu-1",
            hardware_id="hw-1",
            quilt_smart_module_id="qsm-1",
            firmware_update_info_id="",
        ),
        settings=_ns(
            name="Test Room IDU",
            description="",
            light_brightness_default_percent=0.8,
            presence_fence_left_m=0.0,
            presence_fence_right_m=0.0,
            presence_fence_forward_m=0.0,
            radar_sensor_distance_from_floor_m=0.0,
        ),
        controls=_ns(
            fan_speed_mode=1,  # AUTO
            fan_speed_percent=0.0,
            louver_mode=LouverMode.SWEEP,
            louver_fixed_position=0.0,
            led_color_code=0,
            led_color_brightness_percent=0.8,
            led_animation=1,
            led_state=0,  # LIGHT_STATE_UNSPECIFIED
        ),
        state=_ns(
            hvac_mode=hvac_mode,
            hvac_state=hvac_state,
            ambient_temperature_c=22.1,
            ambient_humidity_percent=45.0,
            fan_speed_rpm=850.0,
            fan_speed_setpoint_rpm=900.0,
            presence_detection_level=0.3,
            temperature_setpoint_c=21.0,
            light_brightness_percent=0.0,
            inlet_temperature_c=20.5,
            outlet_temperature_c=20.3,
            calculated_ambient_temperature_c=21.2,
            louver_angle_up_down_degrees=0.0,
            updated_ts=_ns(seconds=int(time.time())),  # recent → online
        ),
        hvac_inputs=_ns(
            updated_ts=None,  # absent by default
            external_ambient_temperature_c=0.0,
            ambient_temperature_source=0,
            temperature_setpoint_c=0.0,
            hvac_mode=0,
            hvac_state=0,
            hvac_controller_type=0,
        ),
        conditions=_ns(
            updated_ts=None,  # absent by default
            mode_conflict=0,
            anti_cold_wind=0,
            abnormal_outdoor_air_temperature=0,
            hvac_mode_switching_delay=0,
            defrost_cycle=0,
            safety_heating=0,
            oil_return=0,
            modbus_communication_error=0,
            coil_preheat=0,
            mode_conflict_avoidance=0,
            outdoor_unit_communication_error=0,
        ),
        performance_data=_ns(
            updated_ts=None,  # no timestamp → perf data absent
            coil_temperature_c=0.0,
            energy_measurement_j=0.0,
            measurement_interval_s=0.0,
            hvac_mode=0,
            hvac_state=0,
            actual_fan_speed_rpm=0.0,
            outlet_temperature_c=0.0,
            inlet_temperature_c=0.0,
            inlet_humidity_pct=0.0,
            gas_pipe_temperature_c=0.0,
            liquid_pipe_temperature_c=0.0,
        ),
        performance_metrics=_ns(
            updated_ts=None,
            capacity_w=0.0,
            coefficient_of_performance=0.0,
            hvac_power_w=0.0,
            led_power_w=0.0,
            hvac_mode=0,
            hvac_state=0,
            measurement_duration_s=0.0,
            energy_total_j=0.0,
            hvac_energy_j=0.0,
            led_energy_j=0.0,
        ),
        commands=_ns(
            updated_ts=None,  # absent by default
            fallback_control_command=0,
        ),
    )


def test_idu_from_proto_basic() -> None:
    proto = _make_idu_proto()
    idu = IndoorUnit.from_proto(proto)
    assert idu.id == "idu-1"
    assert idu.space_id == "space-1"
    assert idu.hardware_id == "hw-1"
    assert idu.qsm_id == "qsm-1"


def test_idu_from_proto_enums() -> None:
    proto = _make_idu_proto(hvac_mode=HVACMode.COOL, hvac_state=HVACState.COOL)
    idu = IndoorUnit.from_proto(proto)
    assert isinstance(idu.state.hvac_mode, HVACMode)
    assert idu.state.hvac_mode == HVACMode.COOL
    assert isinstance(idu.state.hvac_state, HVACState)
    assert idu.state.hvac_state == HVACState.COOL


def test_idu_fan_speed_auto() -> None:
    proto = _make_idu_proto()
    idu = IndoorUnit.from_proto(proto)
    # mode=1 (non-SETPOINT) → AUTO; raw wire value preserved
    assert idu.controls.fan_speed == FanSpeed.AUTO
    assert idu.controls.fan_speed_mode_raw == 1


def test_idu_fan_speed_mode_raw_absent() -> None:
    """fan_speed_mode=0 (proto3 default) stays as 0 in fan_speed_mode_raw.

    This is the controls-absent case.  FanSpeed.from_wire(0, 0.0) also returns
    AUTO, so only fan_speed_mode_raw distinguishes absent from explicit AUTO.
    """
    proto = _make_idu_proto()
    proto.controls.fan_speed_mode = 0
    idu = IndoorUnit.from_proto(proto)
    assert idu.controls.fan_speed == FanSpeed.AUTO  # same decoded value…
    assert idu.controls.fan_speed_mode_raw == 0  # …but raw correctly shows absent
    assert idu.controls.fan_speed_is_placeholder is True
    assert idu.controls.fan_speed_percent_raw == 0.0


def test_idu_louver_position_placeholder() -> None:
    proto = _make_idu_proto()
    proto.controls.louver_mode = LouverMode.AUTO
    proto.controls.louver_fixed_position = 0.0
    idu = IndoorUnit.from_proto(proto)
    assert idu.controls.louver_position_is_placeholder is True


def test_idu_led_light_on() -> None:
    proto = _make_idu_proto()
    proto.controls.led_color_code = 0xFF460064  # non-black color
    proto.controls.led_color_brightness_percent = 0.8
    idu = IndoorUnit.from_proto(proto)
    assert idu.is_online is True
    assert idu.controls.light_on is True


def test_idu_led_light_off() -> None:
    proto = _make_idu_proto()
    proto.controls.led_color_code = 0xFF460064
    proto.controls.led_color_brightness_percent = 0.0
    idu = IndoorUnit.from_proto(proto)
    assert idu.controls.light_on is False


def test_idu_led_black_color_code_always_off() -> None:
    """led_color_code=0 (black) means off regardless of brightness."""
    proto = _make_idu_proto()
    proto.controls.led_color_code = 0
    proto.controls.led_color_brightness_percent = 0.8
    idu = IndoorUnit.from_proto(proto)
    assert idu.controls.light_on is False


def test_idu_led_state_off_preserves_brightness() -> None:
    """led_state=OFF with non-zero brightness (scheduling path) must report OFF.

    When mobile_led_scheduling_enabled is on, the app calls
    withBrightnessAndState, preserving brightness (e.g. 0.29) and setting
    led_state=OFF. Brightness-
    based detection would wrongly report ON — led_state must take priority.
    """
    proto = _make_idu_proto()
    proto.controls.led_color_code = 0xFF460064
    proto.controls.led_color_brightness_percent = 0.29  # preserved, NOT zeroed
    proto.controls.led_state = 2  # LIGHT_STATE_OFF
    idu = IndoorUnit.from_proto(proto)
    assert idu.controls.light_on is False
    assert idu.led_on is False


def test_idu_led_state_on_explicit() -> None:
    """led_state=ON must report ON regardless of whether brightness > 0."""
    proto = _make_idu_proto()
    proto.controls.led_color_code = 0xFF460064
    proto.controls.led_color_brightness_percent = 0.42
    proto.controls.led_state = 1  # LIGHT_STATE_ON
    idu = IndoorUnit.from_proto(proto)
    assert idu.controls.light_on is True
    assert idu.led_on is True


def test_idu_offline_when_state_timestamp_absent() -> None:
    """IDU with no state updated_ts is considered offline."""
    proto = _make_idu_proto()
    proto.state.updated_ts = _ns(seconds=0)
    idu = IndoorUnit.from_proto(proto)
    assert idu.is_online is False
    # Offline IDU: effective properties gate out stale data
    assert idu.led_on is False
    assert idu.effective_occupancy_state is None


def test_idu_offline_when_state_timestamp_stale() -> None:
    """IDU with state updated > 5 min ago is considered offline."""
    proto = _make_idu_proto()
    stale_seconds = int(time.time()) - 400  # 6+ minutes ago
    proto.state.updated_ts = _ns(seconds=stale_seconds)
    idu = IndoorUnit.from_proto(proto)
    assert idu.is_online is False
    assert idu.led_on is False
    assert idu.effective_occupancy_state is None


def test_idu_no_perf_data() -> None:
    proto = _make_idu_proto()
    # performance_data.updated_ts=None → no perf data regardless of field values
    idu = IndoorUnit.from_proto(proto)
    assert idu.performance_data is None
    assert idu.performance_metrics is None


def test_idu_with_perf_data() -> None:
    proto = _make_idu_proto()
    proto.performance_data.updated_ts = object()  # truthy → data present
    proto.performance_data.coil_temperature_c = 8.5
    proto.performance_data.energy_measurement_j = 4500.0
    proto.performance_data.measurement_interval_s = 5.0
    proto.performance_metrics.updated_ts = object()  # truthy → metrics present
    proto.performance_metrics.capacity_w = 2800.0
    proto.performance_metrics.coefficient_of_performance = 3.5
    idu = IndoorUnit.from_proto(proto)
    assert idu.performance_data is not None
    assert idu.performance_data.coil_temperature_c == 8.5
    assert idu.performance_data.energy_kwh == pytest.approx(4500 / 3_600_000)
    assert idu.performance_metrics is not None
    assert idu.performance_metrics.coefficient_of_performance == 3.5


import pytest  # noqa: E402 — imported here to avoid top-level for the approx usage above

# ─── ComfortSetting ──────────────────────────────────────────────────────────


def _make_cs_proto(cs_id: str = "cs-1", space_id: str = "space-1") -> SimpleNamespace:
    return _ns(
        header=_make_header(cs_id),
        relationships=_ns(space_id=space_id),
        attributes=_ns(
            name="Active",
            type=ComfortSettingType.ACTIVE,
            hvac_mode=HVACMode.HEAT,
            heating_temperature_setpoint_c=21.0,
            cooling_temperature_setpoint_c=26.0,
            fan_speed_mode=1,
            fan_speed_percent=0.0,
            louver_mode=0,
            louver_fixed_position=0.0,
        ),
    )


def test_comfort_setting_from_proto() -> None:
    proto = _make_cs_proto()
    cs = ComfortSetting.from_proto(proto)
    assert cs.id == "cs-1"
    assert cs.name == "Active"
    assert cs.type == ComfortSettingType.ACTIVE
    assert cs.hvac_mode == HVACMode.HEAT
    assert cs.heating_setpoint_c == 21.0
    assert cs.fan_speed == FanSpeed.AUTO


def test_comfort_setting_standby_and_placeholder_sentinels() -> None:
    proto = _make_cs_proto("cs-standby")
    proto.attributes.type = ComfortSettingType.STANDBY
    proto.attributes.hvac_mode = HVACMode.STANDBY
    proto.attributes.heating_temperature_setpoint_c = STANDBY_HEAT_SENTINEL_C
    proto.attributes.cooling_temperature_setpoint_c = STANDBY_COOL_SENTINEL_C
    proto.attributes.louver_mode = LouverMode.AUTO
    proto.attributes.louver_fixed_position = 0.0
    cs = ComfortSetting.from_proto(proto)
    assert cs.has_standby_sentinel_setpoints is True
    assert cs.has_placeholder_setpoints is True
    assert cs.louver_position_is_placeholder is True


def test_comfort_setting_unspecified_zero_setpoint_sentinels() -> None:
    proto = _make_cs_proto("cs-unspecified")
    proto.attributes.type = ComfortSettingType.UNSPECIFIED
    proto.attributes.heating_temperature_setpoint_c = 0.0
    proto.attributes.cooling_temperature_setpoint_c = 0.0
    cs = ComfortSetting.from_proto(proto)
    assert cs.has_unspecified_setpoint_sentinels is True
    assert cs.has_placeholder_setpoints is True


# ─── Controller ─────────────────────────────────────────────────────────────


def test_controller_from_proto() -> None:
    proto = _ns(
        header=_make_header("ctrl-1"),
        relationships=_ns(
            space_id="space-1",
            software_update_info_id="",
            firmware_update_info_id="",
        ),
        settings=_ns(name="Living Room Dial"),
        state=_ns(
            updated_ts=_ns(seconds=int(__import__("time").time())),
            ambient_temperature_c=21.9,
            temperature_f3=34.0,
            temperature_f4=48.5,
            temperature_f5=21.0,
        ),
        hosted_wifi_state=_ns(
            ssid="MyNet",
            ipv4_address="192.168.1.42",
            signal_level_dbm=-63,
            frequency_mhz=5745,
            updated_ts=_ns(seconds=int(__import__("time").time())),
        ),
        ap_wifi_state=_ns(
            ssid="",
            ipv4_address="",
            signal_level_dbm=0,
            frequency_mhz=0,
            updated_ts=_ns(seconds=0),
        ),
        p2p_wifi_state=_ns(
            ssid="",
            ipv4_address="",
            signal_level_dbm=0,
            frequency_mhz=0,
            updated_ts=_ns(seconds=0),
        ),
        controls=_ns(remote_sensor_control_mode=0),
    )
    ctrl = Controller.from_proto(proto)
    assert ctrl.id == "ctrl-1"
    assert ctrl.name == "Living Room Dial"
    assert ctrl.raw_thermistor_c == 21.9  # raw on-chip reading (biased)
    assert ctrl.calibrated_ambient_c == 21.0  # corrected value sent to IDU
    assert ctrl.ambient_temperature_c == 21.0  # property: returns calibrated_ambient_c
    assert ctrl.pcb_temperature_a_c == 34.0
    assert ctrl.pcb_temperature_b_c == 48.5
    assert ctrl.wifi_ssid == "MyNet"
    assert ctrl.wifi_ip == "192.168.1.42"
    assert ctrl.wifi_signal_dbm == -63
    assert ctrl.wifi_band == "5 GHz"
    assert ctrl.wifi_last_seen is not None
    assert ctrl.is_online  # recent updated_ts → online


def test_controller_no_wifi() -> None:
    proto = _ns(
        header=_make_header("ctrl-2"),
        relationships=_ns(
            space_id="space-1",
            software_update_info_id="",
            firmware_update_info_id="",
        ),
        settings=_ns(name=""),
        state=_ns(
            updated_ts=_ns(seconds=0),
            ambient_temperature_c=20.0,
            temperature_f3=33.0,
            temperature_f4=47.0,
            temperature_f5=20.0,
        ),
        hosted_wifi_state=_ns(
            ssid="",
            ipv4_address="",
            signal_level_dbm=0,
            frequency_mhz=0,
            updated_ts=_ns(seconds=0),
        ),
        ap_wifi_state=_ns(
            ssid="",
            ipv4_address="",
            signal_level_dbm=0,
            frequency_mhz=0,
            updated_ts=_ns(seconds=0),
        ),
        p2p_wifi_state=_ns(
            ssid="",
            ipv4_address="",
            signal_level_dbm=0,
            frequency_mhz=0,
            updated_ts=_ns(seconds=0),
        ),
        controls=_ns(remote_sensor_control_mode=0),
    )
    ctrl = Controller.from_proto(proto)
    assert ctrl.wifi_ssid is None
    assert ctrl.wifi_ip is None
    assert ctrl.wifi_signal_dbm is None
    assert ctrl.wifi_band is None
    assert ctrl.wifi_last_seen is None
    assert ctrl.is_online  # seconds=0 → no timestamp → unknown → assume online (fail-open)


# ─── QuiltSmartModule ────────────────────────────────────────────────────────


def test_qsm_from_proto_with_sensors() -> None:
    proto = _ns(
        header=_make_header("qsm-1"),
        relationships=_ns(software_update_info_id="", firmware_update_info_id=""),
        controls=_ns(led_color_code=5, updated_ts=None),
        state=_ns(
            updated_ts=object(),  # truthy → sensors populated
            phase_detected_raw=0.12,
            target_detected_raw=0.87,
            als_illuminance_raw=320,
            als_ir_raw=45,
            als_both_raw=365,
            accel_x_raw=-12,
            accel_y_raw=4,
            accel_z_raw=990,
        ),
        hosted_wifi_state=_ns(ssid="HomeNet", ipv4_address="192.168.1.50", signal_level_dbm=-55),
        ap_wifi_state=_ns(ssid="", ipv4_address="", signal_level_dbm=0),
        p2p_wifi_state=_ns(ssid="", ipv4_address="", signal_level_dbm=0),
    )
    qsm = QuiltSmartModule.from_proto(proto)
    assert qsm.id == "qsm-1"
    assert qsm.led_color_code == 5
    assert qsm.hosted_wifi is not None
    assert qsm.hosted_wifi.ssid == "HomeNet"
    assert qsm.hosted_wifi.ip == "192.168.1.50"
    assert qsm.hosted_wifi.signal_dbm == -55
    assert qsm.hosted_wifi.connected is True
    assert qsm.ap_wifi is None  # empty ssid → None
    assert qsm.p2p_wifi is None
    assert qsm.sensors is not None
    assert qsm.sensors.phase_detected_raw == pytest.approx(0.12)
    assert qsm.sensors.target_detected_raw == pytest.approx(0.87)
    assert qsm.sensors.als_illuminance_raw == 320
    assert qsm.sensors.accel_z_raw == 990


def test_qsm_from_proto_no_sensors() -> None:
    proto = _ns(
        header=_make_header("qsm-2"),
        relationships=_ns(software_update_info_id="", firmware_update_info_id=""),
        controls=_ns(led_color_code=0, updated_ts=None),
        state=_ns(
            updated_ts=None,
            phase_detected_raw=0.0,
            target_detected_raw=0.0,
            als_illuminance_raw=0,
            als_ir_raw=0,
            als_both_raw=0,
            accel_x_raw=0,
            accel_y_raw=0,
            accel_z_raw=0,
        ),
        hosted_wifi_state=_ns(ssid="", ipv4_address="", signal_level_dbm=0),
        ap_wifi_state=_ns(ssid="", ipv4_address="", signal_level_dbm=0),
        p2p_wifi_state=_ns(ssid="", ipv4_address="", signal_level_dbm=0),
    )
    qsm = QuiltSmartModule.from_proto(proto)
    assert qsm.sensors is None
    assert qsm.hosted_wifi is None


# ─── RemoteSensor ────────────────────────────────────────────────────────────


def test_remote_sensor_from_proto() -> None:
    proto = _ns(
        header=_make_header("rs-1"),
        relationships=_ns(indoor_unit_id="idu-1"),
        attributes=_ns(mac="AA:BB:CC:DD:EE:FF"),
        controls=_ns(control_mode=2),  # APK: ENABLED=2 (DISABLED=1, UNSPECIFIED=0)
        state=_ns(
            ambient_temperature_c=21.5,
            humidity_percent=48.0,
            battery_level_percent=85.0,
            signal_level_dbm=-72,
        ),
    )
    rs = RemoteSensor.from_proto(proto)
    assert rs.id == "rs-1"
    assert rs.indoor_unit_id == "idu-1"
    assert rs.mac == "AA:BB:CC:DD:EE:FF"
    assert rs.ambient_temperature_c == 21.5
    assert rs.battery_level_percent == 85.0
    assert rs.control_mode == RemoteSensorControlMode.ENABLED


def test_remote_sensor_missing_fields() -> None:
    proto = _ns(
        header=_make_header("rs-2"),
        relationships=_ns(indoor_unit_id="idu-1"),
        attributes=_ns(mac=""),
        controls=_ns(control_mode=0),
        state=_ns(
            ambient_temperature_c=0.0,
            humidity_percent=0.0,
            battery_level_percent=0.0,
            signal_level_dbm=0,
        ),
    )
    rs = RemoteSensor.from_proto(proto)
    assert rs.mac is None
    assert rs.ambient_temperature_c is None
    assert rs.battery_level_percent is None
    assert rs.signal_level_dbm is None


# ─── ScheduleDay / ScheduleWeek ─────────────────────────────────────────────


def _make_event_proto(start_s: int, cs_id: str = "", hvac_mode: int = 0) -> SimpleNamespace:
    return _ns(
        start_s=start_s,
        comfort_setting_id=cs_id,
        hvac_mode=hvac_mode,
        heating_temperature_setpoint_c=21.0,
        cooling_temperature_setpoint_c=26.0,
        precondition=False,
    )


def test_schedule_day_from_proto_sorted() -> None:
    proto = _ns(
        header=_make_header("day-1"),
        attributes=_ns(name="Weekday"),
        relationships=_ns(space_id="space-1"),
        events=[
            _make_event_proto(64800),  # 18:00
            _make_event_proto(25200),  # 07:00
            _make_event_proto(32400),  # 09:00
        ],
    )
    day = ScheduleDay.from_proto(proto)
    assert day.id == "day-1"
    assert day.name == "Weekday"
    times = [ev.start_time for ev in day.events]
    assert times == ["07:00", "09:00", "18:00"]


def test_schedule_event_start_time() -> None:
    ev = ScheduleEvent(
        start_s=7 * 3600 + 30 * 60,  # 07:30
        comfort_setting_id="",
        hvac_mode=0,
        heating_setpoint_c=21.0,
        cooling_setpoint_c=26.0,
        precondition=False,
    )
    assert ev.start_time == "07:30"
    assert ev.has_linked_comfort_setting is False
    assert ev.comfort_setting_id_or_none is None


def test_schedule_week_from_proto() -> None:
    proto = _ns(
        header=_make_header("week-1"),
        relationships=_ns(space_id="space-1"),
        days=[
            _ns(weekday=3, day_id="day-wed"),
            _ns(weekday=1, day_id="day-mon"),
            _ns(weekday=5, day_id="day-fri"),
        ],
    )
    week = ScheduleWeek.from_proto(proto)
    assert week.id == "week-1"
    # Should be sorted by weekday
    assert [d.weekday for d in week.days] == [1, 3, 5]
    assert week.days[0].day_id == "day-mon"
    assert week.days[0].weekday_name == "Mon"


def test_schedule_weekday_unknown_sort_order_sentinel() -> None:
    proto = _ns(
        header=_make_header("week-unknown"),
        relationships=_ns(space_id="space-1"),
        days=[_ns(weekday=0, day_id="day-unknown")],
    )
    week = ScheduleWeek.from_proto(proto)
    assert week.days[0].weekday_sort_order == UNKNOWN_SCHEDULE_SORT_ORDER_SENTINEL


def test_energy_bucket_nan_sentinel_handling() -> None:
    now = datetime.now(UTC)
    bucket_ok = EnergyBucket(start_time=now, energy_kwh=1.25, status=1)
    bucket_nan = EnergyBucket(start_time=now, energy_kwh=math.nan, status=1)
    metrics = SpaceEnergyMetrics(space_id="space-1", buckets=[bucket_ok, bucket_nan])
    assert bucket_nan.has_missing_energy_value is True
    assert bucket_nan.energy_kwh_or_none is None
    assert metrics.missing_bucket_count == 1
    assert metrics.total_kwh == 1.25


# ─── Location ────────────────────────────────────────────────────────────────


def test_location_from_proto_running() -> None:
    from quilt_hp._proto import quilt_hds_pb2 as hds

    proto = _ns(
        header=_make_header("loc-1"),
        attributes=_ns(name="", tz_identifier="America/Los_Angeles"),
        controls=_ns(schedule_execution=hds.SCHEDULE_EXECUTION_RUNNING),
    )
    loc = Location.from_proto(proto)
    assert loc.id == "loc-1"
    assert loc.timezone == "America/Los_Angeles"
    assert loc.schedule_paused is False


def test_location_from_proto_paused() -> None:
    from quilt_hp._proto import quilt_hds_pb2 as hds

    proto = _ns(
        header=_make_header("loc-1"),
        attributes=_ns(name="", tz_identifier="America/New_York"),
        controls=_ns(schedule_execution=hds.SCHEDULE_EXECUTION_PAUSED),
    )
    loc = Location.from_proto(proto)
    assert loc.schedule_paused is True


# ─── SystemSnapshot ──────────────────────────────────────────────────────────


def test_system_snapshot_rooms() -> None:
    """rooms property returns only leaf spaces."""
    space_root = _make_space_proto("root", "Home", parent_space_id="")
    space_room = _make_space_proto("room-1", "Living Room", parent_space_id="root")

    from quilt_hp._proto import quilt_hds_pb2 as hds

    # Build a minimal snapshot proto
    proto = _ns(
        spaces=[space_root, space_room],
        indoor_units=[],
        outdoor_units=[],
        outdoor_unit_hardware=[],
        controller_hardware=[],
        controllers=[],
        quilt_smart_modules=[],
        comfort_settings=[],
        schedule_weeks=[],
        schedule_days=[],
        remote_sensors=[],
        controller_remote_sensors=[],
        software_update_infos=[],
        locations=[
            _ns(
                header=_make_header("loc-1"),
                attributes=_ns(name="", tz_identifier="America/Los_Angeles"),
                controls=_ns(schedule_execution=hds.SCHEDULE_EXECUTION_RUNNING),
            )
        ],
    )
    snap = SystemSnapshot.from_proto(proto)
    assert len(snap.spaces) == 2
    rooms = snap.rooms
    assert len(rooms) == 1
    assert rooms[0].name == "Living Room"


def test_system_snapshot_primary_location() -> None:
    from quilt_hp._proto import quilt_hds_pb2 as hds

    proto = _ns(
        spaces=[],
        indoor_units=[],
        outdoor_units=[],
        outdoor_unit_hardware=[],
        controller_hardware=[],
        controllers=[],
        quilt_smart_modules=[],
        comfort_settings=[],
        schedule_weeks=[],
        schedule_days=[],
        remote_sensors=[],
        controller_remote_sensors=[],
        software_update_infos=[],
        locations=[
            _ns(
                header=_make_header("loc-1"),
                attributes=_ns(name="", tz_identifier="Europe/London"),
                controls=_ns(schedule_execution=hds.SCHEDULE_EXECUTION_RUNNING),
            )
        ],
    )
    snap = SystemSnapshot.from_proto(proto)
    assert snap.primary_location is not None
    assert snap.primary_location.timezone == "Europe/London"
    assert snap.timezone == "Europe/London"


def test_system_snapshot_no_locations() -> None:
    proto = _ns(
        spaces=[],
        indoor_units=[],
        outdoor_units=[],
        outdoor_unit_hardware=[],
        controller_hardware=[],
        controllers=[],
        quilt_smart_modules=[],
        comfort_settings=[],
        schedule_weeks=[],
        schedule_days=[],
        remote_sensors=[],
        controller_remote_sensors=[],
        software_update_infos=[],
        locations=[],
    )
    snap = SystemSnapshot.from_proto(proto)
    assert snap.primary_location is None
    assert snap.timezone is None


def test_system_snapshot_space_by_name() -> None:
    from quilt_hp._proto import quilt_hds_pb2 as hds

    proto = _ns(
        spaces=[
            _make_space_proto("s1", "Living Room", parent_space_id="root"),
            _make_space_proto("s2", "Office", parent_space_id="root"),
        ],
        indoor_units=[],
        outdoor_units=[],
        outdoor_unit_hardware=[],
        controller_hardware=[],
        controllers=[],
        quilt_smart_modules=[],
        comfort_settings=[],
        schedule_weeks=[],
        schedule_days=[],
        remote_sensors=[],
        controller_remote_sensors=[],
        software_update_infos=[],
        locations=[
            _ns(
                header=_make_header("loc-1"),
                attributes=_ns(name="", tz_identifier="UTC"),
                controls=_ns(schedule_execution=hds.SCHEDULE_EXECUTION_RUNNING),
            )
        ],
    )
    snap = SystemSnapshot.from_proto(proto)
    assert snap.space_by_name("living room") is not None
    assert snap.space_by_name("living room").id == "s1"
    assert snap.space_by_name("OFFICE").id == "s2"
    assert snap.space_by_name("Bedroom") is None


# ─── SystemSnapshot.comfort_settings_for_space / away_comfort_setting ────────


def _make_snap_with_comfort_settings() -> SystemSnapshot:
    """Build a minimal snapshot with two spaces and comfort settings."""
    from quilt_hp._proto import quilt_hds_pb2 as hds

    def _cs_proto(
        cs_id: str,
        space_id: str,
        cs_type: ComfortSettingType,
        heat: float = 21.0,
        cool: float = 26.0,
    ) -> SimpleNamespace:
        return _ns(
            header=_make_header(cs_id, system_id="sys-1"),
            relationships=_ns(space_id=space_id),
            attributes=_ns(
                name=cs_type.name.title(),
                type=cs_type,
                hvac_mode=HVACMode.HEAT,
                heating_temperature_setpoint_c=heat,
                cooling_temperature_setpoint_c=cool,
                fan_speed_mode=1,
                fan_speed_percent=0.0,
                louver_mode=0,
                louver_fixed_position=0.0,
            ),
        )

    proto = _ns(
        spaces=[
            _make_space_proto("s1", "Living Room", parent_space_id="root"),
            _make_space_proto("s2", "Office", parent_space_id="root"),
        ],
        indoor_units=[],
        outdoor_units=[],
        outdoor_unit_hardware=[],
        controller_hardware=[],
        controllers=[],
        quilt_smart_modules=[],
        comfort_settings=[
            _cs_proto("cs-s1-active", "s1", ComfortSettingType.ACTIVE, heat=21.0, cool=26.0),
            _cs_proto("cs-s1-away", "s1", ComfortSettingType.AWAY, heat=15.5, cool=28.0),
            _cs_proto("cs-s1-sleep", "s1", ComfortSettingType.SLEEP, heat=19.0, cool=25.0),
            _cs_proto("cs-s2-active", "s2", ComfortSettingType.ACTIVE, heat=20.0, cool=25.0),
            _cs_proto("cs-s2-away", "s2", ComfortSettingType.AWAY, heat=14.0, cool=29.0),
        ],
        schedule_weeks=[],
        schedule_days=[],
        remote_sensors=[],
        controller_remote_sensors=[],
        software_update_infos=[],
        locations=[
            _ns(
                header=_make_header("loc-1"),
                attributes=_ns(name="Home", tz_identifier="America/Los_Angeles"),
                controls=_ns(schedule_execution=hds.SCHEDULE_EXECUTION_RUNNING),
            )
        ],
    )
    return SystemSnapshot.from_proto(proto)


def test_comfort_settings_for_space_by_object() -> None:
    snap = _make_snap_with_comfort_settings()
    s1 = snap.space_by_name("Living Room")
    assert s1 is not None
    cs_list = snap.comfort_settings_for_space(s1)
    assert len(cs_list) == 3
    assert all(cs.space_id == s1.id for cs in cs_list)


def test_comfort_settings_for_space_by_id() -> None:
    snap = _make_snap_with_comfort_settings()
    s2 = snap.space_by_name("Office")
    assert s2 is not None
    cs_list = snap.comfort_settings_for_space(s2.id)
    assert len(cs_list) == 2
    types = {cs.type for cs in cs_list}
    assert ComfortSettingType.ACTIVE in types
    assert ComfortSettingType.AWAY in types


def test_comfort_settings_for_space_unknown_id_returns_empty() -> None:
    snap = _make_snap_with_comfort_settings()
    assert snap.comfort_settings_for_space("no-such-id") == []


def test_away_comfort_setting_found() -> None:
    """away_comfort_setting returns the AWAY preset with correct setpoints."""
    snap = _make_snap_with_comfort_settings()
    s1 = snap.space_by_name("Living Room")
    assert s1 is not None

    away = snap.away_comfort_setting(s1)
    assert away is not None
    assert away.type == ComfortSettingType.AWAY
    assert away.heating_setpoint_c == pytest.approx(15.5)
    assert away.cooling_setpoint_c == pytest.approx(28.0)


def test_away_comfort_setting_by_space_id() -> None:
    snap = _make_snap_with_comfort_settings()
    s2 = snap.space_by_name("Office")
    assert s2 is not None

    away = snap.away_comfort_setting(s2.id)
    assert away is not None
    assert away.heating_setpoint_c == pytest.approx(14.0)
    assert away.cooling_setpoint_c == pytest.approx(29.0)


def test_away_comfort_setting_not_found_returns_none() -> None:
    snap = _make_snap_with_comfort_settings()
    assert snap.away_comfort_setting("no-such-space") is None


def test_away_setpoints_reflected_in_controls_when_away() -> None:
    """When a space is in away mode its controls reflect the away setpoints."""
    snap = _make_snap_with_comfort_settings()
    s1 = snap.space_by_name("Living Room")
    assert s1 is not None

    away = snap.away_comfort_setting(s1)
    assert away is not None

    # Simulate the server switching the space to AWAY: comfort_setting_id
    # points to the AWAY preset and the server copies its setpoints into controls.
    from dataclasses import replace

    away_controls = replace(
        s1.controls,
        comfort_setting_id=away.id,
        heating_setpoint_c=away.heating_setpoint_c,
        cooling_setpoint_c=away.cooling_setpoint_c,
    )
    s1_away = replace(
        s1, controls=away_controls, active_comfort_setting_type=ComfortSettingType.AWAY
    )

    assert s1_away.is_away is True
    assert s1_away.controls.heating_setpoint_c == pytest.approx(away.heating_setpoint_c)
    assert s1_away.controls.cooling_setpoint_c == pytest.approx(away.cooling_setpoint_c)
