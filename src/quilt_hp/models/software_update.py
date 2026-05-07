"""Software/firmware update info model.

SoftwareUpdateInfo is returned at field 18 of HomeDatastoreSystem.
Each device (IDU, QSM, Controller, ODU) has two entries:
  - one referenced by software_update_info_id  (OS/app firmware)
  - one referenced by firmware_update_info_id   (device firmware)

When no update is pending, only updated_ts is populated; all version
fields and progress fields are empty/zero.

APK-confirmed: YL.java (proto), WL.java (attributes), OJ.java (field 18 in HDS).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class SoftwareUpdateState(IntEnum):
    """Update state values (field 2, values still unconfirmed)."""

    UNKNOWN = 0


class SoftwareUpdateStatus(IntEnum):
    """Update status values (field 3, values still unconfirmed)."""

    UNKNOWN = 0


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
    state: int
    """Raw update state integer (SoftwareUpdateState enum, TBD)."""
    status: int
    """Raw update status integer (SoftwareUpdateStatus enum, TBD)."""
    current_version: str
    """Installed version string; empty when no update is active."""
    target_version: str
    """Target version string; empty when no update is pending."""
    current_progress: float
    """Download/install progress in ``progress_unit`` units."""
    total_progress: float
    """Total work in ``progress_unit`` units."""
    progress_unit: int
    """Unit for progress values (enum TBD)."""

    @classmethod
    def from_proto(cls, proto: object) -> SoftwareUpdateInfo:
        """Construct from a protobuf SoftwareUpdateInfo message."""
        a = proto.attributes  # type: ignore[attr-defined]
        return cls(
            id=proto.header.object_id,  # type: ignore[attr-defined]
            state=a.state,
            status=a.status,
            current_version=a.current_version or "",
            target_version=a.target_version or "",
            current_progress=a.current_progress,
            total_progress=a.total_progress,
            progress_unit=a.progress_unit,
        )
