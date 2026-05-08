# Automation service daemon

This playbook shows how to build a production-quality Python daemon that runs `quilt-hp-python` continuously, handles reconnection automatically, responds to HVAC events with custom logic, and shuts down cleanly.

---

## Process lifecycle

A well-behaved daemon follows this lifecycle:

```
startup → login → initial snapshot → start stream → main loop → [event handling] → shutdown
```

On shutdown (SIGINT or SIGTERM), the daemon:

1. Sets a stop event.
2. Waits for the stream to drain in-flight callbacks.
3. Stops the stream (sends gRPC close).
4. Exits the `QuiltClient` context manager (closes the channel).

---

## Full daemon template

```python
#!/usr/bin/env python3
"""
quilt-daemon — minimal production daemon template.

Set QUILT_EMAIL in the environment before running.
"""
from __future__ import annotations
import asyncio
import logging
import os
import signal
from datetime import datetime, timezone
from quilt_hp import QuiltClient
from quilt_hp.cli.store import FileStore
from quilt_hp.models.space import Space
from quilt_hp.models.indoor_unit import IndoorUnit
from quilt_hp.models.system import SystemSnapshot

LOG = logging.getLogger("quilt-daemon")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

EMAIL = os.environ["QUILT_EMAIL"]
_stop = asyncio.Event()
_snapshot: SystemSnapshot | None = None


# ---------------------------------------------------------------------------
# Event handlers — put your automation logic here
# ---------------------------------------------------------------------------

async def on_space_update(space: Space) -> None:
    global _snapshot
    if _snapshot is not None:
        _snapshot.spaces[space.id] = space

    temp = (
        f"{space.state.current_temp_c:.1f}°C"
        if space.state.current_temp_c is not None
        else "unknown"
    )
    LOG.info("[space] %s — mode=%s temp=%s", space.name, space.controls.mode.value, temp)

    # Example rule: if a room gets too hot and is in AUTO mode, log a warning
    if (
        space.state.current_temp_c is not None
        and space.state.current_temp_c > 27.0
        and space.controls.mode.value in ("auto", "cool")
    ):
        LOG.warning("[space] %s is above 27°C — check cooling", space.name)


async def on_idu_update(idu: IndoorUnit) -> None:
    global _snapshot
    if _snapshot is not None:
        _snapshot.indoor_units[idu.id] = idu
    LOG.debug("[idu] %s — fan=%s online=%s", idu.id, idu.controls.fan_speed.value, idu.state.is_online)


async def on_connected() -> None:
    LOG.info("Stream connected")


async def on_disconnected() -> None:
    LOG.warning("Stream disconnected; will reconnect automatically")


# ---------------------------------------------------------------------------
# Main coroutine
# ---------------------------------------------------------------------------

async def run() -> None:
    global _snapshot

    store = FileStore()
    async with QuiltClient(EMAIL, token_store=store, snapshot_ttl_s=300) as client:
        LOG.info("Logging in as %s", EMAIL)
        await client.login()

        _snapshot = await client.get_snapshot()
        LOG.info(
            "Snapshot loaded: system=%s rooms=%d idus=%d",
            _snapshot.system_id,
            len(_snapshot.rooms),
            len(_snapshot.indoor_units),
        )

        topics = _snapshot.stream_topics()
        stream = client.stream(topics, max_reconnects=-1, reconnect_delay_s=2.0)
        stream.on_space_update(on_space_update)
        stream.on_indoor_unit_update(on_idu_update)
        stream.on_connected(on_connected)
        stream.on_disconnected(on_disconnected)

        async with stream:
            LOG.info("Daemon running. Send SIGINT or SIGTERM to stop.")
            await _stop.wait()

        LOG.info("Daemon stopped cleanly.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    loop = asyncio.new_event_loop()

    def _handle_signal(sig: signal.Signals) -> None:
        LOG.info("Received %s; shutting down…", sig.name)
        loop.call_soon_threadsafe(_stop.set)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal, sig)

    try:
        loop.run_until_complete(run())
    except Exception:
        LOG.exception("Daemon exited with unhandled error")
        raise
    finally:
        loop.close()


if __name__ == "__main__":
    main()
```

---

## Installing as a systemd service

Create `/etc/systemd/system/quilt-daemon.service`:

```ini
[Unit]
Description=Quilt HP HVAC daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=quilt
Environment=QUILT_EMAIL=you@example.com
ExecStart=/usr/local/bin/quilt-daemon
Restart=on-failure
RestartSec=10s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now quilt-daemon
journalctl -fu quilt-daemon
```

---

## Periodic snapshot refresh

If your daemon needs to verify the in-memory snapshot against server state periodically (e.g., to catch any missed events during a reconnect window), add a refresh task alongside the stream:

```python
async def refresh_loop(client: QuiltClient, interval_s: float = 300.0) -> None:
    """Periodically re-fetch the full snapshot as a consistency check."""
    while not _stop.is_set():
        await asyncio.sleep(interval_s)
        if _stop.is_set():
            break
        try:
            client.invalidate_snapshot()
            fresh = await client.get_snapshot()
            LOG.info("Periodic snapshot refresh: %d rooms", len(fresh.rooms))
            # Replace the global snapshot atomically
            global _snapshot
            _snapshot = fresh
        except Exception:
            LOG.warning("Periodic snapshot refresh failed; will retry next cycle", exc_info=True)
```

Start this as a background task alongside the stream:

```python
async with stream:
    refresh_task = asyncio.create_task(refresh_loop(client))
    await _stop.wait()
    refresh_task.cancel()
    try:
        await refresh_task
    except asyncio.CancelledError:
        pass
```

---

## Handling token expiry in long-running daemons

The library handles token expiry automatically:

- The `_AuthInterceptor` retries unary RPCs once after a silent refresh on `UNAUTHENTICATED`.
- The `NotifierStream` calls `refresh_callback` and reconnects after `UNAUTHENTICATED` on the stream.

For extra resilience in daemons, configure a `TokenRefreshPolicy` that raises immediately (rather than falling back to OTP) so the daemon logs the failure and the systemd watchdog triggers a restart:

```python
from quilt_hp.tokens import TokenRefreshPolicy, TokenRefreshContext, RefreshFailureAction


class DaemonRefreshPolicy:
    def on_refresh_failure(
        self, context: TokenRefreshContext, error: Exception
    ) -> RefreshFailureAction:
        LOG.error(
            "Token refresh failed (attempt=%d source=%s): %s",
            context.attempt,
            context.source,
            error,
        )
        return RefreshFailureAction.RAISE


async with QuiltClient(
    EMAIL,
    token_store=store,
    token_refresh_policy=DaemonRefreshPolicy(),
) as client:
    ...
```

With `RefreshFailureAction.RAISE`, a failed refresh propagates as `QuiltAuthError`, which exits the `async with` block, exits `run()`, and lets the daemon process crash. systemd then restarts it after `RestartSec`.
