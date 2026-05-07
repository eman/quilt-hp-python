"""CLI entry point for quilt-hp-python."""
from __future__ import annotations

import asyncio
import sys

try:
    import typer
    from rich.console import Console
    from rich.tree import Tree
except ImportError:
    print("CLI dependencies not found. Install with: pip install 'quilt-hp-python[cli]'")
    sys.exit(1)

from quilt_hp.cli.store import FileStore
from quilt_hp.client import QuiltClient
from quilt_hp.models.enums import HVACMode, HVACState

app = typer.Typer(help="Quilt HVAC command-line interface.")
console = Console()
_store = FileStore()

def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


def _resolve(email: str | None, home: str | None) -> tuple[str, str | None]:
    """Return (email, home) from args, saved settings, or token cache.

    Saves any newly supplied values back so future invocations can omit them.
    Exits with an error message if email is unavailable.
    """
    settings = _store.load_settings()
    resolved_email = email or settings.get("email")
    resolved_home = home or settings.get("home")

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
    changed: dict[str, object] = {}
    if email and email != settings.get("email"):
        changed["email"] = email
    if home and home != settings.get("home"):
        changed["home"] = home
    if changed:
        _store.update_settings(**changed)

    return resolved_email, resolved_home


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
            except Exception:
                pass

            # Cached tokens absent or expired — prompt for OTP.
            console.print(f"[yellow]✉ OTP sent to {email} — check your email.[/yellow]")
            otp = typer.prompt("Enter OTP code")
            await client.login(otp_callback=lambda _email: otp.strip())
            console.print("[green]✓ Successfully logged in![/green]")
    _run(_login())

@app.command()
def info(
    email: str | None = typer.Option(None, envvar="QUILT_EMAIL", help="Quilt account email"),
    home: str | None = typer.Option(None, help="Specific home name to connect to"),
) -> None:
    """Display the full Home -> Room -> Device hierarchy."""
    email, home = _resolve(email, home)

    async def _info() -> None:
        async with QuiltClient(email, home=home, token_store=_store) as client:
            await client.login()
            snap = await client.get_snapshot()

            tree = Tree("[bold blue]Home[/bold blue]")

            # Home Settings
            home_node = tree.add("[bold]Home Settings[/bold]")
            home_node.add(f"Timezone: {snap.timezone}")

            # Rooms -> IDUs
            rooms_node = tree.add("[bold]Rooms[/bold]")
            for space in snap.rooms:
                space_node = rooms_node.add(f"[green]{space.name}[/green]")

                # Find IDUs for this space
                idus = [idu for idu in snap.indoor_units if idu.space_id == space.id]
                for idu in idus:
                    mode = HVACMode(idu.state.hvac_mode).name
                    state = HVACState(idu.state.hvac_state).name
                    idu_node = space_node.add(f"[cyan]IDU {idu.id[:8]}[/cyan]")

                    # IDU Telemetry
                    telemetry_node = idu_node.add("[dim]Telemetry[/dim]")
                    telemetry_node.add(f"Ambient: {idu.state.ambient_temperature_c:.1f}°C")
                    telemetry_node.add(f"Humidity: {idu.state.ambient_humidity_percent:.0f}%")
                    telemetry_node.add(f"Mode/State: {mode} / {state}")

                    if idu.performance_data and (idu.performance_data.coil_temperature_c or idu.performance_data.actual_fan_speed_rpm):
                        pd = idu.performance_data
                        telemetry_node.add(f"Coil: {pd.coil_temperature_c:.1f}°C")
                        telemetry_node.add(f"Fan: {pd.actual_fan_speed_rpm:.0f} RPM")
                    if idu.occupancy and idu.occupancy.occupancy_state:
                        telemetry_node.add(f"Occupancy: {idu.occupancy.occupancy_state}")

            # Outdoor Units
            odu_node = tree.add("[bold]Outdoor Units[/bold]")
            for odu in snap.outdoor_units:
                node = odu_node.add(f"[cyan]{odu.model_sku or 'ODU'}[/cyan] ({odu.serial_number or odu.id[:8]})")
                if odu.performance_data and odu.performance_data.compressor_frequency_hz:
                    pd = odu.performance_data
                    node.add(f"Freq: {pd.compressor_frequency_hz}Hz, Coil: {pd.coil_temperature_c:.1f}°C, Amb: {pd.ambient_temperature_c:.1f}°C")

            # Controllers
            ctrl_node = tree.add("[bold]Controllers (Dials)[/bold]")
            for ctrl in snap.controllers:
                node = ctrl_node.add(f"[cyan]{ctrl.name}[/cyan]")
                node.add(f"Ambient: {ctrl.ambient_temperature_c:.1f}°C")
                if ctrl.pcb_temperature_a_c:
                    node.add(f"PCB-A: {ctrl.pcb_temperature_a_c:.1f}°C / PCB-B: {ctrl.pcb_temperature_b_c:.1f}°C")

            console.print(tree)
    _run(_info())

