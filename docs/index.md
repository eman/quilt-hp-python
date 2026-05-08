# quilt-hp-python

**quilt-hp-python** is an async Python client library for [Quilt](https://www.quilt.com/) mini-split HVAC systems. It communicates with the Quilt cloud API over gRPC and gives you full programmatic control of your Quilt installation: read temperatures, change HVAC modes and setpoints, configure comfort presets, manage schedules, query energy metrics, and stream real-time updates as changes happen.

## What you can do with it

- **Read system state:** Fetch a complete `SystemSnapshot` with all spaces, indoor units, outdoor units, controllers, sensors, comfort settings, and schedules in one call.
- **Control spaces:** Set HVAC mode (`HEAT`, `COOL`, `AUTO`, `STANDBY`, `FAN`) and heating or cooling setpoints for each room.
- **Control indoor units:** Set fan speed, louver mode, LED color and brightness, and presence-detection fence geometry.
- **Manage comfort presets:** Create and update named comfort settings (Active, Sleep, Away, and others) with their own mode, setpoints, and fan speed.
- **Manage schedules:** Create, update, and delete schedule-day programs and schedule-week mappings.
- **Monitor energy use:** Query hourly per-space energy consumption for any time range.
- **Stream real-time updates:** Subscribe to live change events for spaces, indoor units, outdoor units, controllers, remote sensors, and more. The bidirectional gRPC stream reconnects automatically.
- **Use the CLI and TUI:** Work with the bundled command-line interface (`quilt login`, `quilt devices`, `quilt set`, `quilt stream`, `quilt tui`, and more) for interactive use and shell scripting.

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

On subsequent runs, the cached refresh token is used automatically, so there is no OTP prompt unless the session expires. Use a `token_store` (for example, the `FileStore` that ships with the CLI) to persist tokens across processes.

## Token persistence

```python
from quilt_hp import QuiltClient
from quilt_hp.cli.store import FileStore

store = FileStore()  # persists to ~/.config/quilt-hp/tokens.json

async with QuiltClient("you@example.com", token_store=store) as client:
    await client.login(otp_callback=lambda email: input(f"OTP for {email}: "))
    # ... tokens are now saved; next run won't need OTP
```

## Core concepts

**`QuiltClient`** is the single entry point. It handles authentication, manages the gRPC channel lifecycle, and exposes all high-level methods. Use it as an async context manager so the channel is properly closed.

**`SystemSnapshot`** is the full in-memory model of a system. Call `get_snapshot()` to fetch one. It contains lists of `Space`, `IndoorUnit`, `OutdoorUnit`, `Controller`, `ComfortSetting`, `ScheduleDay`, `ScheduleWeek`, `RemoteSensor`, and more. Snapshot data is the starting point for almost every read operation.

**`NotifierStream`** is the real-time update channel. Register callbacks on it with `on_space_update()`, `on_indoor_unit_update()`, and related methods. The callbacks run whenever the server pushes a change. The stream reconnects automatically with exponential back-off.

## Documentation structure

The documentation follows the [Diátaxis](https://diataxis.fr/) framework, organised into four quadrants:

- **Tutorial:** A hands-on learning path for newcomers. Start here if you've never used the library before.
- **How-to guides:** Step-by-step recipes for specific tasks. Use these when you know what you want to do and need to know how.
- **Reference:** API documentation for parameters, return types, and other details you need to look up.
- **Explanation:** Background, context, and design rationale. Read these when you want to understand *why* something works the way it does.

## Documentation sections

- **[Tutorial: Get started](tutorial/get-started.md):** Build a working script that logs in, reads rooms, controls a space, and streams live updates.
- **How-to guides:** [Authenticate and manage tokens](how-to/authenticate.md) · [Control spaces and indoor units](how-to/control-spaces.md) · [Stream real-time updates](how-to/stream-updates.md) · [Build a Home Assistant component](how-to/home-assistant.md) · [Build an automation daemon](how-to/automation-daemon.md) · [Automate with the CLI](how-to/cli-scripting.md) · and more.
- **[Reference: QuiltClient](reference/client.md):** Complete API reference for every method, parameter, and return type.
- **[Explanation: Architecture](explanation/architecture.md):** Why the library is layered the way it is, the async-first constraint, and the injection design.
