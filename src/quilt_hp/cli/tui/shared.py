"""Small data helpers shared by several screens."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from quilt_hp.cli.tui.format import _id_tokens
from quilt_hp.client import QuiltClient
from quilt_hp.models.indoor_unit import IndoorUnit
from quilt_hp.models.outdoor_unit import OutdoorUnit

if TYPE_CHECKING:
    from quilt_hp.models.system import SystemSnapshot


logger = logging.getLogger(__name__)


def _odu_for_space(
    snapshot: SystemSnapshot, space_id: str, idu: IndoorUnit | None
) -> OutdoorUnit | None:
    """Resolve a room's ODU from the IDU link first, then by room relationship."""
    if idu:
        odu = snapshot.odu_for_idu(idu)
        if odu is not None:
            return odu
    space_ids = _id_tokens(space_id)
    return next(
        (u for u in snapshot.outdoor_units if _id_tokens(u.space_id) & space_ids),
        None,
    )


def _patch_schedule_paused(snapshot: SystemSnapshot, paused: bool) -> None:
    """Patch the cached snapshot's primary location with a new paused state."""
    loc = snapshot.primary_location
    if loc is None:
        return
    idx = snapshot.locations.index(loc)
    snapshot.locations[idx] = replace(loc, schedule_paused=paused)


async def _set_schedule_paused(
    client: QuiltClient, snapshot: SystemSnapshot, paused: bool
) -> None:
    """Toggle schedule execution server-side and patch the local cache."""
    await client.set_schedule_execution(paused)
    _patch_schedule_paused(snapshot, paused)
