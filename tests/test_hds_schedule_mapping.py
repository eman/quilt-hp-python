"""Tests for schedule mapping between domain models and wire protos."""

from __future__ import annotations

from types import SimpleNamespace

from quilt_hp._proto import quilt_hds_pb2 as hds
from quilt_hp.models.schedule import ScheduleEvent, ScheduleWeekDay
from quilt_hp.services.hds import _to_wire_schedule_event, _to_wire_schedule_week_day


def test_to_wire_schedule_event_from_domain_model() -> None:
    event = ScheduleEvent(
        start_s=3600,
        comfort_setting_id="cs-1",
        hvac_mode=3,
        heating_setpoint_c=20.0,
        cooling_setpoint_c=25.0,
        precondition=True,
    )

    wire = _to_wire_schedule_event(event)

    assert isinstance(wire, hds.ScheduleEvent)
    assert wire.start_s == 3600
    assert wire.comfort_setting_id == "cs-1"
    assert wire.hvac_mode == 3
    assert wire.heating_temperature_setpoint_c == 20.0
    assert wire.cooling_temperature_setpoint_c == 25.0
    assert wire.precondition is True


def test_to_wire_schedule_event_passthrough_proto() -> None:
    wire = hds.ScheduleEvent(start_s=123)
    assert _to_wire_schedule_event(wire) is wire


def test_to_wire_schedule_event_accepts_duck_typed_object() -> None:
    event = SimpleNamespace(
        start_s=7200,
        comfort_setting_id="cs-2",
        hvac_mode=2,
        heating_setpoint_c=19.0,
        cooling_setpoint_c=24.0,
        precondition=False,
    )

    wire = _to_wire_schedule_event(event)

    assert wire.start_s == 7200
    assert wire.comfort_setting_id == "cs-2"


def test_to_wire_schedule_week_day_from_domain_model() -> None:
    day = ScheduleWeekDay(weekday=2, day_id="day-2")

    wire = _to_wire_schedule_week_day(day)

    assert isinstance(wire, hds.ScheduleWeekDay)
    assert wire.weekday == 2
    assert wire.day_id == "day-2"


def test_to_wire_schedule_week_day_passthrough_proto() -> None:
    wire = hds.ScheduleWeekDay(weekday=6, day_id="day-6")
    assert _to_wire_schedule_week_day(wire) is wire
