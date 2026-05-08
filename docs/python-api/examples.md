# Examples

Complete runnable scripts demonstrating common tasks. Each example is self-contained and shows realistic usage including error handling and clean shutdown.

## Prerequisites

Install the library and set your email:

```bash
pip install quilt-hp
export QUILT_EMAIL="you@example.com"
```

All examples use `FileStore` so tokens are cached after the first login. Replace with your own `TokenStore` for non-CLI applications.

---

## List all spaces and current temperatures

```python
#!/usr/bin/env python3
"""Print every space, its current mode, and the room temperature."""
import asyncio
import os
from quilt_hp import QuiltClient, Environment
from quilt_hp.cli.store import FileStore
from quilt_hp.models.enums import HVACMode

EMAIL = os.environ["QUILT_EMAIL"]


async def main() -> None:
    store = FileStore()
    async with QuiltClient(EMAIL, token_store=store) as client:
        await client.login()
        snapshot = await client.get_snapshot()

        print(f"System: {snapshot.system_id}")
        print()

        for space in sorted(snapshot.rooms, key=lambda s: s.name):
            temp = (
                f"{space.state.current_temp_c:.1f}°C"
                if space.state.current_temp_c is not None
                else "—"
            )
            mode = space.controls.mode.value
            heat = f"{space.controls.heat_setpoint_c:.1f}"
            cool = f"{space.controls.cool_setpoint_c:.1f}"

            print(f"{space.name:<20} {mode:<8} {temp:<8} (heat {heat}°C / cool {cool}°C)")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Control a space

```python
#!/usr/bin/env python3
"""Set a specific space to COOL mode at 22°C."""
import asyncio
import os
import sys
from quilt_hp import QuiltClient
from quilt_hp.cli.store import FileStore
from quilt_hp.models.enums import HVACMode

EMAIL = os.environ["QUILT_EMAIL"]
SPACE_NAME = sys.argv[1] if len(sys.argv) > 1 else "Living Room"


async def main() -> None:
    store = FileStore()
    async with QuiltClient(EMAIL, token_store=store) as client:
        await client.login()
        snapshot = await client.get_snapshot()

        # Find the space by name (case-insensitive)
        space = next(
            (s for s in snapshot.rooms if s.name.lower() == SPACE_NAME.lower()),
            None,
        )
        if space is None:
            rooms = ", ".join(s.name for s in snapshot.rooms)
            print(f"Space '{SPACE_NAME}' not found. Available: {rooms}")
            return

        updated = await client.set_space(
            space,
            mode=HVACMode.COOL,
            cool_setpoint_c=22.0,
        )
        print(
            f"Updated '{updated.name}': mode={updated.controls.mode.value}, "
            f"cool={updated.controls.cool_setpoint_c}°C"
        )


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Fetch energy data for the past week

```python
#!/usr/bin/env python3
"""Print daily kWh totals per space for the last 7 days."""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from quilt_hp import QuiltClient
from quilt_hp.cli.store import FileStore

EMAIL = os.environ["QUILT_EMAIL"]


async def main() -> None:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=7)

    store = FileStore()
    async with QuiltClient(EMAIL, token_store=store) as client:
        await client.login()
        snapshot = await client.get_snapshot()
        metrics = await client.get_energy(start=start, end=now)

        space_name = {s.id: s.name for s in snapshot.rooms}

        print(f"Energy: {start.date()} – {now.date()}")
        print()

        for entry in sorted(metrics, key=lambda e: space_name.get(e.space_id, "")):
            name = space_name.get(entry.space_id, entry.space_id)
            total_kwh = sum(b.energy_kwh for b in entry.buckets)
            print(f"  {name:<20} {total_kwh:.2f} kWh")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Subscribe to real-time updates for 60 seconds

```python
#!/usr/bin/env python3
"""Stream space and indoor-unit updates for 60 seconds then exit."""
import asyncio
import os
from quilt_hp import QuiltClient
from quilt_hp.cli.store import FileStore
from quilt_hp.models.space import Space
from quilt_hp.models.indoor_unit import IndoorUnit

EMAIL = os.environ["QUILT_EMAIL"]


async def on_space(space: Space) -> None:
    temp = (
        f"{space.state.current_temp_c:.1f}°C"
        if space.state.current_temp_c is not None
        else "—"
    )
    print(f"[space] {space.name}: mode={space.controls.mode.value}, temp={temp}")


async def on_idu(idu: IndoorUnit) -> None:
    print(
        f"[idu]   {idu.id}: fan={idu.controls.fan_speed.value}, "
        f"online={idu.state.is_online}"
    )


