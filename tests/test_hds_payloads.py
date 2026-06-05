"""Payload-shaping tests for HomeDatastoreService update_space."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from google.protobuf.timestamp_pb2 import Timestamp

from quilt_hp._proto import quilt_hds_pb2 as hds
from quilt_hp.models.enums import HVACMode
from quilt_hp.models.space import Space
from quilt_hp.models.system import SystemSnapshot
from quilt_hp.services import hds as hds_service


def _fixed_timestamp() -> Timestamp:
    ts = Timestamp()
    ts.FromSeconds(123)
    return ts


async def _capture_update_space_diff(
    monkeypatch: pytest.MonkeyPatch,
    space: Space,
    **kwargs: object,
) -> hds.Space:
    captured: dict[str, hds.UpdateSpaceRequest] = {}

    async def _update_space(request: hds.UpdateSpaceRequest) -> hds.Space:
        captured["request"] = request
        return request.diff

    class _Stub:
        def __init__(self) -> None:
            self.UpdateSpace = _update_space

    monkeypatch.setattr(hds_service.hds_grpc, "HomeDatastoreServiceStub", lambda _ch: _Stub())
    monkeypatch.setattr(hds_service, "_now_ts", _fixed_timestamp)
    monkeypatch.setattr(hds_service.Space, "from_proto", lambda proto: proto)

    service = hds_service.HomeDatastoreService(MagicMock())
    diff = await service.update_space(space, **kwargs)
    return captured["request"].diff if isinstance(diff, hds.Space) else diff


@pytest.mark.parametrize(
    ("mode", "expected_temp", "expected_override", "expected_comfort_setting_id"),
    [
        (
            HVACMode.HEAT,
            20.0,
            hds.COMFORT_SETTING_OVERRIDE_UNTIL_NEXT_SCHEDULE,
            "comfort-1",
        ),
        (
            HVACMode.COOL,
            24.0,
            hds.COMFORT_SETTING_OVERRIDE_UNTIL_NEXT_SCHEDULE,
            "comfort-1",
        ),
        (
            HVACMode.AUTO,
            24.0,
            hds.COMFORT_SETTING_OVERRIDE_UNTIL_NEXT_SCHEDULE,
            "comfort-1",
        ),
        (HVACMode.STANDBY, 24.0, hds.COMFORT_SETTING_OVERRIDE_NONE, ""),
    ],
)
async def test_update_space_builds_expected_payload_for_modes(
    monkeypatch: pytest.MonkeyPatch,
    fake_snapshot: SystemSnapshot,
    mode: HVACMode,
    expected_temp: float,
    expected_override: int,
    expected_comfort_setting_id: str,
) -> None:
    diff = await _capture_update_space_diff(
        monkeypatch,
        fake_snapshot.spaces[0],
        mode=mode,
    )

    assert diff.header.object_id == "space-1"
    assert diff.header.system_id == "sys-1"
    assert diff.controls.hvac_mode == mode.value
    assert diff.controls.temperature_setpoint_c == pytest.approx(expected_temp)
    assert diff.controls.heating_temperature_setpoint_c == pytest.approx(20.0)
    assert diff.controls.cooling_temperature_setpoint_c == pytest.approx(24.0)
    assert diff.controls.comfort_setting_override == expected_override
    assert diff.controls.comfort_setting_id_string == expected_comfort_setting_id
    assert diff.controls.updated_ts.seconds == 123


async def test_update_space_auto_deadband_clamps_cooling_setpoint(
    monkeypatch: pytest.MonkeyPatch,
    fake_snapshot: SystemSnapshot,
) -> None:
    diff = await _capture_update_space_diff(
        monkeypatch,
        fake_snapshot.spaces[0],
        mode=HVACMode.AUTO,
        heat_setpoint_c=21.0,
        cool_setpoint_c=22.0,
    )

    assert diff.controls.heating_temperature_setpoint_c == pytest.approx(21.0)
    assert diff.controls.cooling_temperature_setpoint_c == pytest.approx(23.5)
    assert diff.controls.temperature_setpoint_c == pytest.approx(23.5)


async def test_update_space_standby_clears_comfort_setting(
    monkeypatch: pytest.MonkeyPatch,
    fake_snapshot: SystemSnapshot,
) -> None:
    diff = await _capture_update_space_diff(
        monkeypatch,
        fake_snapshot.spaces[0],
        mode=HVACMode.STANDBY,
    )

    assert diff.controls.comfort_setting_id_string == ""
    assert diff.controls.comfort_setting_override == hds.COMFORT_SETTING_OVERRIDE_NONE


async def test_update_space_dry_mode_omits_setpoints(
    monkeypatch: pytest.MonkeyPatch,
    fake_snapshot: SystemSnapshot,
) -> None:
    diff = await _capture_update_space_diff(
        monkeypatch,
        fake_snapshot.spaces[0],
        mode=HVACMode.DRY,
    )

    assert diff.controls.hvac_mode == HVACMode.DRY.value
    # Setpoint fields must be absent (proto3 default = 0.0) for DRY mode
    assert diff.controls.temperature_setpoint_c == pytest.approx(0.0)
    assert diff.controls.heating_temperature_setpoint_c == pytest.approx(0.0)
    assert diff.controls.cooling_temperature_setpoint_c == pytest.approx(0.0)
    assert diff.controls.updated_ts.seconds == 123
