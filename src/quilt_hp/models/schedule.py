"""Schedule models — week programs, day programs, schedule events."""

from __future__ import annotations

from dataclasses import dataclass

from quilt_hp.const import EMPTY_COMFORT_SETTING_ID_SENTINEL, UNKNOWN_SCHEDULE_SORT_ORDER_SENTINEL
from quilt_hp.models.enums import HVACMode

_WEEKDAY_NAMES = {
    0: "?",
    1: "Mon",
    2: "Tue",
    3: "Wed",
    4: "Thu",
    5: "Fri",
    6: "Sat",
    7: "Sun",
}


@dataclass(slots=True)
class ScheduleEvent:
    """A single time event within a schedule day."""

    start_s: int  # seconds from midnight
    comfort_setting_id: str
    hvac_mode: HVACMode
    heating_setpoint_c: float
    cooling_setpoint_c: float
    precondition: bool

    @property
    def start_time(self) -> str:
        """Format start_s as HH:MM."""
        return f"{self.start_s // 3600:02d}:{(self.start_s % 3600) // 60:02d}"

    @property
    def has_linked_comfort_setting(self) -> bool:
        """True when this event references a comfort setting by ID."""
        return self.comfort_setting_id != EMPTY_COMFORT_SETTING_ID_SENTINEL

    @property
    def comfort_setting_id_or_none(self) -> str | None:
        """Comfort-setting ID, or None when event uses explicit setpoints."""
        return self.comfort_setting_id if self.has_linked_comfort_setting else None


@dataclass(slots=True)
class ScheduleDay:
    """A named day program with time events."""

    id: str
    name: str
    space_id: str
    events: list[ScheduleEvent]

    @classmethod
    def from_proto(cls, proto: object) -> ScheduleDay:
        """Construct from a protobuf ScheduleDay message."""
        events = [
            ScheduleEvent(
                start_s=ev.start_s,
                comfort_setting_id=ev.comfort_setting_id,
                hvac_mode=HVACMode(ev.hvac_mode),
                heating_setpoint_c=ev.heating_temperature_setpoint_c,
                cooling_setpoint_c=ev.cooling_temperature_setpoint_c,
                precondition=ev.precondition,
            )
            for ev in sorted(proto.events, key=lambda e: e.start_s)  # type: ignore[attr-defined]
        ]
        return cls(
            id=proto.header.object_id,  # type: ignore[attr-defined]
            name=proto.attributes.name,  # type: ignore[attr-defined]
            space_id=proto.relationships.space_id,  # type: ignore[attr-defined]
            events=events,
        )


@dataclass(slots=True)
class ScheduleWeekDay:
    """A single weekday→day-program mapping."""

    weekday: int
    day_id: str

    @property
    def weekday_name(self) -> str:
        return _WEEKDAY_NAMES.get(self.weekday, str(self.weekday))

    @property
    def weekday_sort_order(self) -> int:
        """Sort key; unknown weekday values map to a tail sentinel."""
        return (
            self.weekday
            if self.weekday in _WEEKDAY_NAMES and self.weekday != 0
            else (UNKNOWN_SCHEDULE_SORT_ORDER_SENTINEL)
        )


@dataclass(slots=True)
class ScheduleWeek:
    """A weekly schedule for a space, mapping weekdays to day programs."""

    id: str
    space_id: str
    days: list[ScheduleWeekDay]

    @classmethod
    def from_proto(cls, proto: object) -> ScheduleWeek:
        """Construct from a protobuf ScheduleWeek message."""
        days = [
            ScheduleWeekDay(weekday=wd.weekday, day_id=wd.day_id)
            for wd in sorted(proto.days, key=lambda x: x.weekday)  # type: ignore[attr-defined]
        ]
        return cls(
            id=proto.header.object_id,  # type: ignore[attr-defined]
            space_id=proto.relationships.space_id,  # type: ignore[attr-defined]
            days=days,
        )