@app.command()
def presets(
    email: str | None = typer.Option(None, envvar="QUILT_EMAIL", help="Quilt account email"),
    home: str | None = typer.Option(None, help="Specific home name to connect to"),
) -> None:
    """List all comfort setting presets."""
    email, home = _resolve(email, home)

    async def _presets() -> None:
        async with QuiltClient(email, home=home, token_store=_store) as client:
            await client.login()
            settings = await client.list_comfort_settings()
            if not settings:
                console.print("No comfort settings found.")
                return

            console.print("\n[bold]═══ Comfort Settings ═══[/bold]")
            for cs in settings:
                mode = cs.hvac_mode.name
                heat = f"{cs.heating_setpoint_c:.1f}°C" if cs.heating_setpoint_c else "--"
                cool = f"{cs.cooling_setpoint_c:.1f}°C" if cs.cooling_setpoint_c else "--"
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
        async with QuiltClient(email, home=home, token_store=_store) as client:
            await client.login()
            snapshot = await client.get_snapshot()

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
    period: str = typer.Option("day", help="Time period: day, week, month"),
) -> None:
    """Show energy consumption metrics."""
    email, home = _resolve(email, home)

    async def _energy() -> None:
        import zoneinfo
        from datetime import datetime, timedelta

        async with QuiltClient(email, home=home, token_store=_store) as client:
            await client.login()
            snapshot = await client.get_snapshot()
            name_by_id = {s.id: s.name for s in snapshot.spaces}

            now = datetime.now(tz=zoneinfo.ZoneInfo(snapshot.timezone or "UTC"))
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)

            if period == "day":
                end = start + timedelta(days=1) - timedelta(seconds=1)
            elif period == "week":
                start = start - timedelta(days=start.weekday())
                end = start + timedelta(weeks=1) - timedelta(seconds=1)
            else:  # month
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
                total = getattr(sm, "total_kwh", 0)
                if total == 0:
                    continue
                console.print(f"  {name:<22}  total={total:.3f} kWh")
    _run(_energy())

@app.command(name="set")
def set_space(
    space_name: str = typer.Argument(..., help="Exact name of the room to update"),
    mode: str | None = typer.Option(None, help="HVAC mode: COOL, HEAT, AUTO, STANDBY"),
    heat: float | None = typer.Option(None, help="Heating setpoint in °C"),
    cool: float | None = typer.Option(None, help="Cooling setpoint in °C"),
    email: str | None = typer.Option(None, envvar="QUILT_EMAIL", help="Quilt account email"),
    home: str | None = typer.Option(None, help="Specific home name to connect to"),
) -> None:
    """Update HVAC mode and setpoints for a room."""
    email, home = _resolve(email, home)

    async def _set() -> None:
        async with QuiltClient(email, home=home, token_store=_store) as client:
            await client.login()
            snap = await client.get_snapshot()

            space = next((s for s in snap.rooms if s.name.lower() == space_name.lower()), None)
            if not space:
                console.print(f"[red]Room {space_name!r} not found.[/red]")
                raise typer.Exit(1)

            hvac_mode = HVACMode[mode.upper()] if mode else None

            await client.set_space(
                space.id,
                mode=hvac_mode,
                heat_setpoint_c=heat,
                cool_setpoint_c=cool
            )
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
        console.print("[red]Textual not installed. Install with `pip install 'quilt-hp-python[cli]'`[/red]")
        sys.exit(1)

    tui_app = QuiltApp(email=email, home=home)
    tui_app.run()

if __name__ == "__main__":
    app()
