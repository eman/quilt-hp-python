# quilt-hp-python

**quilt-hp-python** is an async Python client library for [Quilt](https://www.quilt.com/) mini-split HVAC systems. It communicates with the Quilt cloud API over gRPC and gives you full programmatic control of your Quilt installation: read temperatures, change HVAC modes and setpoints, configure comfort presets, manage schedules, query energy metrics, and stream real-time updates as changes happen.

## What you can do with it

- **Read system state** — fetch a complete `SystemSnapshot` containing all spaces, indoor units, outdoor units, controllers, sensors, comfort settings, and schedules in a single call.
- **Control spaces** — set HVAC mode (`HEAT`, `COOL`, `AUTO`, `STANDBY`, `FAN`) and heating/cooling setpoints per room.
- **Control indoor units** — set fan speed, louver mode, LED color and brightness, and presence-detection fence geometry.
- **Manage comfort presets** — create and update named comfort settings (Active, Sleep, Away, etc.) with their own mode, setpoints, and fan speed.
- **Schedule management** — create, update, and delete schedule-day programs and schedule-week mappings.
- **Energy monitoring** — query hourly per-space energy consumption for any time range.
- **Real-time streaming** — subscribe to live change events for spaces, indoor units, outdoor units, controllers, remote sensors, and more via a bidirectional gRPC stream that reconnects automatically.
- **CLI and TUI** — a bundled command-line interface (`quilt login`, `quilt devices`, `quilt set`, `quilt stream`, `quilt tui`, and more) for interactive use and shell scripting.

## Installation

```bash
pip install quilt-hp-python
```

For the CLI and TUI:

```bash
pip install 'quilt-hp-python[cli]'
```

## Quick start

```python
import asyncio
from quilt_hp import QuiltClient

async def main() -> None:
    async with QuiltClient("you@example.com") as client:
        # First run: Quilt sends an OTP to your email.
        await client.login(otp_callback=lambda email: input(f"OTP for {email}: "))

        # List all rooms with their current temperature and mode.
        for space in await client.list_spaces():
            temp = space.state.ambient_temperature_c
            mode = space.controls.hvac_mode
            print(f"{space.name}: {temp:.1f}°C, mode={mode}")

asyncio.run(main())
```

On subsequent runs the cached refresh token is used automatically — no OTP prompt unless the session expires. Use a `token_store` (e.g. the `FileStore` that ships with the CLI) to persist tokens across processes.

## Token persistence

```python
from quilt_hp import QuiltClient
from quilt_hp.cli.store import FileStore

store = FileStore()  # persists to ~/.config/quilt-hp/tokens.json

async with QuiltClient("you@example.com", token_store=store) as client:
    await client.login(otp_callback=lambda email: input(f"OTP for {email}: "))
    # ... tokens are now saved; next run won't need OTP
```

## Key concepts

**`QuiltClient`** is the single entry point. It handles authentication, manages the gRPC channel lifecycle, and exposes all high-level methods. Use it as an async context manager so the channel is properly closed.

**`SystemSnapshot`** is the full in-memory model of a system. Call `get_snapshot()` to fetch one. It contains lists of `Space`, `IndoorUnit`, `OutdoorUnit`, `Controller`, `ComfortSetting`, `ScheduleDay`, `ScheduleWeek`, `RemoteSensor`, and more. Snapshot data is the starting point for almost every read operation.

**`NotifierStream`** is the real-time update channel. Register callbacks on it with `on_space_update()`, `on_indoor_unit_update()`, etc. and the callbacks are fired whenever the server pushes a change. The stream reconnects automatically with exponential back-off.

## Documentation sections

- **[Architecture](architecture/index.md)** — layered design, snapshot vs. stream data model, channel lifecycle.
- **[Protocol](protocol/index.md)** — gRPC transport, Cognito auth flow, protobuf artifacts, streaming wire format.
- **[Python API](python-api/index.md)** — usage patterns, complete API reference, token management, examples.
- **[Integrations](integrations/index.md)** — Home Assistant, automation daemons, CLI scripting, TUI apps.
- **[Contributing](contributing/index.md)** — development setup, quality gates, docs and protocol update process.
