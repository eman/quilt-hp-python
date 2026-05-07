"""Schedule models — week programs, day programs, schedule events."""

from __future__ import annotations

from dataclasses import dataclass

_WEEKDAY_NAMES = {0: "?", 1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}


@dataclass(slots=True)
class ScheduleEvent:
    """A single time event within a schedule day."""

    start_s: int  # seconds from midnight
    comfort_setting_id: str
    hvac_mode: int
    heating_setpoint_c: float
    cooling_setpoint_c: float
    precondition: bool

    @property
    def start_time(self) -> str:
        """Format start_s as HH:MM."""
        return f"{self.start_s // 3600:02d}:{(self.start_s % 3600) // 60:02d}"


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
                hvac_mode=ev.hvac_mode,
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
