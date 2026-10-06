"""Energy screen: the whole house's energy use, by room, hour and day."""

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar

from rich.text import Text
from textual import work
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from quilt_hp.cli.tui.base import SnapshotHost
from quilt_hp.cli.tui.format import hourly_chart
from quilt_hp.cli.tui.views import EnergySummary, energy_summary, system_tz

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from quilt_hp.client import QuiltClient
    from quilt_hp.models.energy import EnergyBucket
    from quilt_hp.models.system import SystemSnapshot

logger = logging.getLogger(__name__)

_COLUMNS: tuple[tuple[str, int], ...] = (
    ("Room", 18),
    ("Today", 9),
    ("Yesterday", 10),
    ("7 days", 9),
    ("30 days", 9),
    ("Share", 22),
)


class EnergyScreen(Screen[None]):
    """Energy for every room and the house: totals, today by hour, and the last 14 days."""

    DEFAULT_CSS = """
    EnergyScreen .panel {
        border: round $primary-darken-2; border-title-color: $text; padding: 0 1; height: auto;
    }
    EnergyScreen #en-house-row { height: auto; }
    EnergyScreen #en-house-today { width: 54; margin-right: 1; }  /* the 48-column chart + border */
    EnergyScreen #en-house-days { width: 1fr; }
    EnergyScreen #en-rooms { height: auto; margin-top: 1; }
    EnergyScreen #en-status { height: auto; padding: 0 1; color: $text-muted; }
    """
    BINDINGS: ClassVar = [
        Binding("escape,b", "back", "Back"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self, snapshot: SystemSnapshot, client: QuiltClient) -> None:
        super().__init__()
        self._snapshot = snapshot
        self._client = client
        self._rooms: dict[str, EnergySummary] = {}
        self._house: EnergySummary | None = None
        self._error: str | None = None

    @property
    def snapshot(self) -> SystemSnapshot:
        with contextlib.suppress(Exception):
            app = self.app
            if isinstance(app, SnapshotHost) and app.snapshot is not None:
                return app.snapshot
        return self._snapshot

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll():
            yield Static("Loading energy…", id="en-status")
            with Horizontal(id="en-house-row"):
                yield Static(id="en-house-today", classes="panel")
                yield Static(id="en-house-days", classes="panel")
            yield DataTable(id="en-rooms", cursor_type="none", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Energy"
        self.query_one("#en-house-today").border_title = "Whole house today by hour (kWh)"
        self.query_one("#en-house-days").border_title = "Whole house, last 7 days"
        table: DataTable[Any] = self.query_one("#en-rooms", DataTable)
        for label, width in _COLUMNS:
            table.add_column(label, key=label, width=width)
        self._fetch()

    # ── Data ────────────────────────────────────────────────────

    @work(exclusive=True, group="energy")
    async def _fetch(self) -> None:
        snap = self.snapshot
        tz = system_tz(snap)
        now = datetime.now(tz=UTC)
        start = (now.astimezone(tz) - timedelta(days=30)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        try:
            metrics = await self._client.get_energy(start=start, end=now)
        except Exception as exc:
            logger.warning("Energy fetch failed: %s", exc)
            self._error = f"Couldn't load energy: {exc}"
            self.render_all()
            return
        everything: list[EnergyBucket] = []
        self._rooms = {}
        for m in metrics:
            self._rooms[m.space_id] = energy_summary(m.buckets, tz, now)
            everything += m.buckets
        self._house = energy_summary(everything, tz, now)
        self._error = None
        self.render_all()

    # ── Rendering ───────────────────────────────────────────────

    def render_all(self) -> None:
        status = self.query_one("#en-status", Static)
        house = self._house
        if house is None:
            status.update(
                Text(self._error or "Loading energy…", style="red" if self._error else "dim")
            )
            return
        status.update(
            Text.assemble(
                ("Whole house  ", "bold"),
                (f"{house.today_kwh:.2f} kWh today", "cyan"),
                f"  ·  {house.yesterday_kwh:.2f} yesterday  ·  {house.last_7_days_kwh:.1f} in 7 days"
                f"  ·  {house.last_30_days_kwh:.1f} in 30 days",
            )
        )
        bars, axis = hourly_chart(house.today_by_hour)
        self.query_one("#en-house-today", Static).update(
            Text.assemble((bars, "cyan"), "\n", (axis, "dim"))
        )
        week = house.by_day[:7]
        peak = max((kwh for _, kwh in week), default=0.0)
        lines = [
            Text.assemble(
                (f"{day.strftime('%a')} {day.day:>2}  ", "dim"),
                ("█" * (round(kwh / peak * 20) if peak else 0) or "▏", "cyan"),
                f" {kwh:.2f}",
            )
            for day, kwh in week
        ]
        self.query_one("#en-house-days", Static).update(Text("\n").join(lines))

        table: DataTable[Any] = self.query_one("#en-rooms", DataTable)
        table.clear()
        names = {s.id: s.name for s in self.snapshot.rooms}
        total_30 = house.last_30_days_kwh
        rows = sorted(
            ((names.get(sid, "?"), e) for sid, e in self._rooms.items() if sid in names),
            key=lambda item: -item[1].last_30_days_kwh,
        )
        for name, e in rows:
            share = e.last_30_days_kwh / total_30 if total_30 else 0.0
            bar = "█" * round(share * 14)
            table.add_row(
                Text(name, style="bold"),
                Text(f"{e.today_kwh:.2f}", style="cyan"),
                f"{e.yesterday_kwh:.2f}",
                f"{e.last_7_days_kwh:.1f}",
                f"{e.last_30_days_kwh:.1f}",
                Text.assemble((bar or "▏", "cyan"), f" {share:.0%}"),
            )

    # ── Actions ─────────────────────────────────────────────────

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_refresh(self) -> None:
        self._house = None
        self.render_all()
        self._fetch()
