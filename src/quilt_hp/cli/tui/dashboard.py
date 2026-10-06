"""Dashboard screen: one row per room."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual import on, work
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import (
    Footer,
    Header,
    ListItem,
    ListView,
    Static,
)

from quilt_hp.cli.tui.base import SnapshotHost
from quilt_hp.cli.tui.format import _fmt_state, _occ_glyph, _space_mode_badge, _tc
from quilt_hp.cli.tui.room import RoomScreen
from quilt_hp.cli.tui.shared import _odu_for_space
from quilt_hp.cli.tui.system import SystemScreen
from quilt_hp.client import QuiltClient
from quilt_hp.models.enums import (
    HVACState,
    OccupancyMode,
    OccupancyState,
)
from quilt_hp.models.indoor_unit import IndoorUnit
from quilt_hp.models.outdoor_unit import OutdoorUnit

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from quilt_hp.models.space import Space
    from quilt_hp.models.system import SystemSnapshot


logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# DashboardScreen
# ──────────────────────────────────────────────────────────────────


class RoomListItem(ListItem):
    """A ListView row representing one room."""

    def __init__(self, space: Space, idu: IndoorUnit | None = None, use_f: bool = False) -> None:
        super().__init__()
        self._space_id = space.id
        self._space_name = space.name
        self._idu = idu
        self._use_f = use_f
        self.update_space(space, idu, use_f)

    @property
    def space_id(self) -> str:
        return self._space_id

    def _build_row(self, space: Space, idu: IndoorUnit | None, use_f: bool) -> Text:
        c = space.controls
        s = space.state
        mode = _space_mode_badge(space) if c else Text("--", style="dim")
        state = _fmt_state(s.hvac_state) if s else Text("--", style="dim")
        ambient = _tc(s.ambient_temperature_c, use_f) if s else "--"
        setpt = c.display_setpoint_str(use_f) if c else "--"
        occ_state = (
            OccupancyState(idu.effective_occupancy_state)
            if idu
            and idu.effective_occupancy_state is not None
            and space.settings.occupancy_mode == OccupancyMode.ENABLED
            else None
        )
        occ = Text.from_markup(_occ_glyph(occ_state))
        name_w = 20
        name_part = self._space_name[:name_w].ljust(name_w)
        return Text.assemble(
            Text(name_part, style="bold"),
            "  ",
            mode,
            "  ",
            occ,
            " ",
            Text(f"{ambient:>8}", style="green"),
            Text(" → "),
            Text(f"{setpt:<12}", style="yellow"),
            Text("  "),
            state,
        )

    def update_space(
        self, space: Space, idu: IndoorUnit | None = None, use_f: bool = False
    ) -> None:
        self._space = space
        self._use_f = use_f
        if idu is not None:
            self._idu = idu
        with contextlib.suppress(NoMatches):
            self.query_one(Static).update(self._build_row(space, self._idu, use_f))

    def compose(self) -> ComposeResult:
        yield Static(
            self._build_row(self._space, self._idu, self._use_f),
            id=f"room-row-{self._space_id}",
        )


class DashboardScreen(Screen[None]):
    """Main screen — scrollable room list with live updates."""

    BINDINGS: ClassVar = [
        Binding("s", "system", "System"),
        Binding("r", "refresh", "Refresh"),
        Binding("u", "toggle_units", "°C/°F"),
        Binding("enter", "select_room", "Room Detail"),
    ]

    def __init__(
        self,
        snapshot: SystemSnapshot,
        client: QuiltClient,
    ) -> None:
        super().__init__()
        self._snapshot = snapshot  # fallback when not attached to a QuiltApp
        self._client = client
        self._items: dict[str, RoomListItem] = {}  # space_id → ListItem

    @property
    def snapshot(self) -> SystemSnapshot:
        """The app-owned snapshot, falling back to the constructor value."""
        with contextlib.suppress(Exception):
            app = self.app
            if isinstance(app, SnapshotHost) and app.snapshot is not None:
                return app.snapshot
        return self._snapshot

    @property
    def use_f(self) -> bool:
        """App-level °C/°F preference (falls back to °C when unmounted)."""
        with contextlib.suppress(Exception):
            app = self.app
            if isinstance(app, SnapshotHost):
                return app.use_f
        return False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ListView(id="dashboard-list")
        yield Static("", id="dashboard-statusbar")
        yield Footer()

    def _idu_for(self, space_id: str) -> IndoorUnit | None:
        return next(
            (u for u in self.snapshot.indoor_units if u.space_id == space_id),
            None,
        )

    def _odu_for(self, space_id: str, idu: IndoorUnit | None) -> OutdoorUnit | None:
        """Resolve room ODU from IDU link first, then by room relationship."""
        return _odu_for_space(self.snapshot, space_id, idu)

    def on_mount(self) -> None:
        lv = self.query_one(ListView)
        for space in self.snapshot.rooms:
            item = RoomListItem(space, self._idu_for(space.id), self.use_f)
            self._items[space.id] = item
            lv.append(item)
        self._refresh_statusbar()
        self.set_interval(60, self._periodic_refresh)

    def on_screen_resume(self) -> None:
        """Re-render rows from the merged snapshot when returning to this screen."""
        self.refresh_units()

    def refresh_units(self) -> None:
        """Re-render all room rows and the statusbar from the current snapshot."""
        snap = self.snapshot
        use_f = self.use_f
        for space_id, item in self._items.items():
            space = next((s for s in snap.rooms if s.id == space_id), None)
            if space:
                item.update_space(space, self._idu_for(space_id), use_f)
                item.refresh()
        self._refresh_statusbar()

    async def _apply_snapshot(self, snap: SystemSnapshot) -> None:
        """Adopt a fresh snapshot and rebuild the room list in-place."""
        self._snapshot = snap
        app = self.app
        if isinstance(app, SnapshotHost):
            app.update_snapshot(snap)
        lv = self.query_one(ListView)
        # Preserve the highlighted room across the rebuild.
        highlighted = lv.highlighted_child
        selected_id = highlighted.space_id if isinstance(highlighted, RoomListItem) else None
        old_index = lv.index
        self._items.clear()
        await lv.clear()
        for space in snap.rooms:
            item = RoomListItem(space, self._idu_for(space.id), self.use_f)
            self._items[space.id] = item
            lv.append(item)
        if self._items:
            ids = list(self._items)
            if selected_id in self._items:
                lv.index = ids.index(selected_id)
            elif old_index is not None:
                lv.index = min(old_index, len(ids) - 1)
        self._refresh_statusbar()

    @work
    async def _periodic_refresh(self) -> None:
        """Periodic silent re-sync with server state (called every 60 s)."""
        try:
            snap = await self._client.get_snapshot()
            await self._apply_snapshot(snap)
        except Exception as exc:
            logger.warning("Dashboard auto-refresh failed: %s", exc)

    @work
    async def action_refresh(self) -> None:
        try:
            snap = await self._client.get_snapshot()
            await self._apply_snapshot(snap)
            self.notify("Refreshed", timeout=2)
        except Exception as exc:
            self.notify(f"Refresh failed: {exc}", severity="error")

    def _refresh_statusbar(self) -> None:
        snap = self.snapshot
        tz = snap.timezone or "?"
        loc = snap.primary_location
        sched = "⏸ PAUSED" if (loc and loc.schedule_paused) else "▶ RUNNING"
        odu_state = "--"
        if snap.outdoor_units:
            odu = snap.outdoor_units[0]
            odu_state = HVACState(odu.hvac_state).name if odu.hvac_state else "--"
        with contextlib.suppress(NoMatches):
            self.query_one("#dashboard-statusbar", Static).update(
                f" System: {tz}  ·  Schedule: {sched}  ·  ODU: {odu_state}"
            )

    def update_space(self, space: Space) -> None:
        """Called from stream callbacks to update this room row."""
        item = self._items.get(space.id)
        if item:
            idu = self._idu_for(space.id)
            item.update_space(space, idu, self.use_f)
            item.refresh()

    def update_idu(self, idu: IndoorUnit) -> None:
        """Called from stream callbacks — refresh the row for the IDU's room."""
        space = next((s for s in self.snapshot.rooms if s.id == idu.space_id), None)
        if space is None:
            return
        item = self._items.get(space.id)
        if item:
            item.update_space(space, idu, self.use_f)
            item.refresh()

    def update_odu(self, _odu: OutdoorUnit) -> None:
        """Called when an ODU stream event arrives — refresh the statusbar.

        The updated ODU is already merged into the snapshot, which the
        statusbar reads directly.
        """
        self._refresh_statusbar()

    def action_toggle_units(self) -> None:
        app = self.app
        if isinstance(app, SnapshotHost):
            app.use_f = not app.use_f

    def action_system(self) -> None:
        self.app.push_screen(SystemScreen(self.snapshot, self._client, use_f=self.use_f))

    def action_select_room(self) -> None:
        lv = self.query_one(ListView)
        if lv.highlighted_child is None:
            return
        item = lv.highlighted_child
        if isinstance(item, RoomListItem):
            self._open_room(item.space_id)

    @on(ListView.Selected)
    def on_room_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, RoomListItem):
            self._open_room(event.item.space_id)

    def _open_room(self, space_id: str) -> None:
        snap = self.snapshot
        space = next((s for s in snap.rooms if s.id == space_id), None)
        if space is None:
            return
        idu = next(
            (u for u in snap.indoor_units if u.space_id == space_id),
            None,
        )
        ctrl = next(
            (c for c in snap.controllers if c.space_id == space_id),
            None,
        )
        odu = self._odu_for(space_id, idu)
        qsm = snap.qsm_for_idu(idu) if idu else None
        self.app.push_screen(
            RoomScreen(
                space=space,
                idu=idu,
                controller=ctrl,
                odu=odu,
                qsm=qsm,
                snapshot=snap,
                client=self._client,
                use_f=self.use_f,
            )
        )
