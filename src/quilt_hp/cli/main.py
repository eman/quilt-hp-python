"""CLI entry point for quilt-hp-python."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import AsyncIterator, Callable, Coroutine, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict
from enum import StrEnum
from functools import wraps
from typing import Any, Protocol, cast

try:
    import typer
    from rich.console import Console
except ImportError:
    print("CLI dependencies not found. Install with: pip install 'quilt-hp-python[cli]'")
    sys.exit(1)

from quilt_hp import __version__
from quilt_hp.cli.constants import SETPOINT_MAX_C, SETPOINT_MIN_C
from quilt_hp.cli.settings import SettingsStore
from quilt_hp.cli.store import FileStore
from quilt_hp.client import QuiltClient
from quilt_hp.exceptions import QuiltAuthError, QuiltError
from quilt_hp.models.enums import FanSpeed, HVACMode
from quilt_hp.models.system import SystemSnapshot

app = typer.Typer(help="Quilt HVAC command-line interface.")
console = Console()
_store = FileStore()
_settings = SettingsStore()


class OutputMode(StrEnum):
    """Script output format."""

    SUMMARY = "summary"
    JSON = "json"


class EnergyPeriod(StrEnum):
    """Reporting period for the energy command."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"


# User-settable HVAC modes (FALLBACK_* are device-side fallback states).
_SETTABLE_MODES = (
    HVACMode.COOL,
    HVACMode.HEAT,
    HVACMode.AUTO,
    HVACMode.FAN,
    HVACMode.DRY,
    HVACMode.STANDBY,
)


class _EntityWithId(Protocol):
    id: str


def _version_callback(value: bool) -> None:
    if value:
        console.print(__version__)
        raise typer.Exit()


