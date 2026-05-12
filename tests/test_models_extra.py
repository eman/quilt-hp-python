"""Additional model conversion coverage."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from quilt_hp.models.comfort import ComfortSetting
from quilt_hp.models.controller import Controller
from quilt_hp.models.energy import EnergyBucket, SpaceEnergyMetrics
from quilt_hp.models.enums import (
    ComfortSettingType,
    FanSpeed,
    HVACMode,
    LouverMode,
    RemoteSensorControlMode,
)
from quilt_hp.models.outdoor_unit import OutdoorUnit
from quilt_hp.models.sensor import ControllerRemoteSensor, RemoteSensor
from quilt_hp.models.software_update import SoftwareUpdateInfo
from tests.conftest import _make_header, _ns


@pytest.mark.parametrize(
    ("state", "status", "current_version", "target_version", "current", "total", "unit"),
    [
        (0, 0, "", "", 0.0, 0.0, 0),
        (2, 3, "1.0.0", "1.1.0", 45.0, 100.0, 1),
    ],
)
def test_software_update_info_from_proto(
    state: int,
    status: int,
    current_version: str,
    target_version: str,
    current: float,
    total: float,
    unit: int,
) -> None:
    proto = _ns(
        header=_make_header("update-1"),
        attributes=_ns(
            state=state,
            status=status,
            current_version=current_version,
            target_version=target_version,
            current_progress=current,
            total_progress=total,
            progress_unit=unit,
        ),
    )

    info = SoftwareUpdateInfo.from_proto(proto)

    assert info.id == "update-1"
    assert info.state == state
    assert info.status == status
    assert info.current_version == current_version
    assert info.target_version == target_version
    assert info.current_progress == current
    assert info.total_progress == total
    assert info.progress_unit == unit


def test_energy_bucket_is_valid_and_total_kwh() -> None:
    now = datetime.now(UTC)
    valid_bucket = EnergyBucket(start_time=now, energy_kwh=1.25, status=1)
    zero_bucket = EnergyBucket(start_time=now, energy_kwh=0.0, status=1)
    invalid_bucket = EnergyBucket(start_time=now, energy_kwh=math.nan, status=2)
    metrics = SpaceEnergyMetrics(
        space_id="space-1",
        buckets=[valid_bucket, zero_bucket, invalid_bucket],
    )

    assert valid_bucket.is_valid is True
    assert zero_bucket.is_valid is True
    assert invalid_bucket.is_valid is False
    assert metrics.total_kwh == pytest.approx(1.25)


@pytest.mark.parametrize(
    ("comfort_type", "hvac_mode", "fan_mode", "fan_percent", "louver_mode", "expected_fan"),
    [
        (ComfortSettingType.ACTIVE, HVACMode.HEAT, 1, 0.0, LouverMode.AUTO, FanSpeed.AUTO),
        (ComfortSettingType.AWAY, HVACMode.COOL, 2, 0.60, LouverMode.SWEEP, FanSpeed.MEDIUM),
        (ComfortSettingType.CUSTOM, HVACMode.AUTO, 2, 0.80, LouverMode.FIXED, FanSpeed.HIGH),
    ],
)
def test_comfort_setting_from_proto_different_types(
    comfort_type: ComfortSettingType,
    hvac_mode: HVACMode,
    fan_mode: int,
    fan_percent: float,
    louver_mode: LouverMode,
    expected_fan: FanSpeed,
) -> None:
    proto = _ns(
        header=_make_header("comfort-1"),
        relationships=_ns(space_id="space-1"),
        attributes=_ns(
            name=comfort_type.name.title(),
            type=comfort_type,
            hvac_mode=hvac_mode,
            heating_temperature_setpoint_c=20.0,
            cooling_temperature_setpoint_c=25.0,
            fan_speed_mode=fan_mode,
            fan_speed_percent=fan_percent,
            louver_mode=louver_mode,
            louver_fixed_position=0.4,
        ),
    )

    setting = ComfortSetting.from_proto(proto)

    assert setting.id == "comfort-1"
    assert setting.space_id == "space-1"
    assert setting.type == comfort_type
    assert setting.hvac_mode == hvac_mode
    assert setting.fan_speed == expected_fan
    assert setting.louver_mode == louver_mode


def test_controller_from_proto_includes_wifi_remote_sensor_and_hardware() -> None:
    now = int(datetime.now(tz=UTC).timestamp())
    proto = _ns(
        header=_make_header("ctrl-1"),
        relationships=_ns(
            space_id="space-1",
            hardware_id="controllers/HW-1",
            software_update_info_id="sw-1",
            firmware_update_info_id="fw-1",
        ),
        settings=_ns(name="Hall Dial"),
        state=_ns(
            updated_ts=_ns(seconds=now),
            ambient_temperature_c=22.1,
            temperature_f3=34.5,
            temperature_f4=48.0,
            temperature_f5=21.7,
        ),
        hosted_wifi_state=_ns(
            ssid="HomeNet",
            ipv4_address="192.168.1.10",
            signal_level_dbm=-58,
            frequency_mhz=2437,
            updated_ts=_ns(seconds=now),
        ),
        ap_wifi_state=_ns(
            ssid="Dial-AP",
            ipv4_address="192.168.4.1",
            signal_level_dbm=-30,
            updated_ts=_ns(seconds=now),
        ),
        p2p_wifi_state=_ns(
            ssid="Dial-Direct",
            ipv4_address="169.254.1.1",
            signal_level_dbm=-40,
            updated_ts=_ns(seconds=now),
        ),
        controls=_ns(remote_sensor_control_mode=RemoteSensorControlMode.ENABLED),
    )
    hw_map = {
        "hw-1": _ns(
            attributes=_ns(
                serial_number="SN123",
                model_sku="DIAL-V1",
                firmware_version="9.9.9",
            )
        )
    }

    controller = Controller.from_proto(proto, hw_map=hw_map)

    assert controller.name == "Hall Dial"
    assert controller.wifi_ssid == "HomeNet"
    assert controller.wifi_ip == "192.168.1.10"
    assert controller.wifi_signal_dbm == -58
    assert controller.wifi_band == "2.4 GHz"
    assert controller.ap_wifi is not None
    assert controller.ap_wifi.ssid == "Dial-AP"
    assert controller.p2p_wifi is not None
    assert controller.p2p_wifi.ssid == "Dial-Direct"
    assert controller.remote_sensor_mode == RemoteSensorControlMode.ENABLED
    assert controller.software_update_info_id == "sw-1"
    assert controller.firmware_update_info_id == "fw-1"
    assert controller.serial_number == "SN123"
    assert controller.model_sku == "DIAL-V1"
    assert controller.firmware_version == "9.9.9"
    assert controller.state_updated_at is not None
    assert controller.wifi_last_seen is not None


@pytest.mark.parametrize(
    ("ambient", "compressor", "energy", "high_pressure", "low_pressure"),
    [
        (19.5, 55.0, 7200.0, 2450.0, 780.0),
        (0.0, 0.0, 0.0, 0.0, 0.0),
    ],
)
def test_outdoor_unit_from_proto_with_performance_data(
    ambient: float,
    compressor: float,
    energy: float,
    high_pressure: float,
    low_pressure: float,
) -> None:
    proto = _ns(
        header=_make_header("odu-1"),
        relationships=_ns(
            space_id="space-1",
            hardware_id="outdoor/HW-ODU-1",
            firmware_update_info_id="fw-odu-1",
        ),
        state=_ns(hvac_state=HVACMode.COOL),
        performance_data=_ns(
            measurement_interval_s=5.0,
            energy_measurement_j=energy,
            compressor_frequency_hz=compressor,
            ambient_temperature_c=ambient,
            coil_temperature_c=8.0,
            exhaust_temperature_c=42.0,
            high_pressure_kpa=high_pressure,
            low_pressure_kpa=low_pressure,
        ),
    )
    hw_map = {
        "hw-odu-1": _ns(
            attributes=_ns(
                model_sku="ODU-24K",
                serial_number="ODU123",
                firmware_version="3.2.1",
            )
        )
    }

    outdoor_unit = OutdoorUnit.from_proto(proto, hw_map=hw_map)

    assert outdoor_unit.model_sku == "ODU-24K"
    assert outdoor_unit.serial_number == "ODU123"
    assert outdoor_unit.firmware_version == "3.2.1"
    assert outdoor_unit.firmware_update_info_id == "fw-odu-1"
    assert outdoor_unit.performance_data is not None
    assert outdoor_unit.performance_data.ambient_temperature_c == ambient
    assert outdoor_unit.performance_data.compressor_frequency_hz == compressor
    assert outdoor_unit.performance_data.energy_measurement_j == energy
    assert outdoor_unit.performance_data.high_pressure_kpa == high_pressure
    assert outdoor_unit.performance_data.low_pressure_kpa == low_pressure


@pytest.mark.parametrize(
    ("model_cls", "relationship_field", "relationship_value"),
    [
        (RemoteSensor, "indoor_unit_id", "idu-1"),
        (ControllerRemoteSensor, "controller_id", "ctrl-1"),
    ],
)
def test_remote_sensor_models_from_proto(
    model_cls: type[RemoteSensor] | type[ControllerRemoteSensor],
    relationship_field: str,
    relationship_value: str,
) -> None:
    proto = _ns(
        header=_make_header("sensor-1"),
        relationships=_ns(**{relationship_field: relationship_value}),
        attributes=_ns(mac=""),
        controls=_ns(control_mode=RemoteSensorControlMode.DISABLED),
        state=_ns(
            ambient_temperature_c=0.0,
            humidity_percent=47.5,
            battery_level_percent=91.0,
            signal_level_dbm=0,
        ),
    )

    sensor = model_cls.from_proto(proto)

    assert getattr(sensor, relationship_field) == relationship_value
    assert sensor.mac is None
    assert sensor.ambient_temperature_c == 0.0
    assert sensor.humidity_percent == 47.5
    assert sensor.battery_level_percent == 91.0
    assert sensor.signal_level_dbm == 0
    assert sensor.control_mode == RemoteSensorControlMode.DISABLED
