"""What screens need from the running app, without importing it (avoids an import cycle)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from quilt_hp.models.system import SystemSnapshot


@runtime_checkable
class SnapshotHost(Protocol):
    """The app as screens see it: the shared snapshot and the unit preference."""

    use_f: bool

    @property
    def snapshot(self) -> SystemSnapshot | None: ...

    def update_snapshot(self, snap: SystemSnapshot) -> None: ...