@app.callback()
def _app_callback(
    version: bool = typer.Option(
        False,
        "--version",
        help="Show package version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    _ = version


def _handle_errors[T](
    func: Callable[..., Coroutine[Any, Any, T]],
) -> Callable[..., Coroutine[Any, Any, T]]:
    @wraps(func)
    async def _wrapped(*args: Any, **kwargs: Any) -> T:
        try:
            return await func(*args, **kwargs)
        except QuiltAuthError as exc:
            console.print(f"[red]Authentication failed: {exc}[/red]")
            raise typer.Exit(1) from None
        except QuiltError as exc:
            console.print(f"[red]Error: {exc}[/red]")
            raise typer.Exit(1) from None

    return _wrapped


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    @_handle_errors
    async def _wrapped() -> T:
        return await coro

    return asyncio.run(_wrapped())


@asynccontextmanager
async def _logged_in_client(email: str, home: str | None) -> AsyncIterator[QuiltClient]:
    async with QuiltClient(email, home=home, token_store=_store) as client:
        await client.login()
        yield client


@asynccontextmanager
async def _client_snapshot(
    email: str, home: str | None
) -> AsyncIterator[tuple[QuiltClient, SystemSnapshot]]:
    async with _logged_in_client(email, home) as client:
        yield client, await client.get_snapshot()


def _resolve(email: str | None, home: str | None) -> tuple[str, str | None]:
    """Return (email, home) from args, saved settings, or token cache.

    Saves any newly supplied values back so future invocations can omit them.
    Exits with an error message if email is unavailable.
    """
    settings = _settings.load()
    resolved_email = email or settings.email
    resolved_home = home or settings.home

    # Fall back to token cache: if exactly one account has tokens, use it.
    if not resolved_email:
        cached = _store.list_emails()
        if len(cached) == 1:
            resolved_email = cached[0]

    if not resolved_email:
        console.print(
            "[red]Error:[/red] --email is required on first use.\n"
            "It will be saved automatically and is optional on subsequent runs."
        )
        raise typer.Exit(1)

    # Persist newly supplied values.
    next_email = email if email and email != settings.email else None
    next_home = home if home and home != settings.home else None
    if next_email is not None or next_home is not None:
        _settings.update(email=next_email, home=next_home)

    return resolved_email, resolved_home


def _space_name_by_id(snap: SystemSnapshot) -> dict[str, str]:
    return {space.id: space.name for space in snap.spaces}


def _fmt_c(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}°C"


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}%"


def _fmt_w(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}W"


def _snapshot_payload(snap: SystemSnapshot) -> dict[str, Any]:
    space_names = _space_name_by_id(snap)
    update_refs: dict[str, list[str]] = {}
    update_links: list[tuple[str, str, Sequence[_EntityWithId]]] = [
        ("indoor_unit", "software_update_info_id", snap.indoor_units),
        ("indoor_unit", "firmware_update_info_id", snap.indoor_units),
        ("outdoor_unit", "firmware_update_info_id", snap.outdoor_units),
        ("controller", "software_update_info_id", snap.controllers),
        ("controller", "firmware_update_info_id", snap.controllers),
        ("qsm", "software_update_info_id", snap.quilt_smart_modules),
        ("qsm", "firmware_update_info_id", snap.quilt_smart_modules),
    ]
    for entity_type, field_name, entities in update_links:
        for entity in entities:
            update_id = getattr(entity, field_name, None)
            if not update_id:
                continue
            update_refs.setdefault(update_id, []).append(f"{entity_type}:{entity.id}")

    return {
        "timezone": snap.timezone,
        "spaces": [
            {
                "id": s.id,
                "name": s.name,
                "parent_space_id": s.parent_space_id,
                "is_room": s.is_room,
                "controls": {
                    "hvac_mode": s.controls.hvac_mode.name,
                    "temperature_setpoint_c": s.controls.temperature_setpoint_c,
                    "cooling_setpoint_c": s.controls.cooling_setpoint_c,
                    "heating_setpoint_c": s.controls.heating_setpoint_c,
                    "display_setpoint": s.controls.display_setpoint,
                    "comfort_setting_id": s.controls.comfort_setting_id,
                },
                "state": {
                    "ambient_temperature_c": s.state.ambient_temperature_c,
                    "setpoint_c": s.state.setpoint_c,
                    "hvac_state": s.state.hvac_state.name,
                    "comfort_setting_id": s.state.comfort_setting_id,
                },
            }
            for s in snap.spaces
        ],
        "indoor_units": [
            {
                "id": idu.id,
                "space_id": idu.space_id,
                "space_name": space_names.get(idu.space_id),
                "outdoor_unit_id": idu.outdoor_unit_id,
                "qsm_id": idu.qsm_id,
                "hardware_id": idu.hardware_id,
                "firmware_update_info_id": idu.firmware_update_info_id,
                "controls": {
                    "fan_speed": idu.controls.fan_speed.name,
                    "louver_mode": idu.controls.louver_mode.name,
                    "led_on": idu.led_on,
                    "led_brightness": idu.controls.led_brightness,
                },
                "state": {
                    "hvac_mode": idu.state.hvac_mode.name,
                    "hvac_state": idu.state.hvac_state.name,
                    "ambient_temperature_c": idu.state.ambient_temperature_c,
                    "ambient_humidity_percent": idu.state.ambient_humidity_percent,
                    "temperature_setpoint_c": idu.state.temperature_setpoint_c,
                },
                "performance_data": (
                    {
                        "coil_temperature_c": idu.performance_data.coil_temperature_c,
                        "actual_fan_speed_rpm": idu.performance_data.actual_fan_speed_rpm,
                    }
                    if idu.performance_data
                    else None
                ),
                "occupancy_state": idu.effective_occupancy_state,
            }
            for idu in snap.indoor_units
        ],
        "outdoor_units": [
            {
                "id": odu.id,
                "space_id": odu.space_id,
                "space_name": space_names.get(odu.space_id),
                "model_sku": odu.model_sku,
                "serial_number": odu.serial_number,
                "firmware_version": odu.firmware_version,
                "firmware_update_info_id": odu.firmware_update_info_id,
                "performance_data": (
                    {
                        "compressor_frequency_hz": odu.performance_data.compressor_frequency_hz,
                        "ambient_temperature_c": odu.performance_data.ambient_temperature_c,
                        "coil_temperature_c": odu.performance_data.coil_temperature_c,
                    }
                    if odu.performance_data
                    else None
                ),
            }
            for odu in snap.outdoor_units
        ],
        "controllers": [
            {
                "id": ctrl.id,
                "space_id": ctrl.space_id,
                "space_name": space_names.get(ctrl.space_id),
                "name": ctrl.name,
                "ambient_temperature_c": ctrl.ambient_temperature_c,
                "raw_thermistor_c": ctrl.raw_thermistor_c,
                "remote_sensor_mode": ctrl.remote_sensor_mode.name,
                "local_comms_health": ctrl.local_comms_health.name,
                "software_update_info_id": ctrl.software_update_info_id,
                "firmware_update_info_id": ctrl.firmware_update_info_id,
                "serial_number": ctrl.serial_number,
                "model_sku": ctrl.model_sku,
            }
            for ctrl in snap.controllers
        ],
        "remote_sensors": [
            {
                "id": rs.id,
                "indoor_unit_id": rs.indoor_unit_id,
                "ambient_temperature_c": rs.ambient_temperature_c,
                "humidity_percent": rs.humidity_percent,
                "battery_level_percent": rs.battery_level_percent,
                "signal_level_dbm": rs.signal_level_dbm,
                "control_mode": rs.control_mode.name,
            }
            for rs in snap.remote_sensors
        ],
        "controller_remote_sensors": [
            {
                "id": rs.id,
                "controller_id": rs.controller_id,
                "ambient_temperature_c": rs.ambient_temperature_c,
                "humidity_percent": rs.humidity_percent,
                "battery_level_percent": rs.battery_level_percent,
                "signal_level_dbm": rs.signal_level_dbm,
                "control_mode": rs.control_mode.name,
            }
            for rs in snap.controller_remote_sensors
        ],
        "quilt_smart_modules": [
            {
                "id": qsm.id,
                "software_update_info_id": qsm.software_update_info_id,
                "firmware_update_info_id": qsm.firmware_update_info_id,
                "local_comms_health": qsm.local_comms_health.name,
                "sensors": (
                    {
                        "phase_detected_raw": qsm.sensors.phase_detected_raw,
                        "target_detected_raw": qsm.sensors.target_detected_raw,
                        "als_illuminance_raw": qsm.sensors.als_illuminance_raw,
                        "accel_x_raw": qsm.sensors.accel_x_raw,
                        "accel_y_raw": qsm.sensors.accel_y_raw,
                        "accel_z_raw": qsm.sensors.accel_z_raw,
                    }
                    if qsm.sensors
                    else None
                ),
            }
            for qsm in snap.quilt_smart_modules
        ],
        "software_update_infos": [
            {
                "id": sui.id,
                "state": sui.state,
                "status": sui.status,
                "current_version": sui.current_version,
                "target_version": sui.target_version,
                "current_progress": sui.current_progress,
                "total_progress": sui.total_progress,
                "progress_unit": sui.progress_unit,
                "linked_entities": update_refs.get(sui.id, []),
            }
            for sui in snap.software_update_infos
        ],
        "update_entities": [
            {"topic": topic, "entity_type": topic.split("/")[1], "id": topic.split("/")[2]}
            for topic in snap.stream_topics()
        ],
    }


def _print_snapshot_summary(data: dict[str, Any]) -> None:
    console.print("[bold]Spaces[/bold]")
    for space in data["spaces"]:
        controls = space["controls"]
        state = space["state"]
        console.print(
            f"  {space['name']} ({space['id']}) "
            f"mode={controls['hvac_mode']} "
            f"setpoint={controls['display_setpoint']} "
            f"ambient={state['ambient_temperature_c']}°C"
        )

    console.print("\n[bold]Indoor Units[/bold]")
    for idu in data["indoor_units"]:
        st = idu["state"]
        console.print(
            f"  {idu['id']} space={idu['space_name'] or idu['space_id']} "
            f"mode={st['hvac_mode']}/{st['hvac_state']} "
            f"ambient={st['ambient_temperature_c']}°C "
            f"humidity={st['ambient_humidity_percent']}%"
        )

    console.print("\n[bold]Outdoor Units[/bold]")
    for odu in data["outdoor_units"]:
        console.print(
            f"  {odu['id']} model={odu['model_sku'] or '--'} serial={odu['serial_number'] or '--'}"
        )

    console.print("\n[bold]Controllers[/bold]")
    for ctrl in data["controllers"]:
        lc = ctrl.get("local_comms_health", "UNSPECIFIED")
        lc_str = f" local={lc}" if lc not in ("UNSPECIFIED", "HEALTHY") else ""
        console.print(
            f"  {ctrl['name']} ({ctrl['id']}) space={ctrl['space_name'] or ctrl['space_id']} "
            f"ambient={ctrl['ambient_temperature_c']}°C{lc_str}"
        )

    console.print("\n[bold]Remote Sensors[/bold]")
    for rs in data["remote_sensors"]:
        console.print(
            f"  {rs['id']} idu={rs['indoor_unit_id']} "
            f"temp={rs['ambient_temperature_c']}°C humidity={rs['humidity_percent']}%"
        )

    console.print("\n[bold]Controller Remote Sensors[/bold]")
    for rs in data["controller_remote_sensors"]:
        console.print(
            f"  {rs['id']} controller={rs['controller_id']} "
            f"temp={rs['ambient_temperature_c']}°C humidity={rs['humidity_percent']}%"
        )

    console.print("\n[bold]QSMs[/bold]")
    for qsm in data["quilt_smart_modules"]:
        console.print(f"  {qsm['id']}")

    console.print("\n[bold]Software Update Entities[/bold]")
    for sui in data["software_update_infos"]:
        links = ",".join(sui["linked_entities"]) or "--"
        console.print(f"  {sui['id']} linked={links}")

    console.print("\n[bold]Update Topics[/bold]")
    for topic in data["update_entities"]:
        console.print(f"  {topic['topic']}")


def _emit_output(mode: OutputMode, payload: dict[str, Any]) -> None:
    if mode == OutputMode.JSON:
        console.print(json.dumps(payload, indent=2, sort_keys=True))
        return
    _print_snapshot_summary(payload)


@app.command()
def login(
    email: str | None = typer.Option(None, envvar="QUILT_EMAIL", help="Quilt account email"),
    home: str | None = typer.Option(None, help="Specific home name to connect to"),
) -> None:
    """Authenticate with Quilt."""
    email, home = _resolve(email, home)

    async def _login() -> None:
        async with QuiltClient(email, home=home, token_store=_store) as client:
            # Try silent login first (uses cached/refreshed token, no OTP).
            try:
                await client.login()
                console.print(f"[green]✓ Already logged in as {email}[/green]")
                return
            except QuiltAuthError:
                pass  # expected — cached tokens absent/expired, proceed to OTP

            # Cached tokens absent/expired — trigger OTP flow and prompt.
            async def _prompt_for_otp(challenge_email: str) -> str:
                console.print(
                    f"[yellow]✉ OTP sent to {challenge_email} — check your email.[/yellow]"
                )
                # typer.prompt blocks on stdin — run it off the event loop.
                code = await asyncio.to_thread(typer.prompt, "Enter OTP code")
                return cast("str", code).strip()

            await client.login(otp_callback=_prompt_for_otp)
            console.print("[green]✓ Successfully logged in![/green]")

    _run(_login())


@app.command()
def info(
    email: str | None = typer.Option(None, envvar="QUILT_EMAIL", help="Quilt account email"),
    home: str | None = typer.Option(None, help="Specific home name to connect to"),
    output: OutputMode = typer.Option(  # noqa: B008
        OutputMode.SUMMARY,
        "--output",
        "-o",
        help="Output mode: summary or json",
    ),
) -> None:
    """Display complete system inventory + telemetry."""
    email, home = _resolve(email, home)

    async def _info() -> None:
        async with _client_snapshot(email, home) as (_, snap):
            _emit_output(output, _snapshot_payload(snap))

    _run(_info())


@app.command()
def devices(
    email: str | None = typer.Option(None, envvar="QUILT_EMAIL", help="Quilt account email"),
    home: str | None = typer.Option(None, help="Specific home name to connect to"),
    output: OutputMode = typer.Option(  # noqa: B008
        OutputMode.SUMMARY,
        "--output",
        "-o",
        help="Output mode: summary or json",
    ),
) -> None:
    """List all device/entity IDs, including update entities."""
    email, home = _resolve(email, home)

    async def _devices() -> None:
        async with _client_snapshot(email, home) as (_, snapshot):
            payload = _snapshot_payload(snapshot)
            device_payload = {
                "spaces": [{"id": s["id"], "name": s["name"]} for s in payload["spaces"]],
                "indoor_units": [
                    {"id": i["id"], "space_id": i["space_id"]} for i in payload["indoor_units"]
                ],
                "outdoor_units": [
                    {"id": o["id"], "space_id": o["space_id"]} for o in payload["outdoor_units"]
                ],
                "controllers": [
                    {"id": c["id"], "space_id": c["space_id"]} for c in payload["controllers"]
                ],
                "remote_sensors": [
                    {"id": r["id"], "indoor_unit_id": r["indoor_unit_id"]}
                    for r in payload["remote_sensors"]
                ],
                "controller_remote_sensors": [
                    {"id": r["id"], "controller_id": r["controller_id"]}
                    for r in payload["controller_remote_sensors"]
                ],
                "quilt_smart_modules": [{"id": q["id"]} for q in payload["quilt_smart_modules"]],
                "software_update_infos": [
                    {"id": u["id"]} for u in payload["software_update_infos"]
                ],
                "update_entities": payload["update_entities"],
            }
            if output == OutputMode.JSON:
                console.print(json.dumps(device_payload, indent=2, sort_keys=True))
                return

            for key, items in device_payload.items():
                console.print(f"[bold]{key.replace('_', ' ').title()}[/bold]")
                for item in items:
                    left = item["id"]
                    refs = ", ".join(
                        f"{k}={v}" for k, v in item.items() if k != "id" and v is not None
                    )
                    console.print(f"  {left}{f' ({refs})' if refs else ''}")

    _run(_devices())


@app.command()
def values(
    email: str | None = typer.Option(None, envvar="QUILT_EMAIL", help="Quilt account email"),
    home: str | None = typer.Option(None, help="Specific home name to connect to"),
    output: OutputMode = typer.Option(  # noqa: B008
        OutputMode.SUMMARY,
        "--output",
        "-o",
        help="Output mode: summary or json",
    ),
) -> None:
    """Show current sensor values and HVAC control setpoints."""
    email, home = _resolve(email, home)

    async def _values() -> None:
        async with _client_snapshot(email, home) as (_, snapshot):
            payload = _snapshot_payload(snapshot)
            value_payload = {
                "spaces": [
                    {
                        "id": s["id"],
                        "name": s["name"],
                        "ambient_temperature_c": s["state"]["ambient_temperature_c"],
                        "hvac_mode": s["controls"]["hvac_mode"],
                        "hvac_state": s["state"]["hvac_state"],
                        "display_setpoint": s["controls"]["display_setpoint"],
                        "temperature_setpoint_c": s["controls"]["temperature_setpoint_c"],
                        "cooling_setpoint_c": s["controls"]["cooling_setpoint_c"],
                        "heating_setpoint_c": s["controls"]["heating_setpoint_c"],
                    }
                    for s in payload["spaces"]
                ],
                "indoor_units": [
                    {
                        "id": i["id"],
                        "space_id": i["space_id"],
                        "ambient_temperature_c": i["state"]["ambient_temperature_c"],
                        "ambient_humidity_percent": i["state"]["ambient_humidity_percent"],
                        "temperature_setpoint_c": i["state"]["temperature_setpoint_c"],
                        "fan_speed": i["controls"]["fan_speed"],
                    }
                    for i in payload["indoor_units"]
                ],
                "outdoor_units": [
                    {"id": o["id"], "performance_data": o["performance_data"]}
                    for o in payload["outdoor_units"]
                ],
                "controllers": [
                    {
                        "id": c["id"],
                        "name": c["name"],
                        "ambient_temperature_c": c["ambient_temperature_c"],
                        "raw_thermistor_c": c["raw_thermistor_c"],
                    }
                    for c in payload["controllers"]
                ],
                "remote_sensors": payload["remote_sensors"],
                "controller_remote_sensors": payload["controller_remote_sensors"],
                "quilt_smart_modules": [
                    {"id": q["id"], "sensors": q["sensors"]}
                    for q in payload["quilt_smart_modules"]
                ],
            }
            if output == OutputMode.JSON:
                console.print(json.dumps(value_payload, indent=2, sort_keys=True))
                return

            console.print("[bold]Spaces[/bold]")
            for space in value_payload["spaces"]:
                console.print(
                    f"  {space['name']} ({space['id']}) "
                    f"ambient={space['ambient_temperature_c']}°C "
                    f"setpoint={space['display_setpoint']} "
                    f"mode/state={space['hvac_mode']}/{space['hvac_state']}"
                )
            console.print("\n[bold]Indoor Units[/bold]")
            for idu in value_payload["indoor_units"]:
                console.print(
                    f"  {idu['id']} space={idu['space_id']} "
                    f"ambient={idu['ambient_temperature_c']}°C "
                    f"humidity={idu['ambient_humidity_percent']}% "
                    f"setpoint={idu['temperature_setpoint_c']}°C "
                    f"fan={idu['fan_speed']}"
                )

            console.print("\n[bold]Outdoor Units[/bold]")
            for odu in value_payload["outdoor_units"]:
                perf = odu["performance_data"] or {}
                console.print(
                    f"  {odu['id']} compressor={perf.get('compressor_frequency_hz')}Hz "
                    f"ambient={perf.get('ambient_temperature_c')}°C "
                    f"coil={perf.get('coil_temperature_c')}°C"
                )

            console.print("\n[bold]Controllers[/bold]")
            for ctrl in value_payload["controllers"]:
                console.print(
                    f"  {ctrl['name']} ({ctrl['id']}) ambient={ctrl['ambient_temperature_c']}°C "
                    f"thermistor={ctrl['raw_thermistor_c']}°C"
                )

            console.print("\n[bold]Remote Sensors[/bold]")
            for rs in value_payload["remote_sensors"]:
                console.print(
                    f"  {rs['id']} idu={rs['indoor_unit_id']} "
                    f"temp={rs['ambient_temperature_c']}°C humidity={rs['humidity_percent']}%"
                )

            console.print("\n[bold]Controller Remote Sensors[/bold]")
            for rs in value_payload["controller_remote_sensors"]:
                console.print(
                    f"  {rs['id']} controller={rs['controller_id']} "
                    f"temp={rs['ambient_temperature_c']}°C humidity={rs['humidity_percent']}%"
                )

            console.print("\n[bold]QSM Sensors[/bold]")
            for qsm in value_payload["quilt_smart_modules"]:
                sensors = qsm["sensors"] or {}
                console.print(
                    f"  {qsm['id']} phase={sensors.get('phase_detected_raw')} "
                    f"target={sensors.get('target_detected_raw')} "
                    f"illuminance={sensors.get('als_illuminance_raw')}"
                )

    _run(_values())


@app.command()
def diagnostics(
    email: str | None = typer.Option(None, envvar="QUILT_EMAIL", help="Quilt account email"),
    home: str | None = typer.Option(None, help="Specific home name to connect to"),
    faults_only: bool = typer.Option(
        False, "--faults-only", help="Only show indoor units with an active fault condition."
    ),
    output: OutputMode = typer.Option(  # noqa: B008
        OutputMode.SUMMARY,
        "--output",
        "-o",
        help="Output mode: summary or json",
    ),
) -> None:
    """Show system diagnostics: fault conditions, refrigerant temps, and power.

    Assembles the installer-style diagnostic view from data the cloud API
    returns on the indoor units. The outdoor unit's own raw sensors (compressor
    Hz, pressures, discharge temp) are withheld from the cloud plane and are not
    shown.
    """
    email, home = _resolve(email, home)

    async def _diagnostics() -> None:
        async with _client_snapshot(email, home) as (_, snapshot):
            diag = snapshot.diagnostics()

            if output == OutputMode.JSON:
                console.print(json.dumps(asdict(diag), indent=2, sort_keys=True, default=str))
                return

            idus = (
                [d for d in diag.indoor_units if d.active_faults]
                if faults_only
                else (diag.indoor_units)
            )
            fault_total = len(diag.active_faults)
            header = (
                f"[red]{fault_total} active fault(s)[/red]"
                if fault_total
                else "[green]No active faults[/green]"
            )
            console.print(f"[bold]Diagnostics[/bold] — {header}\n")

            if not idus:
                console.print("  (no indoor units to show)")

            for d in idus:
                status = "online" if d.online else "[dim]offline[/dim]"
                faults = (
                    "[red]" + ", ".join(d.active_faults) + "[/red]" if d.active_faults else "none"
                )
                name = d.name or d.space_name or d.indoor_unit_id
                console.print(
                    f"[bold]{name}[/bold] ({d.space_name}) — {status}, state={d.hvac_state}"
                )
                console.print(f"    faults: {faults}")
                console.print(
                    "    refrigerant: "
                    f"coil={_fmt_c(d.coil_temperature_c)} "
                    f"gas={_fmt_c(d.gas_pipe_temperature_c)} "
                    f"liquid={_fmt_c(d.liquid_pipe_temperature_c)} "
                    f"inlet={_fmt_c(d.inlet_temperature_c)} "
                    f"outlet={_fmt_c(d.outlet_temperature_c)} "
                    f"humidity={_fmt_pct(d.inlet_humidity_pct)}"
                )
                console.print(f"    power: {_fmt_w(d.hvac_power_w)}\n")

            console.print("[bold]Outdoor Units[/bold]")
            for o in diag.outdoor_units:
                console.print(
                    f"  {o.outdoor_unit_id} state={o.hvac_state} "
                    f"raw_sensors={'yes' if o.raw_sensors_available else 'no (cloud-withheld)'}"
                )

    _run(_diagnostics())


@app.command()
def presets(
    email: str | None = typer.Option(None, envvar="QUILT_EMAIL", help="Quilt account email"),
    home: str | None = typer.Option(None, help="Specific home name to connect to"),
) -> None:
    """List all comfort setting presets."""
    email, home = _resolve(email, home)

    async def _presets() -> None:
        async with _logged_in_client(email, home) as client:
            settings = await client.list_comfort_settings()
            if not settings:
                console.print("No comfort settings found.")
                return

            console.print("\n[bold]═══ Comfort Settings ═══[/bold]")
            for cs in settings:
                mode = cs.hvac_mode.name
                heat = (
                    f"{cs.heating_setpoint_c:.1f}°C" if cs.heating_setpoint_c is not None else "--"
                )
                cool = (
                    f"{cs.cooling_setpoint_c:.1f}°C" if cs.cooling_setpoint_c is not None else "--"
                )
                fan = cs.fan_speed.name
                console.print(f"\n  [cyan]{cs.name}[/cyan] ({cs.type.name})")
                console.print(f"    Mode: {mode}  Heat: {heat}  Cool: {cool}  Fan: {fan}")
            console.print()

    _run(_presets())


@app.command()
def schedules(
    email: str | None = typer.Option(None, envvar="QUILT_EMAIL", help="Quilt account email"),
    home: str | None = typer.Option(None, help="Specific home name to connect to"),
) -> None:
    """List schedules configured for each space."""
    email, home = _resolve(email, home)

    async def _schedules() -> None:
        async with _client_snapshot(email, home) as (_, snapshot):
            cs_by_id = {cs.id: cs for cs in snapshot.comfort_settings}
            day_by_id = {d.id: d for d in snapshot.schedule_days}

            console.print("\n[bold]═══ Schedules ═══[/bold]")
            for week in snapshot.schedule_weeks:
                space = next((s for s in snapshot.spaces if s.id == week.space_id), None)
                space_name = space.name if space else "Unknown Space"
                console.print(f"\n  [green][{space_name}][/green]")

                seen_days = set()
                for wd in week.days:
                    if wd.day_id in seen_days:
                        continue
                    seen_days.add(wd.day_id)
                    day = day_by_id.get(wd.day_id)
                    if not day:
                        continue

                    wdays = [w.weekday_name for w in week.days if w.day_id == day.id]
                    console.print(f"    [yellow]{', '.join(wdays)}[/yellow]: {day.name}")

                    for ev in day.events:
                        cs = cs_by_id.get(ev.comfort_setting_id)
                        name = cs.name if cs else "Unknown"
                        console.print(f"      {ev.start_time} → [cyan]{name}[/cyan]")
            console.print()

    _run(_schedules())


@app.command()
def energy(
    email: str | None = typer.Option(None, envvar="QUILT_EMAIL", help="Quilt account email"),
    home: str | None = typer.Option(None, help="Specific home name to connect to"),
    period: EnergyPeriod = typer.Option(  # noqa: B008
        EnergyPeriod.DAY,
        help="Time period: day, week, month",
    ),
) -> None:
    """Show energy consumption metrics."""
    email, home = _resolve(email, home)

    async def _energy() -> None:
        import zoneinfo
        from datetime import datetime, timedelta

        async with _client_snapshot(email, home) as (client, snapshot):
            name_by_id = {s.id: s.name for s in snapshot.spaces}

            now = datetime.now(tz=zoneinfo.ZoneInfo(snapshot.timezone or "UTC"))
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)

            if period == EnergyPeriod.DAY:
                end = start + timedelta(days=1) - timedelta(seconds=1)
            elif period == EnergyPeriod.WEEK:
                start = start - timedelta(days=start.weekday())
                end = start + timedelta(weeks=1) - timedelta(seconds=1)
            else:  # EnergyPeriod.MONTH
                start = start.replace(day=1)
                if start.month == 12:
                    end = start.replace(year=start.year + 1, month=1) - timedelta(seconds=1)
                else:
                    end = start.replace(month=start.month + 1) - timedelta(seconds=1)

            metrics = await client.get_energy(start, end)
            header = f"{start.strftime('%b %d')} - {end.strftime('%b %d %Y')}"
            console.print(f"\n  [bold][{period.upper()}][/bold] {header}\n")
            for sm in metrics:
                name = name_by_id.get(sm.space_id, sm.space_id[:8])
                total = sm.total_kwh
                if total == 0:
                    continue
                console.print(f"  {name:<22}  total={total:.3f} kWh")

    _run(_energy())


