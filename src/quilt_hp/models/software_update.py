"""Software/firmware update info model.

SoftwareUpdateInfo is returned at field 18 of HomeDatastoreSystem.
Each device (IDU, QSM, Controller, ODU) has two entries:
  - one referenced by software_update_info_id  (OS/app firmware)
  - one referenced by firmware_update_info_id   (device firmware)

When no update is pending, only updated_ts is populated; all version
fields and progress fields are empty/zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from quilt_hp.models._helpers import enum_or


class SoftwareUpdateState(IntEnum):
    """Where an update is in its lifecycle (``SoftwareUpdateInfoAttributes.state``)."""

    UNSPECIFIED = 0
    UNKNOWN = 0
    """Alias of UNSPECIFIED, kept for code written before the values were confirmed."""
    IDLE = 1
    DOWNLOADING = 2
    TRANSFERRING = 3
    INSTALLING = 4
    REBOOTING = 5


class SoftwareUpdateStatus(IntEnum):
    """Outcome of the last update step (``SoftwareUpdateInfoAttributes.status``)."""

    UNSPECIFIED = 0
    UNKNOWN = 0
    """Alias of UNSPECIFIED, kept for code written before the values were confirmed."""
    OK = 1
    UNKNOWN_ERROR = 2


class SoftwareUpdateProgressUnit(IntEnum):
    """Unit of ``current_progress`` / ``total_progress``."""

    UNSPECIFIED = 0
    PERCENT = 1
    BYTES = 2
    SECONDS = 3


@dataclass(slots=True)
class SoftwareUpdateInfo:
    """Update record for a single device firmware/software slot.

    All device types carry both a ``software_update_info_id`` and a
    ``firmware_update_info_id`` in their relationships; each ID
    corresponds to one SoftwareUpdateInfo object in the snapshot.

    When no update is pending all version strings are empty and
    ``current_progress``/``total_progress`` are 0.0.
    """

    id: str
    """Object UUID for software_update_info_id or firmware_update_info_id."""
    state: SoftwareUpdateState
    """Lifecycle state; IDLE when no update is in progress."""
    status: SoftwareUpdateStatus
    """Outcome of the last step."""
    current_version: str
    """Installed version string; empty when no update is active."""
    target_version: str
    """Target version string; empty when no update is pending."""
    current_progress: float
    """Download/install progress in ``progress_unit`` units."""
    total_progress: float
    """Total work in ``progress_unit`` units."""
    progress_unit: SoftwareUpdateProgressUnit
    """Unit for the progress values."""

    @classmethod
    def from_proto(cls, proto: object) -> SoftwareUpdateInfo:
        """Construct from a protobuf SoftwareUpdateInfo message."""
        a = proto.attributes  # type: ignore[attr-defined]
        return cls(
            id=proto.header.object_id,  # type: ignore[attr-defined]
            state=enum_or(SoftwareUpdateState, a.state, SoftwareUpdateState.UNSPECIFIED),
            status=enum_or(SoftwareUpdateStatus, a.status, SoftwareUpdateStatus.UNSPECIFIED),
            current_version=a.current_version or "",
            target_version=a.target_version or "",
            current_progress=a.current_progress,
            total_progress=a.total_progress,
            progress_unit=enum_or(
                SoftwareUpdateProgressUnit, a.progress_unit, SoftwareUpdateProgressUnit.UNSPECIFIED
            ),
        )
