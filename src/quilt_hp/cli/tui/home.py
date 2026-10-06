"""Home screen: every room at a glance, the selected room's summary, and what needs attention."""

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from rich.text import Text
from textual import on, work
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static
from textual.widgets.data_table import ColumnKey

from quilt_hp.cli.tui.base import SnapshotHost
from quilt_hp.cli.tui.controls import next_mode, nudge_setpoint, room_lock, send_space_change
from quilt_hp.cli.tui.dialogs import ConfirmScreen
from quilt_hp.cli.tui.format import _fmt_state, _tc
from quilt_hp.cli.tui.render import (
    MODE_WORDS,
    SEVERITY_MARK,
    people_text,
    room_summary,
    target_text,
)
from quilt_hp.cli.tui.shared import _set_schedule_paused, room_screen_for
from quilt_hp.cli.tui.views import (
    AttentionItem,
    RoomView,
    Severity,
    attention_items,
    room_views,
    system_tz,
)

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from quilt_hp.client import QuiltClient
    from quilt_hp.models.system import SystemSnapshot

logger = logging.getLogger(__name__)

# Fixed widths keep the table steady as live values change; together they fit 100 columns.
_ROOM_COLUMNS: tuple[tuple[str, int | None], ...] = (
    ("Now", 7),
    ("RH", 4),
    ("Target", 14),
    ("Doing", 13),
    ("People", 7),
    ("Today", 9),
    ("Alerts", None),  # takes the rest
)


