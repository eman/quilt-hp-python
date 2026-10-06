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
from quilt_hp.models.comfort import ComfortSetting
from quilt_hp.models.energy import EnergyBucket, SpaceEnergyMetrics
from quilt_hp.models.enums import LightState, MetricBucketStatus
from quilt_hp.models.indoor_unit import IndoorUnit
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
        self.delay = 0.0

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
        if self.delay:
            await asyncio.sleep(self.delay)  # a slow server, to test presses that overlap
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

    async def set_indoor_unit(self, idu: IndoorUnit, **changes: Any) -> IndoorUnit:
        self.calls.append(("set_indoor_unit", (idu.id,), changes))
        c = idu.controls
        updates: dict[str, Any] = {}
        if changes.get("fan_speed") is not None:
            updates["fan_speed"] = changes["fan_speed"]
        if changes.get("louver_mode") is not None:
            updates["louver_mode"] = changes["louver_mode"]
        if changes.get("led_brightness") is not None:
            level = changes["led_brightness"]
            updates["led_brightness"] = level if level > 0 else c.led_brightness
            updates["led_state"] = LightState.ON if level > 0 else LightState.OFF
        return replace(idu, controls=replace(c, **updates))

    async def set_space_settings(self, space: Space, **changes: Any) -> Space:
        self.calls.append(("set_space_settings", (space.id,), changes))
        updates = {k: v for k, v in changes.items() if v is not None}
        return replace(space, settings=replace(space.settings, **updates))

    async def set_indoor_unit_settings(self, idu: IndoorUnit, **changes: Any) -> IndoorUnit:
        self.calls.append(("set_indoor_unit_settings", (idu.id,), changes))
        return idu

    async def update_comfort_setting(
        self, setting: ComfortSetting, **changes: Any
    ) -> ComfortSetting:
        self.calls.append(("update_comfort_setting", (setting.id,), changes))
        return replace(
            setting,
            heating_setpoint_c=changes.get("heat_setpoint_c") or setting.heating_setpoint_c,
            cooling_setpoint_c=changes.get("cool_setpoint_c") or setting.cooling_setpoint_c,
        )

    async def apply_mode(self, mode: Any, **kwargs: Any) -> Any:
        from quilt_hp.models import ActionOutcome, ActionResult

        self.calls.append(("apply_mode", (mode,), kwargs))
        return ActionOutcome(result=ActionResult.SUCCESS, action_id="fake-action")

    async def start_self_test(self, idu: IndoorUnit) -> None:
        self.calls.append(("start_self_test", (idu,), {}))

    async def cancel_self_test(self, idu: IndoorUnit) -> None:
        self.calls.append(("cancel_self_test", (idu,), {}))

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
