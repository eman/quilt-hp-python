"""Dial display / radar / light telemetry (ControllerState fields 6–22)."""

from __future__ import annotations

import time

import pytest

from quilt_hp._proto import quilt_hds_pb2 as hds
from quilt_hp.models import Controller, ControllerOrientation, ControllerViewState, SystemSnapshot


def _controller(state: hds.ControllerState | None = None) -> hds.Controller:
    proto = hds.Controller(header=hds.EntityMetadata(object_id="dial-1", system_id="sys-1"))
    proto.settings.name = "Dial QD1-TEST"
    if state is not None:
        proto.state.CopyFrom(state)
    return proto


def _state(**overrides: object) -> hds.ControllerState:
    values: dict[str, object] = {
        "sht4x_temperature_c": 27.4,
        "calculated_ambient_temperature_c": 19.7,
        "view_state": hds.CONTROLLER_VIEW_STATE_GLANCE,
        "screen_brightness": 0.25,
        "mmwave_target_detect": True,
        "als_illuminance_calib_lx": 105.2,
        "orientation": hds.CONTROLLER_ORIENTATION_VERTICAL,
        "sht4x_humidity_percent": 38.5,
        "power_meter_w": 0.97,
        "main_board_temperature_c": 44.0,
        "power_board_temperature_c": 31.0,
        "accel_x_raw": 12,
        "accel_y_raw": -4454,
        "accel_z_raw": 15660,
    }
    values.update(overrides)
    return hds.ControllerState(**values)  # type: ignore[arg-type]


def test_display_fields_map_from_state() -> None:
    ctrl = Controller.from_proto(_controller(_state()))
    assert ctrl.view_state is ControllerViewState.GLANCE
    assert ctrl.screen_brightness == pytest.approx(0.25)
    assert ctrl.radar_target_detected is True
    assert ctrl.radar_phase_detected is False
    assert ctrl.ambient_light_lux == pytest.approx(105.2)
    assert ctrl.orientation is ControllerOrientation.VERTICAL
    assert ctrl.humidity_percent == pytest.approx(38.5)
    assert ctrl.power_w == pytest.approx(0.97)
    assert ctrl.main_board_temperature_c == pytest.approx(44.0)
    assert ctrl.power_board_temperature_c == pytest.approx(31.0)
    assert ctrl.accelerometer_raw == (12, -4454, 15660)
    assert ctrl.display_on is True
    assert ctrl.presence_detected is True


def test_sleeping_display_and_no_radar() -> None:
    ctrl = Controller.from_proto(
        _controller(
            _state(
                view_state=hds.CONTROLLER_VIEW_STATE_SLEEP,
                screen_brightness=0.0,
                mmwave_target_detect=False,
            )
        )
    )
    assert ctrl.display_on is False
    assert ctrl.presence_detected is False


def test_zero_humidity_means_not_reported() -> None:
    ctrl = Controller.from_proto(_controller(_state(sht4x_humidity_percent=0.0)))
    assert ctrl.humidity_percent is None


def test_unknown_enum_values_fall_back_to_unspecified() -> None:
    ctrl = Controller.from_proto(_controller(_state(view_state=99, orientation=42)))
    assert ctrl.view_state is ControllerViewState.UNSPECIFIED
    assert ctrl.orientation is ControllerOrientation.UNSPECIFIED
    assert ctrl.display_on is None


def test_absent_state_leaves_display_fields_unknown() -> None:
    ctrl = Controller.from_proto(_controller())
    assert ctrl.view_state is ControllerViewState.UNSPECIFIED
    assert ctrl.screen_brightness is None
    assert ctrl.radar_target_detected is None
    assert ctrl.accelerometer_raw is None
    assert ctrl.display_on is None
    assert ctrl.presence_detected is None


def _snapshot_with(ctrl_state: hds.ControllerState) -> SystemSnapshot:
    system = hds.HomeDatastoreSystem()
    system.controllers.append(_controller(ctrl_state))
    return SystemSnapshot.from_proto(system)


def test_apply_controller_preserves_display_fields_when_state_absent() -> None:
    snap = _snapshot_with(_state())
    merged = snap.apply_controller(Controller.from_proto(_controller()))
    assert merged.view_state is ControllerViewState.GLANCE
    assert merged.screen_brightness == pytest.approx(0.25)
    assert merged.radar_target_detected is True
    assert merged.accelerometer_raw == (12, -4454, 15660)


def test_apply_controller_takes_new_display_values() -> None:
    snap = _snapshot_with(_state())
    update = _state(
        view_state=hds.CONTROLLER_VIEW_STATE_SLEEP,
        screen_brightness=0.0,
        mmwave_target_detect=False,
    )
    merged = snap.apply_controller(Controller.from_proto(_controller(update)))
    assert merged.view_state is ControllerViewState.SLEEP
    assert merged.screen_brightness == 0.0
    assert merged.radar_target_detected is False


def test_is_online_uses_state_updated_ts_field_15() -> None:
    fresh = _state()
    fresh.updated_ts.FromSeconds(int(time.time()) - 10)
    assert Controller.from_proto(_controller(fresh)).is_online is True

    stale = _state()
    stale.updated_ts.FromSeconds(int(time.time()) - 5 * 3600)
    assert Controller.from_proto(_controller(stale)).is_online is False