class HomeScreen(Screen[None]):
    """The first screen: rooms table, selected-room summary and the attention list."""

    DEFAULT_CSS = """
    HomeScreen #home-strip { height: 1; padding: 0 1; color: $text-muted; }
    HomeScreen #home-rooms {
        height: auto; max-height: 50%; margin: 0 1; scrollbar-size-horizontal: 0;
    }
    HomeScreen #home-bottom { height: 1fr; margin: 1 1 0 1; }
    HomeScreen .home-panel {
        width: 1fr; height: 100%; padding: 0 1;
        border: round $primary-darken-2; border-title-color: $text;
    }
    HomeScreen #home-summary { margin-right: 1; }
    """
    BINDINGS: ClassVar = [
        Binding("enter", "open_room", "Open"),
        Binding("m", "cycle_mode", "Mode"),
        Binding("plus,equals_sign", "setpoint(1)", "+ Setpoint", key_display="+"),
        Binding("minus", "setpoint(-1)", "− Setpoint", key_display="−"),
        Binding("d", "devices", "Devices"),
        Binding("e", "energy", "Energy"),
        Binding("P", "toggle_schedules", "Pause/resume schedules", show=False),
        Binding("r", "refresh", "Refresh"),
        Binding("u", "toggle_units", "°C/°F"),
    ]

    def __init__(self, snapshot: SystemSnapshot, client: QuiltClient) -> None:
        super().__init__()
        self._snapshot = snapshot  # fallback when not attached to a QuiltApp
        self._client = client
        self._today_kwh: dict[str, float] | None = None
        self._views: list[RoomView] = []
        self._alerts: list[AttentionItem] = []

    # ── Shared state ────────────────────────────────────────────

    @property
    def snapshot(self) -> SystemSnapshot:
        with contextlib.suppress(Exception):
            app = self.app
            if isinstance(app, SnapshotHost) and app.snapshot is not None:
                return app.snapshot
        return self._snapshot

    @property
    def use_f(self) -> bool:
        with contextlib.suppress(Exception):
            app = self.app
            if isinstance(app, SnapshotHost):
                return app.use_f
        return False

    # ── Layout ──────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="home-strip")
        yield DataTable(id="home-rooms", cursor_type="row", zebra_stripes=False)
        with Horizontal(id="home-bottom"):
            yield Static(id="home-summary", classes="home-panel")
            yield Static(id="home-attention", classes="home-panel")
        yield Footer()

    def on_mount(self) -> None:
        table: DataTable[Any] = self.query_one("#home-rooms", DataTable)
        names = [s.name for s in self.snapshot.rooms]
        table.add_column("Room", key="Room", width=min(max(map(len, names), default=4), 20))
        for column, width in _ROOM_COLUMNS:
            table.add_column(column, key=column, width=width)
        self.query_one("#home-attention", Static).border_title = "Needs attention"
        self.render_all()
        self.query_one("#home-rooms", DataTable).focus()
        self._fetch_energy()
        self.set_interval(60, self._periodic_refresh)
        self.set_interval(600, self._fetch_energy)

    # ── Rendering ───────────────────────────────────────────────

    def render_all(self) -> None:
        """Rebuild every part of the screen from the current snapshot."""
        snap = self.snapshot
        now = datetime.now(tz=UTC)
        self._alerts = attention_items(snap, now)
        self._views = room_views(snap, now, self._alerts)
        self._render_strip()
        self._render_rooms()
        self._render_summary()
        self._render_attention()

    def _render_strip(self) -> None:
        loc = self.snapshot.primary_location
        parts = [
            Text("Schedules paused", style="yellow")
            if loc is not None and loc.schedule_paused
            else Text("Schedules running", style="green")
        ]
        if self._today_kwh is not None:
            parts.append(Text(f"{sum(self._today_kwh.values()):.1f} kWh today"))
        parts.append(Text(f"{len(self._views)} rooms"))
        count = sum(1 for a in self._alerts if a.severity < Severity.INFO)
        if count:
            parts.append(Text(f"{count} need attention", style="yellow"))
        self.query_one("#home-strip", Static).update(Text("  ·  ").join(parts))

    def _render_rooms(self) -> None:
        table: DataTable[Any] = self.query_one("#home-rooms", DataTable)
        selected = self.selected_space_id
        table.columns[ColumnKey("Now")].label = Text(f"Now {'°F' if self.use_f else '°C'}")
        table.clear()
        for view in self._views:
            table.add_row(*self._row(view), key=view.space_id)
        if self._views:
            ids = [v.space_id for v in self._views]
            table.move_cursor(row=ids.index(selected) if selected in ids else 0)

    def _row(self, v: RoomView) -> tuple[Text, ...]:
        today = self._today_kwh.get(v.space_id) if self._today_kwh is not None else None
        alert = Text("")
        if v.alerts:
            mark, style = SEVERITY_MARK[v.alerts[0].severity]
            short = v.alerts[0].title.removeprefix(v.name).strip(" :")
            more = f" +{len(v.alerts) - 1}" if len(v.alerts) > 1 else ""
            alert = Text(f"{mark} {short}{more}", style=style)
        return (
            Text(v.name, style="bold"),
            Text(self._deg(v.temp_c), style="green" if v.temp_c is not None else "dim"),
            Text(f"{v.humidity_percent:.0f}%" if v.humidity_percent is not None else "–"),
            target_text(v, self._deg),
            _fmt_state(v.hvac_state),
            people_text(v.occupancy),
            Text(
                f"{today:.2f} kWh" if today is not None else "–",
                style="dim" if today is None else "",
            ),
            alert,
        )

    def _render_summary(self) -> None:
        panel = self.query_one("#home-summary", Static)
        view = self._selected_view()
        if view is None:
            panel.border_title = "Room"
            panel.update(Text("No rooms in this system.", style="dim"))
            return
        panel.border_title = view.name
        panel.update(room_summary(view, self.use_f))

    def _render_attention(self) -> None:
        lines: list[Text] = []
        for item in self._alerts:
            mark, style = SEVERITY_MARK[item.severity]
            lines.append(Text.assemble((f"{mark} ", style), item.title))
            if item.detail:
                lines.append(Text(f"  {item.detail}", style="dim"))
        if not lines:
            lines.append(Text("✓ Nothing needs attention", style="green"))
        self.query_one("#home-attention", Static).update(Text("\n").join(lines))

    def _deg(self, value_c: float | None) -> str:
        return (
            _tc(value_c, self.use_f).removesuffix("F").removesuffix("C")
            if value_c is not None
            else "–"
        )

    # ── Selection ───────────────────────────────────────────────

    @property
    def selected_space_id(self) -> str | None:
        table: DataTable[Any] = self.query_one("#home-rooms", DataTable)
        if not table.row_count:
            return None
        with contextlib.suppress(Exception):
            return str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        return None

    def _selected_view(self) -> RoomView | None:
        space_id = self.selected_space_id
        return next((v for v in self._views if v.space_id == space_id), None)

    @on(DataTable.RowHighlighted, "#home-rooms")
    def _on_highlight(self, _event: DataTable.RowHighlighted) -> None:
        self._render_summary()

    @on(DataTable.RowSelected, "#home-rooms")
    def _on_select(self, _event: DataTable.RowSelected) -> None:
        self.action_open_room()

    # ── Live updates ────────────────────────────────────────────

    def snapshot_changed(self, _kind: str, _entity: object) -> None:
        """Called by the app after it merges a stream update into the snapshot."""
        self.render_all()

    def refresh_units(self) -> None:
        self.render_all()

    def on_screen_resume(self) -> None:
        self.render_all()

    @work(exclusive=True, group="home-refresh")
    async def _periodic_refresh(self) -> None:
        try:
            snap = await self._client.get_snapshot()
        except Exception as exc:
            logger.warning("Home refresh failed: %s", exc)
            return
        self._adopt(snap)

    def _adopt(self, snap: SystemSnapshot) -> None:
        self._snapshot = snap
        app = self.app
        if isinstance(app, SnapshotHost):
            app.update_snapshot(snap)
        self.render_all()

    @work(exclusive=True, group="home-energy")
    async def _fetch_energy(self) -> None:
        """Today's kWh per room, from local midnight in the system's time zone."""
        tz = system_tz(self.snapshot)
        now = datetime.now(tz=UTC)
        midnight = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            metrics = await self._client.get_energy(start=midnight, end=now)
        except Exception as exc:
            logger.warning("Home energy fetch failed: %s", exc)
            return
        self._today_kwh = {m.space_id: m.total_kwh for m in metrics}
        self.render_all()

    # ── Actions ─────────────────────────────────────────────────

    def action_open_room(self) -> None:
        space_id = self.selected_space_id
        if space_id is None:
            return
        screen = room_screen_for(self.snapshot, self._client, space_id, self.use_f)
        if screen is not None:
            self.app.push_screen(screen)

    def action_devices(self) -> None:
        from quilt_hp.cli.tui.devices import DevicesScreen  # devices imports nothing from here

        self.app.push_screen(DevicesScreen(self.snapshot, self._client))

    def action_energy(self) -> None:
        from quilt_hp.cli.tui.energy import EnergyScreen

        self.app.push_screen(EnergyScreen(self.snapshot, self._client))

    def action_cycle_mode(self) -> None:
        if (space_id := self.selected_space_id) is not None:
            self._control(space_id, "mode")

    def action_setpoint(self, direction: int) -> None:
        if (space_id := self.selected_space_id) is not None:
            self._control(space_id, "setpoint", direction)

    @work(group="home-control")
    async def _control(self, space_id: str, intent: str, direction: int = 0) -> None:
        """Apply one key press. Presses for a room run one at a time, in order, and each
        computes its target from the room as the previous press left it (two quick ``+``
        presses from 24 °C reach 25 °C, not 24.5 °C twice)."""
        async with room_lock(self.app, space_id):
            space = next((s for s in self.snapshot.rooms if s.id == space_id), None)
            if space is None:
                return
            if intent == "mode":
                changes: dict[str, Any] = {"mode": next_mode(space)}
            else:
                change = nudge_setpoint(space, direction, self.use_f)
                if change is None:
                    mode = MODE_WORDS.get(space.controls.hvac_mode, "this mode")
                    self.notify(f"{space.name} has no setpoint in {mode}. Press m to change mode.")
                    return
                changes = {"change": change}
            try:
                await send_space_change(self._client, self.snapshot, space, **changes)
            except Exception as exc:
                self.notify(f"Couldn't update {space.name}: {exc}", severity="error")
                return
        self.render_all()

    def action_toggle_schedules(self) -> None:
        loc = self.snapshot.primary_location
        if loc is None:
            self.notify("This system has no location to pause.", severity="error")
            return
        pause = not loc.schedule_paused
        verb = "Pause" if pause else "Resume"
        detail = (
            "Every room keeps its current settings until you resume."
            if pause
            else "Every room goes back to following its schedule."
        )

        def done(confirmed: bool | None) -> None:
            if confirmed:
                self._set_schedules(pause)

        self.app.push_screen(
            ConfirmScreen(f"{verb} schedules for the whole house?", detail, verb), done
        )

    @work(group="home-control")
    async def _set_schedules(self, paused: bool) -> None:
        try:
            await _set_schedule_paused(self._client, self.snapshot, paused)
        except Exception as exc:
            self.notify(f"Couldn't change schedules: {exc}", severity="error")
            return
        self.notify("Schedules paused" if paused else "Schedules resumed", timeout=3)
        self.render_all()

    @work(exclusive=True, group="home-refresh")
    async def action_refresh(self) -> None:
        try:
            snap = await self._client.get_snapshot()
        except Exception as exc:
            self.notify(f"Refresh failed: {exc}", severity="error")
            return
        self._adopt(snap)
        self._fetch_energy()
        self.notify("Refreshed", timeout=2)

    def action_toggle_units(self) -> None:
        app = self.app
        if isinstance(app, SnapshotHost):
            app.use_f = not app.use_f