@app.command(name="set")
def set_space(
    space_name: str = typer.Argument(..., help="Exact name of the room to update"),
    mode: str | None = typer.Option(None, help="HVAC mode: COOL, HEAT, AUTO, FAN, DRY, STANDBY"),
    heat: float | None = typer.Option(
        None,
        min=SETPOINT_MIN_C,
        max=SETPOINT_MAX_C,
        help=f"Heating setpoint in °C ({SETPOINT_MIN_C:.0f}–{SETPOINT_MAX_C:.0f})",
    ),
    cool: float | None = typer.Option(
        None,
        min=SETPOINT_MIN_C,
        max=SETPOINT_MAX_C,
        help=f"Cooling setpoint in °C ({SETPOINT_MIN_C:.0f}–{SETPOINT_MAX_C:.0f})",
    ),
    fan: str | None = typer.Option(None, help="Fan speed: AUTO, QUIET, LOW, MEDIUM, HIGH, BLAST"),
    email: str | None = typer.Option(None, envvar="QUILT_EMAIL", help="Quilt account email"),
    home: str | None = typer.Option(None, help="Specific home name to connect to"),
) -> None:
    """Update HVAC mode and setpoints for a room."""
    if mode is None and heat is None and cool is None and fan is None:
        console.print(
            "[red]Nothing to update:[/red] provide at least one of --mode, --heat, --cool, --fan."
        )
        raise typer.Exit(1)

    email, home = _resolve(email, home)

    if mode:
        try:
            hvac_mode: HVACMode | None = HVACMode[mode.upper()]
            if hvac_mode not in _SETTABLE_MODES:
                raise KeyError(mode)
        except KeyError:
            valid = ", ".join(m.name.lower() for m in _SETTABLE_MODES)
            console.print(f"[red]Invalid mode {mode!r}. Valid: {valid}[/red]")
            raise typer.Exit(1) from None
    else:
        hvac_mode = None

    async def _set() -> None:
        async with _client_snapshot(email, home) as (client, snap):
            space = next(
                (s for s in snap.rooms if s.name.lower() == space_name.lower()),
                None,
            )
            if not space:
                console.print(f"[red]Room {space_name!r} not found.[/red]")
                raise typer.Exit(1)

            if fan:
                try:
                    fan_speed: FanSpeed | None = FanSpeed[fan.upper()]
                except KeyError:
                    valid = ", ".join(f.name.lower() for f in FanSpeed)
                    console.print(f"[red]Invalid fan speed {fan!r}. Valid: {valid}[/red]")
                    raise typer.Exit(1) from None
            else:
                fan_speed = None

            if hvac_mode is not None or heat is not None or cool is not None:
                await client.set_space(
                    space.id,
                    mode=hvac_mode,
                    heat_setpoint_c=heat,
                    cool_setpoint_c=cool,
                )

            if fan_speed is not None:
                idus = snap.indoor_units_for_space(space)
                if not idus:
                    console.print(
                        f"[red]No indoor unit found for {space.name}; cannot set fan speed.[/red]"
                    )
                    raise typer.Exit(1)
                for idu in idus:
                    await client.set_indoor_unit(idu.id, fan_speed=fan_speed)

            console.print(f"[green]✓ Updated {space.name}[/green]")

    _run(_set())


@app.command()
def tui(
    email: str | None = typer.Option(None, envvar="QUILT_EMAIL", help="Quilt account email"),
    home: str | None = typer.Option(None, help="Specific home name to connect to"),
) -> None:
    """Launch the interactive terminal UI for live streaming."""
    email, home = _resolve(email, home)

    try:
        from quilt_hp.cli.tui import QuiltApp
    except ImportError:
        console.print(
            "[red]Textual not installed. Install with `pip install 'quilt-hp-python[cli]'`[/red]"
        )
        sys.exit(1)

    tui_app = QuiltApp(email=email, home=home)
    tui_app.run()


if __name__ == "__main__":
    app()
