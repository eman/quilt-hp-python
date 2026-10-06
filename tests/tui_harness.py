"""Offline harness for TUI tests: a fake client serving a scrubbed snapshot of a real system.

``tests/fixtures/system_snapshot.bin`` is a ``HomeDatastoreSystem`` captured from a live
five-room system on 2026-10-05, with every id, serial number, name and network detail
replaced. ``FROZEN_NOW`` is just after the capture, so device online/offline state matches
what the system reported (one Dial had been offline for about eight hours).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from quilt_hp._proto import quilt_hds_pb2 as hds
from quilt_hp.cli.settings import SettingsStore
from quilt_hp.cli.tui import QuiltApp
from quilt_hp.models import HVACMode, SystemSnapshot
from quilt_hp.models.energy import EnergyBucket, SpaceEnergyMetrics
from quilt_hp.models.enums import MetricBucketStatus
from quilt_hp.models.space import Space

FIXTURE = Path(__file__).parent / "fixtures" / "system_snapshot.bin"
FROZEN_NOW = datetime.fromtimestamp(1_791_248_669 + 5, tz=UTC)
SYSTEM_TZ = ZoneInfo("America/Los_Angeles")


def load_snapshot() -> SystemSnapshot:
    return SystemSnapshot.from_proto(hds.HomeDatastoreSystem.FromString(FIXTURE.read_bytes()))


class FakeStream:
    """Accepts callbacks and waits until stopped; tests push no events by default."""

    def __init__(self) -> None:
        self.callbacks: dict[str, Callable[..., Any]] = {}
        self._stopped = asyncio.Event()

    def __getattr__(self, name: str) -> Callable[[Callable[..., Any]], None]:
        if not name.startswith("on_"):
            raise AttributeError(name)

        def register(callback: Callable[..., Any]) -> None:
            self.callbacks[name] = callback

        return register

    async def run_forever(self) -> None:
        await self._stopped.wait()

    async def stop(self) -> None:
        self._stopped.set()


class FakeClient:
    """The subset of QuiltClient the TUI uses, backed by the fixture snapshot."""

    system_name = "Example Home"

    def __init__(self, snapshot: SystemSnapshot | None = None) -> None:
        self.snapshot = snapshot or load_snapshot()
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def login(self, **_: Any) -> None:
        return None

    async def get_snapshot(self) -> SystemSnapshot:
        return self.snapshot

    def stream(self, topics: list[str], **_: Any) -> FakeStream:
        return FakeStream()

    async def get_energy(self, start: datetime, end: datetime) -> list[SpaceEnergyMetrics]:
        """Hourly buckets: a 7 Wh standby baseline, with cooling at 16:00 and 17:00 local."""
        today = FROZEN_NOW.astimezone(SYSTEM_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        buckets = []
        hour = start.astimezone(SYSTEM_TZ).replace(minute=0, second=0, microsecond=0)
        while hour < end:
            kwh = 0.0072
            if hour.date() == today.date() and hour.hour in (16, 17):
                kwh = 0.4468 if hour.hour == 16 else 0.527
            buckets.append(EnergyBucket(hour.astimezone(UTC), kwh, MetricBucketStatus.COMPLETE))
            hour += timedelta(hours=1)
        return [SpaceEnergyMetrics(space.id, list(buckets)) for space in self.snapshot.rooms]

    async def close(self) -> None:
        return None

    async def set_space(
        self,
        space: Space,
        *,
        mode: HVACMode | None = None,
        heat_setpoint_c: float | None = None,
        cool_setpoint_c: float | None = None,
    ) -> Space:
        """Record the call and return the space with the change applied, like the server."""
        self.calls.append(
            (
                "set_space",
                (space.id,),
                {"mode": mode, "heat": heat_setpoint_c, "cool": cool_setpoint_c},
            )
        )
        c = space.controls
        return replace(
            space,
            controls=replace(
                c,
                hvac_mode=mode if mode is not None else c.hvac_mode,
                heating_setpoint_c=heat_setpoint_c
                if heat_setpoint_c is not None
                else c.heating_setpoint_c,
                cooling_setpoint_c=cool_setpoint_c
                if cool_setpoint_c is not None
                else c.cooling_setpoint_c,
            ),
        )

    def __getattr__(self, name: str) -> Callable[..., Any]:
        if not name.startswith("set_"):
            raise AttributeError(name)

        async def record(*args: Any, **kwargs: Any) -> None:
            self.calls.append((name, args, kwargs))

        return record


def make_app(tmp_path: Path, client: FakeClient | None = None) -> QuiltApp:
    return QuiltApp(
        "test@example.com",
        client=client or FakeClient(),  # type: ignore[arg-type]
        settings_store=SettingsStore(tmp_path / "settings.json"),
    )
