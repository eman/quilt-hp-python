"""Pure view helpers for the TUI: ages, local times and the "needs attention" list.

Nothing here imports Textual, so it is unit-tested directly.
"""

from __future__ import annotations

import zoneinfo
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from enum import IntEnum
from typing import TYPE_CHECKING

from quilt_hp.models.enums import IndoorUnitTestMode
from quilt_hp.models.software_update import SoftwareUpdateState

if TYPE_CHECKING:
    from quilt_hp.models.system import SystemSnapshot


class Severity(IntEnum):
    """Attention severity; lower sorts first."""

    CRITICAL = 0
    WARNING = 1
    INFO = 2


@dataclass(frozen=True, slots=True)
class AttentionItem:
    """One thing the user should know about, e.g. an offline device."""

    severity: Severity
    title: str
    detail: str = ""
    space_id: str | None = None


def age_text(then: datetime | None, now: datetime) -> str:
    """How long ago ``then`` was, coarsely: ``45 s``, ``12 min``, ``8 h``, ``3 d``."""
    if then is None:
        return "unknown"
    seconds = max(0.0, (now - then).total_seconds())
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 90 * 60:
        return f"{seconds / 60:.0f} min"
    if seconds < 48 * 3600:
        return f"{seconds / 3600:.0f} h"
    return f"{seconds / 86400:.0f} d"


def system_tz(snap: SystemSnapshot) -> tzinfo:
    """The system's own time zone (falls back to the machine's local zone)."""
    if snap.timezone:
        try:
            return zoneinfo.ZoneInfo(snap.timezone)
        except zoneinfo.ZoneInfoNotFoundError, ValueError:
            pass
    local = datetime.now().astimezone().tzinfo
    return local if local is not None else UTC


def local_hhmm(when: datetime, tz: tzinfo, now: datetime) -> str:
    """``09:52`` for today, ``Oct 4 09:52`` for an earlier day, in the system's zone."""
    local = when.astimezone(tz)
    if local.date() == now.astimezone(tz).date():
        return local.strftime("%H:%M")
    return f"{local.strftime('%b')} {local.day} {local.strftime('%H:%M')}"


def attention_items(snap: SystemSnapshot, now: datetime | None = None) -> list[AttentionItem]:
    """Everything that needs the user's attention, most severe first."""
    now = now or datetime.now(tz=UTC)
    tz = system_tz(snap)
    room_names = {s.id: s.name for s in snap.spaces}
    items: list[AttentionItem] = []

    for idu in snap.indoor_units:
        room = room_names.get(idu.space_id, "A room")
        if not idu.is_online:
            seen = idu.state.updated_at
            items.append(
                AttentionItem(
                    Severity.CRITICAL,
                    f"{room} indoor unit offline",
                    _last_seen(seen, tz, now),
                    idu.space_id,
                )
            )
        if idu.is_under_test:
            mode = idu.effective_test_mode
            label = (
                "test" if mode == IndoorUnitTestMode.UNSPECIFIED else _words(mode.name) + " test"
            )
            items.append(
                AttentionItem(
                    Severity.WARNING,
                    f"{room} indoor unit running a {label}",
                    "it ignores the room's controls until the test ends",
                    idu.space_id,
                )
            )

    for ctrl in snap.controllers:
        if not ctrl.is_online:
            room = room_names.get(ctrl.space_id, "A room")
            items.append(
                AttentionItem(
                    Severity.WARNING,
                    f"{room} Dial offline",
                    _last_seen(ctrl.state_updated_at, tz, now),
                    ctrl.space_id,
                )
            )

    for diag in snap.diagnostics().indoor_units:
        for condition in diag.active_faults:
            room = diag.space_name or "A room"
            items.append(
                AttentionItem(Severity.WARNING, f"{room}: {_words(condition)}", "", diag.space_id)
            )

    updating = [
        u
        for u in snap.software_update_infos
        if u.state not in (SoftwareUpdateState.UNSPECIFIED, SoftwareUpdateState.IDLE)
    ]
    if updating:
        noun = "update" if len(updating) == 1 else "updates"
        items.append(AttentionItem(Severity.INFO, f"{len(updating)} firmware {noun} in progress"))

    loc = snap.primary_location
    if loc is not None and loc.schedule_paused:
        items.append(AttentionItem(Severity.INFO, "Schedules paused for the whole house"))

    return sorted(items, key=lambda item: item.severity)


def _last_seen(seen: datetime | None, tz: tzinfo, now: datetime) -> str:
    if seen is None:
        return "never reported"
    return f"last reading {age_text(seen, now)} ago ({local_hhmm(seen, tz, now)})"


def _words(name: str) -> str:
    return name.replace("_", " ").lower()
