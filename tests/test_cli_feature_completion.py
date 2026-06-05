"""Tests for CLI device/value output modes."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

from quilt_hp.cli import main as cli_main
from quilt_hp.models.enums import (
    FanSpeed,
    HVACMode,
    HVACState,
    LocalCommsHealthStatus,
    LouverMode,
    RemoteSensorControlMode,
)

runner = CliRunner()


class _FakeSnapshot:
    timezone = "UTC"

    def __init__(self) -> None:
        self.spaces = [
            SimpleNamespace(
                id="space-1",
                name="Living Room",
                parent_space_id="home-1",
                is_room=True,
                controls=SimpleNamespace(
                    hvac_mode=HVACMode.COOL,
                    temperature_setpoint_c=22.0,
                    cooling_setpoint_c=22.0,
                    heating_setpoint_c=19.0,
                    display_setpoint="22.0°C",
                    comfort_setting_id="comfort-1",
                ),
                state=SimpleNamespace(
                    ambient_temperature_c=23.1,
                    setpoint_c=22.0,
                    hvac_state=HVACState.COOL,
                    comfort_setting_id="comfort-1",
                ),
            )
        ]
        self.indoor_units = [
            SimpleNamespace(
                id="idu-1",
                space_id="space-1",
                outdoor_unit_id="odu-1",
                qsm_id="qsm-1",
                hardware_id="idu-hw-1",
                firmware_update_info_id="update-firmware-idu",
                controls=SimpleNamespace(
                    fan_speed=FanSpeed.LOW,
                    louver_mode=LouverMode.AUTO,
                    led_brightness=0.5,
                ),
                state=SimpleNamespace(
                    hvac_mode=HVACMode.COOL,
                    hvac_state=HVACState.COOL,
                    ambient_temperature_c=23.0,
                    ambient_humidity_percent=45.0,
                    temperature_setpoint_c=22.0,
                ),
                performance_data=SimpleNamespace(
                    coil_temperature_c=12.4,
                    actual_fan_speed_rpm=420.0,
                ),
                led_on=True,
                effective_occupancy_state=2,
                software_update_info_id="update-software-idu",
            )
        ]
        self.outdoor_units = [
            SimpleNamespace(
                id="odu-1",
                space_id="space-1",
                model_sku="ODU-42",
                serial_number="SER123",
                firmware_version="1.2.3",
                firmware_update_info_id="update-firmware-odu",
                performance_data=SimpleNamespace(
                    compressor_frequency_hz=33.0,
                    ambient_temperature_c=28.0,
                    coil_temperature_c=35.0,
                ),
            )
        ]
        self.controllers = [
            SimpleNamespace(
                id="ctrl-1",
                space_id="space-1",
                name="Dial",
                ambient_temperature_c=22.8,
                raw_thermistor_c=24.2,
                remote_sensor_mode=RemoteSensorControlMode.ENABLED,
                local_comms_health=LocalCommsHealthStatus.HEALTHY,
                software_update_info_id="update-software-ctrl",
                firmware_update_info_id="update-firmware-ctrl",
                serial_number="CTRL123",
                model_sku="DIAL-01",
            )
        ]
        self.remote_sensors = [
            SimpleNamespace(
                id="rs-1",
                indoor_unit_id="idu-1",
                ambient_temperature_c=22.6,
                humidity_percent=41.0,
                battery_level_percent=96.0,
                signal_level_dbm=-56,
                control_mode=RemoteSensorControlMode.ENABLED,
            )
        ]
        self.controller_remote_sensors = [
            SimpleNamespace(
                id="crs-1",
                controller_id="ctrl-1",
                ambient_temperature_c=22.5,
                humidity_percent=40.0,
                battery_level_percent=90.0,
                signal_level_dbm=-52,
                control_mode=RemoteSensorControlMode.ENABLED,
            )
        ]
        self.quilt_smart_modules = [
            SimpleNamespace(
                id="qsm-1",
                software_update_info_id="update-software-qsm",
                firmware_update_info_id="update-firmware-qsm",
                local_comms_health=LocalCommsHealthStatus.HEALTHY,
                sensors=SimpleNamespace(
                    phase_detected_raw=0.1,
                    target_detected_raw=0.2,
                    als_illuminance_raw=123,
                    accel_x_raw=1,
                    accel_y_raw=2,
                    accel_z_raw=3,
                ),
            )
        ]
        self.software_update_infos = [
            SimpleNamespace(
                id="update-software-idu",
                state=1,
                status=1,
                current_version="1.0.0",
                target_version="1.1.0",
                current_progress=0.2,
                total_progress=1.0,
                progress_unit=1,
            )
        ]

    def stream_topics(self) -> list[str]:
        return ["hds/space/space-1", "hds/indoor_unit/idu-1", "hds/controller/ctrl-1"]


class _FakeClient:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def login(self) -> None:
        return None

    async def get_snapshot(self) -> _FakeSnapshot:
        return _FakeSnapshot()


def test_info_json_outputs_machine_readable_snapshot() -> None:
    with (
        patch.object(cli_main, "_resolve", return_value=("user@example.com", None)),
        patch.object(cli_main, "QuiltClient", _FakeClient),
    ):
        result = runner.invoke(cli_main.app, ["info", "--output", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["spaces"][0]["id"] == "space-1"
    assert payload["indoor_units"][0]["state"]["ambient_temperature_c"] == 23.0
    assert payload["update_entities"][1]["entity_type"] == "indoor_unit"


def test_devices_summary_lists_all_entity_classes() -> None:
    with (
        patch.object(cli_main, "_resolve", return_value=("user@example.com", None)),
        patch.object(cli_main, "QuiltClient", _FakeClient),
    ):
        result = runner.invoke(cli_main.app, ["devices"])

    assert result.exit_code == 0
    assert "Spaces" in result.stdout
    assert "Indoor Units" in result.stdout
    assert "Remote Sensors" in result.stdout
    assert "qsm-1" in result.stdout


def test_values_summary_contains_setpoints_and_sensor_values() -> None:
    with (
        patch.object(cli_main, "_resolve", return_value=("user@example.com", None)),
        patch.object(cli_main, "QuiltClient", _FakeClient),
    ):
        result = runner.invoke(cli_main.app, ["values"])

    assert result.exit_code == 0
    assert "Living Room" in result.stdout
    assert "setpoint=22.0°C" in result.stdout
    assert "ambient=23.1°C" in result.stdout
    assert "idu-1 space=space-1" in result.stdout
    assert "rs-1 idu=idu-1 temp=22.6°C" in result.stdout


def test_devices_json_includes_all_entity_ids() -> None:
    with (
        patch.object(cli_main, "_resolve", return_value=("user@example.com", None)),
        patch.object(cli_main, "QuiltClient", _FakeClient),
    ):
        result = runner.invoke(cli_main.app, ["devices", "--output", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["spaces"][0]["id"] == "space-1"
    assert payload["indoor_units"][0]["id"] == "idu-1"
    assert payload["outdoor_units"][0]["id"] == "odu-1"
    assert payload["controllers"][0]["id"] == "ctrl-1"
    assert payload["remote_sensors"][0]["id"] == "rs-1"
    assert payload["controller_remote_sensors"][0]["id"] == "crs-1"
    assert payload["quilt_smart_modules"][0]["id"] == "qsm-1"


def test_values_json_includes_setpoints_and_sensor_data() -> None:
    with (
        patch.object(cli_main, "_resolve", return_value=("user@example.com", None)),
        patch.object(cli_main, "QuiltClient", _FakeClient),
    ):
        result = runner.invoke(cli_main.app, ["values", "--output", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["spaces"][0]["display_setpoint"] == "22.0°C"
    assert payload["spaces"][0]["cooling_setpoint_c"] == 22.0
    assert payload["indoor_units"][0]["temperature_setpoint_c"] == 22.0
    assert payload["remote_sensors"][0]["ambient_temperature_c"] == 22.6
    assert payload["quilt_smart_modules"][0]["sensors"]["als_illuminance_raw"] == 123


def test_output_mode_validation_is_explicit() -> None:
    with patch.object(cli_main, "_resolve", return_value=("user@example.com", None)):
        result = runner.invoke(cli_main.app, ["info", "--output", "yaml"])

    assert result.exit_code != 0
    assert "'yaml' is not one of 'summary', 'json'" in result.output