async def main() -> None:
    store = FileStore()
    async with QuiltClient(EMAIL, token_store=store) as client:
        await client.login()
        snapshot = await client.get_snapshot()
        topics = snapshot.stream_topics()

        stream = client.stream(topics)
        stream.on_space_update(on_space)
        stream.on_indoor_unit_update(on_idu)

        async with stream:
            print(f"Streaming {len(topics)} topics for 60 seconds…")
            await asyncio.sleep(60)

        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Simple HVAC daemon

A long-running process that keeps a snapshot fresh via streaming and responds to events. This pattern is the foundation for Home Assistant integrations and automation services.

```python
#!/usr/bin/env python3
"""
Minimal HVAC daemon.

Maintains a live SystemSnapshot, reacts to temperature changes,
and shuts down cleanly on SIGINT/SIGTERM.
"""
import asyncio
import logging
import os
import signal
from quilt_hp import QuiltClient
from quilt_hp.cli.store import FileStore
from quilt_hp.models.space import Space

EMAIL = os.environ["QUILT_EMAIL"]
LOG = logging.getLogger("quilt-daemon")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

snapshot = None  # kept in sync by stream callbacks
stop_event = asyncio.Event()


async def on_space_update(space: Space) -> None:
    global snapshot
    if snapshot is not None:
        snapshot.spaces[space.id] = space

    if space.state.current_temp_c is not None:
        LOG.info(
            "Temperature update: %s = %.1f°C (mode=%s)",
            space.name,
            space.state.current_temp_c,
            space.controls.mode.value,
        )


async def run() -> None:
    global snapshot

    store = FileStore()
    async with QuiltClient(EMAIL, token_store=store, snapshot_ttl_s=300) as client:
        await client.login()
        snapshot = await client.get_snapshot()
        LOG.info("Loaded snapshot: %d rooms", len(snapshot.rooms))

        topics = snapshot.stream_topics()
        stream = client.stream(topics, max_reconnects=-1)
        stream.on_space_update(on_space_update)
        stream.on_connected(lambda: LOG.info("Stream connected"))
        stream.on_disconnected(lambda: LOG.info("Stream disconnected; will reconnect"))

        async with stream:
            LOG.info("Daemon running. Send SIGINT to stop.")
            await stop_event.wait()
            LOG.info("Shutdown signal received.")


def main() -> None:
    loop = asyncio.new_event_loop()

    def _stop(sig: signal.Signals) -> None:
        LOG.info("Received %s", sig.name)
        loop.call_soon_threadsafe(stop_event.set)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _stop, sig)

    try:
        loop.run_until_complete(run())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
```

---

## List all devices as JSON

```python
#!/usr/bin/env python3
"""Emit a JSON document with all spaces, IDUs, and ODUs."""
import asyncio
import json
import os
from dataclasses import asdict
from quilt_hp import QuiltClient
from quilt_hp.cli.store import FileStore

EMAIL = os.environ["QUILT_EMAIL"]


def _clean(obj: object) -> object:
    """Recursively convert non-serialisable values for json.dumps."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    from datetime import datetime
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


async def main() -> None:
    store = FileStore()
    async with QuiltClient(EMAIL, token_store=store) as client:
        await client.login()
        snapshot = await client.get_snapshot()

        doc = {
            "system_id": snapshot.system_id,
            "spaces": _clean([asdict(s) for s in snapshot.rooms]),
            "indoor_units": _clean(list(asdict(u) for u in snapshot.indoor_units.values())),
            "outdoor_units": _clean(list(asdict(u) for u in snapshot.outdoor_units.values())),
            "controllers": _clean(list(asdict(c) for c in snapshot.controllers.values())),
        }
        print(json.dumps(doc, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Apply a comfort setting to all rooms

```python
#!/usr/bin/env python3
"""Apply a named comfort setting to every room that supports it."""
import asyncio
import os
import sys
from quilt_hp import QuiltClient
from quilt_hp.cli.store import FileStore

EMAIL = os.environ["QUILT_EMAIL"]
PRESET_NAME = sys.argv[1] if len(sys.argv) > 1 else "Eco"


async def main() -> None:
    store = FileStore()
    async with QuiltClient(EMAIL, token_store=store) as client:
        await client.login()
        snapshot = await client.get_snapshot()

        # Find the comfort setting by name
        preset = next(
            (cs for cs in snapshot.comfort_settings.values() if cs.name == PRESET_NAME),
            None,
        )
        if preset is None:
            names = [cs.name for cs in snapshot.comfort_settings.values()]
            print(f"Preset '{PRESET_NAME}' not found. Available: {names}")
            return

        for space in snapshot.rooms:
            updated = await client.set_space(
                space,
                mode=preset.hvac_mode,
                heat_setpoint_c=preset.heat_setpoint_c,
                cool_setpoint_c=preset.cool_setpoint_c,
            )
            print(f"  {updated.name}: mode={updated.controls.mode.value}")


if __name__ == "__main__":
    asyncio.run(main())
```
