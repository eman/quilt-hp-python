"""Textual TUI for Quilt HVAC — feature-complete, keyboard-only.

Screen flow:
  LoadingScreen ──→ DashboardScreen ──→
    RoomScreen (Status|Performance|Schedule tabs)
                          └──────────→ SystemScreen
"""

from __future__ import annotations

import contextlib
import datetime
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import (
    Container,
    Horizontal,
    ScrollableContainer,
    Vertical,
)
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
    LoadingIndicator,
    Rule,
    Static,
    TabbedContent,
    TabPane,
)

from quilt_hp.cli.settings import SettingsStore
from quilt_hp.cli.store import FileStore
from quilt_hp.client import QuiltClient
from quilt_hp.models.controller import Controller
from quilt_hp.models.enums import (
    FanSpeed,
    HVACMode,
    HVACState,
    LedAnimation,
    LightPreset,
    LouverMode,
    OccupancyMode,
    OccupancyState,
)
from quilt_hp.models.indoor_unit import IndoorUnit
from quilt_hp.models.outdoor_unit import OutdoorUnit
from quilt_hp.models.qsm import QuiltSmartModule
from quilt_hp.models.sensor import RemoteSensor, RemoteSensorControlMode

if TYPE_CHECKING:
    from quilt_hp.models.space import Space
    from quilt_hp.models.system import SystemSnapshot

# ──────────────────────────────────────────────────────────────────
# Persistent settings (delegates to quilt_hp.cli.settings)
# ──────────────────────────────────────────────────────────────────

# Persistent stores (tokens separate from non-secret settings)
_token_store = FileStore()
_settings_store = SettingsStore()


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

_MODE_STYLE: dict[HVACMode, str] = {
    HVACMode.HEAT: "bold red",
    HVACMode.COOL: "bold cyan",
    HVACMode.AUTO: "bold yellow",
    HVACMode.FAN: "bold green",
    HVACMode.STANDBY: "dim",
    HVACMode.FALLBACK_AUTO: "bold yellow",
    HVACMode.FALLBACK_OFF: "dim",
    HVACMode.UNSPECIFIED: "dim",
}

_STATE_STYLE: dict[HVACState, str] = {
    HVACState.HEAT: "red",
    HVACState.COOL: "cyan",
    HVACState.DRIFT: "yellow",
    HVACState.FAN: "green",
    HVACState.COOL_DEFERRED: "cyan",
    HVACState.HEAT_DEFERRED: "red",
    HVACState.FAN_DEFERRED: "green",
    HVACState.COOL_PREPARING: "cyan",
    HVACState.HEAT_PREPARING: "red",
    HVACState.STANDBY: "dim",
    HVACState.UNSPECIFIED: "dim",
}

_MODE_LABELS: dict[HVACMode, str] = {
    HVACMode.HEAT: "HEAT",
    HVACMode.COOL: "COOL",
    HVACMode.AUTO: "AUTO",
    HVACMode.FAN: " FAN",
    HVACMode.STANDBY: "STBY",
    HVACMode.FALLBACK_AUTO: "FAUTO",
    HVACMode.FALLBACK_OFF: "FOFF",
    HVACMode.UNSPECIFIED: " -- ",
}

_STATE_SYMBOLS: dict[HVACState, str] = {
    HVACState.HEAT: "◉ Heating",
    HVACState.COOL: "◉ Cooling",
    HVACState.DRIFT: "~ Drift",
    HVACState.FAN: "~ Fan",
    HVACState.COOL_DEFERRED: "○ Cool (deferred)",
    HVACState.HEAT_DEFERRED: "○ Heat (deferred)",
    HVACState.FAN_DEFERRED: "○ Fan (deferred)",
    HVACState.COOL_PREPARING: "⋯ Preparing to Cool",
    HVACState.HEAT_PREPARING: "⋯ Preparing to Heat",
    HVACState.STANDBY: "◌ Standby",
    HVACState.UNSPECIFIED: "--",
}

_FAN_CYCLE = [
    FanSpeed.AUTO,
    FanSpeed.QUIET,
    FanSpeed.LOW,
    FanSpeed.MEDIUM,
    FanSpeed.HIGH,
    FanSpeed.BLAST,
]
_MODE_CYCLE = [
    HVACMode.HEAT,
    HVACMode.COOL,
    HVACMode.AUTO,
    HVACMode.FAN,
    HVACMode.STANDBY,
]
_LOUVER_CYCLE = [
    LouverMode.SWEEP,
    LouverMode.AUTO,
    LouverMode.FIXED,
    LouverMode.CLOSED,
]
_OCC_CYCLE = [OccupancyMode.DISABLED, OccupancyMode.ENABLED]


def _tc(val_c: float | None, use_f: bool) -> str:
    """Format a temperature value in °C or °F."""
    if val_c is None:
        return "--"
    if use_f:
        return f"{val_c * 9 / 5 + 32:.1f}°F"
    return f"{val_c:.1f}°C"


def _fmt_timeout(seconds: float) -> str:
    """Format timeout as readable text (for example, '20 min')."""
    if seconds <= 0:
        return "0 s"
    total_m = int(seconds) // 60
    rem_s = int(seconds) % 60
    if total_m == 0:
        return f"{rem_s} s"
    if rem_s == 0:
        return f"{total_m} min"
    return f"{total_m} min {rem_s} s"


def _tu(use_f: bool) -> str:
    return "°F" if use_f else "°C"


def _led_color_str(color_code: int) -> str:
    """Return a human-readable LED color label from a packed RGBW uint32.

    Matches against known LightPreset values first; falls back to hex notation.
    """
    if color_code == 0:
        return "Black"
    try:
        return LightPreset(color_code).name.capitalize()
    except ValueError:
        r = (color_code >> 24) & 0xFF
        g = (color_code >> 16) & 0xFF
        b = (color_code >> 8) & 0xFF
        w = color_code & 0xFF
        return f"#{r:02X}{g:02X}{b:02X}w{w:02X}"


def _bar(level: float, width: int = 10) -> str:
    """Render a simple block-character progress bar."""
    filled = max(0, min(width, round(level * width)))
    return "█" * filled + "░" * (width - filled)


def _sku_or_none(model_sku: str | None) -> str | None:
    """Return a displayable SKU value or None for empty/placeholder values."""
    if not model_sku:
        return None
    sku = model_sku.strip()
    return sku if sku and sku != "N/A" else None


def _id_tokens(value: str | None) -> set[str]:
    """Return raw and normalized ID tokens for tolerant ID comparisons."""
    if not value:
        return set()
    raw = value.strip()
    if not raw:
        return set()
    return {raw, raw.rsplit("/", 1)[-1]}


def _occ_glyph(occ: OccupancyState | int | None) -> str:
    if occ is None:
        return "?"
    state = OccupancyState(occ) if isinstance(occ, int) else occ
    if state == OccupancyState.DETECTED:
        return "[green]●[/green]"
    if state == OccupancyState.UNDETECTED:
        return "[dim]○[/dim]"
    return "[dim]?[/dim]"


def _fmt_mode(mode: HVACMode) -> Text:
    label = _MODE_LABELS.get(mode, mode.name)
    style = _MODE_STYLE.get(mode, "")
    return Text(label, style=style)


def _space_mode_badge(space: Space) -> Text:
    """Mode badge using Space.is_away / Space.is_off from the core model."""
    if space.is_away:
        return Text("AWAY", style="yellow dim")
    if space.is_off:
        return Text(" OFF", style="dim")
    return _fmt_mode(space.controls.hvac_mode)


def _fmt_state(state: HVACState) -> Text:
    label = _STATE_SYMBOLS.get(state, state.name)
    style = _STATE_STYLE.get(state, "")
    return Text(label, style=style)


def _cycle_next(current: object, cycle: list) -> object:
    try:
        return cycle[(cycle.index(current) + 1) % len(cycle)]
    except ValueError:
        return cycle[0]


# ──────────────────────────────────────────────────────────────────
# CSS
# ──────────────────────────────────────────────────────────────────

_APP_CSS = """
Screen {
    background: $surface;
}

/* Loading */
#loading-container {
    align: center middle;
    height: 100%;
}
#loading-label {
    margin-top: 2;
    text-align: center;
    color: $text-muted;
}

/* Dashboard */
#dashboard-list {
    height: 1fr;
    border: round $primary-darken-2;
    margin: 1 2;
}
#dashboard-statusbar {
    height: 1;
    padding: 0 2;
    background: $primary-darken-3;
    color: $text-muted;
    dock: bottom;
}

/* Room panels */
.panel {
    border: round $primary-darken-2;
    border-title-color: $accent;
    border-title-align: left;
    margin: 0 1;
    padding: 1 2;
    height: auto;
}
.section-label {
    text-style: bold;
    color: $accent;
    margin-top: 1;
}
.kv-key {
    color: $text-muted;
    width: 22;
}
.kv-val {
    color: $text;
}
.section-rule {
    margin: 1 0;
}
#room-tabs {
    height: 1fr;
}
#tab-status {
    overflow-y: auto;
}
#tab-perf {
    padding: 0;
}
#tab-schedule {
    padding: 0;
}
.sched-row {
    height: 1fr;
}
.sched-days-panel {
    width: 22;
    height: 1fr;
    border: round $primary-darken-2;
    border-title-color: $accent;
    border-title-align: left;
    margin: 0 0 0 1;
    padding: 0 1;
}
.sched-events-panel {
    width: 1fr;
    height: 1fr;
    border: round $primary-darken-2;
    border-title-color: $accent;
    border-title-align: left;
    margin: 0 1 0 0;
    padding: 0 1;
}
#sched-status {
    height: 1;
    padding: 0 2;
    background: $surface-darken-1;
    color: $text-muted;
}
#tab-energy {
    overflow-y: auto;
}
.energy-summary {
    height: auto;
    padding: 1 2;
    margin: 0 1;
    border: round $primary-darken-2;
    border-title-color: $accent;
    border-title-align: left;
}
.energy-chart {
    height: auto;
    padding: 1 2;
    margin: 0 1;
    border: round $primary-darken-2;
    border-title-color: $accent;
    border-title-align: left;
}
#energy-status {
    padding: 0 2;
    color: $text-muted;
}
.controls-sensors-row {
    height: auto;
}
.controls-panel {
    width: 1fr;
}
.sensors-panel {
    width: 1fr;
}
.dial-panel {
    width: 1fr;
    height: auto;
}
.qsm-panel {
    width: 1fr;
    height: auto;
}
.perf-row {
    height: 1fr;
}
.perf-left {
    width: 1fr;
    height: 1fr;
}
.perf-right {
    width: 1fr;
    height: 1fr;
}

/* System screen */
#system-container {
    overflow-y: auto;
    padding: 1 2;
}
.odu-panel {
    border: round $primary-darken-2;
    border-title-color: $accent;
    border-title-align: left;
    padding: 1 2;
    margin-bottom: 1;
    height: auto;
}
#odu-row {
    height: auto;
    margin-bottom: 1;
}
#odu-row .odu-panel {
    width: 1fr;
    margin-bottom: 0;
    margin-right: 1;
}
"""


# ──────────────────────────────────────────────────────────────────
# LoadingScreen
# ──────────────────────────────────────────────────────────────────


class LoadingScreen(Screen):
    """Spinner shown while logging in and fetching the initial snapshot."""

    def compose(self) -> ComposeResult:
        with Container(id="loading-container"):
            yield LoadingIndicator()
            yield Label("Connecting to Quilt Cloud…", id="loading-label")

    def set_status(self, msg: str) -> None:
        with contextlib.suppress(NoMatches):
            self.query_one("#loading-label", Label).update(msg)


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
        if idu is not None:
            self._idu = idu
        with contextlib.suppress(NoMatches):
            self.query_one(Static).update(self._build_row(space, self._idu, use_f))

    def compose(self) -> ComposeResult:
        yield Static(
            self._build_row(self._space, self._idu, False),
            id=f"room-row-{self._space_id}",
        )


class DashboardScreen(Screen):
    """Main screen — scrollable room list with live updates."""

    BINDINGS: ClassVar = [
        Binding("s", "system", "System"),
        Binding("r", "refresh", "Refresh"),
        Binding("u", "toggle_units", "°C/°F"),
        Binding("enter", "select_room", "Room Detail"),
    ]

    use_f: reactive[bool] = reactive(False)

    def __init__(
        self,
        snapshot: SystemSnapshot,
        client: QuiltClient,
    ) -> None:
        super().__init__()
        self._snapshot = snapshot
        self._client = client
        self._items: dict[str, RoomListItem] = {}  # space_id → ListItem

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ListView(id="dashboard-list")
        yield Static("", id="dashboard-statusbar")
        yield Footer()

    def _idu_for(self, space_id: str) -> IndoorUnit | None:
        return next(
            (u for u in self._snapshot.indoor_units if u.space_id == space_id),
            None,
        )

    def _odu_for(self, space_id: str, idu: IndoorUnit | None) -> OutdoorUnit | None:
        """Resolve room ODU from IDU link first, then by room relationship."""
        if idu:
            odu = self._snapshot.odu_for_idu(idu)
            if odu is not None:
                return odu
        space_ids = _id_tokens(space_id)
        return next(
            (u for u in self._snapshot.outdoor_units if _id_tokens(u.space_id) & space_ids),
            None,
        )

    def on_mount(self) -> None:
        lv = self.query_one(ListView)
        for space in self._snapshot.rooms:
            item = RoomListItem(space, self._idu_for(space.id), self.use_f)
            self._items[space.id] = item
            lv.append(item)
        self._refresh_statusbar()
        self.set_interval(60, self._auto_refresh)

    async def _apply_snapshot(self, snap: SystemSnapshot) -> None:
        """Replace the current snapshot and rebuild the room list in-place."""
        self._snapshot = snap
        # Keep app-level snapshot in sync for stream dispatcher comfort maps.
        self.app._snapshot = snap  # type: ignore[attr-defined]
        self._items.clear()
        lv = self.query_one(ListView)
        await lv.clear()
        for space in snap.rooms:
            item = RoomListItem(space, self._idu_for(space.id), self.use_f)
            self._items[space.id] = item
            lv.append(item)
        self._refresh_statusbar()

    @work
    async def _auto_refresh(self) -> None:
        """Periodic silent re-sync with server state (called every 60 s)."""
        with contextlib.suppress(Exception):
            snap = await self._client.get_snapshot()
            await self._apply_snapshot(snap)

    @work
    async def action_refresh(self) -> None:
        try:
            snap = await self._client.get_snapshot()
            await self._apply_snapshot(snap)
            self.notify("Refreshed", timeout=2)
        except Exception as exc:
            self.notify(f"Refresh failed: {exc}", severity="error")

    def _refresh_statusbar(self) -> None:
        snap = self._snapshot
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

    def update_odu(self, odu: OutdoorUnit) -> None:
        """Called when an ODU stream event arrives — refresh the statusbar."""
        self._refresh_statusbar()

    def watch_use_f(self, use_f: bool) -> None:
        for space_id, item in self._items.items():
            space = next((s for s in self._snapshot.spaces if s.id == space_id), None)
            if space:
                item.update_space(space, None, use_f)
                item.refresh()

    def action_toggle_units(self) -> None:
        self.use_f = not self.use_f
        self.app._persist()

    def action_system(self) -> None:
        self.app.push_screen(SystemScreen(self._snapshot, self._client, use_f=self.use_f))

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
        space = next((s for s in self._snapshot.rooms if s.id == space_id), None)
        if space is None:
            return
        idu = next(
            (u for u in self._snapshot.indoor_units if u.space_id == space_id),
            None,
        )
        ctrl = next(
            (c for c in self._snapshot.controllers if c.space_id == space_id),
            None,
        )
        odu = self._odu_for(space_id, idu)
        qsm = self._snapshot.qsm_for_idu(idu) if idu else None
        self.app.push_screen(
            RoomScreen(
                space=space,
                idu=idu,
                controller=ctrl,
                odu=odu,
                qsm=qsm,
                snapshot=self._snapshot,
                client=self._client,
                use_f=self.use_f,
            )
        )


# ──────────────────────────────────────────────────────────────────
# RoomScreen
# ──────────────────────────────────────────────────────────────────


class _KVStatic(Static):
    """A key: value line as Rich markup."""

    def set_kv(self, key: str, value: str, val_style: str = "") -> None:
        if val_style:
            val = Text(value, style=val_style)
        else:
            val = Text.from_markup(value)
        self.update(Text.assemble(Text(f"{key:<22}", style="dim"), val))


class RoomScreen(Screen):
    """Room detail screen with Status / Performance / Schedule tabs."""

    BINDINGS: ClassVar = [
        Binding("escape,b", "back", "Back"),
        Binding("u", "toggle_units", "°C/°F"),
        # Status tab mutations
        Binding("m", "cycle_mode", "Mode"),
        Binding("H", "heat_up", "Heat+"),
        Binding("h", "heat_down", "Heat-"),
        Binding("C", "cool_up", "Cool+"),
        Binding("c", "cool_down", "Cool-"),
        Binding("f", "cycle_fan", "Fan"),
        Binding("l", "cycle_louver", "Louver"),
        Binding("L", "toggle_led", "LED"),
        Binding("o", "cycle_occupancy", "Occ"),
        Binding("p", "toggle_schedule", "Pause Sched"),
        Binding("e", "refresh_energy", "Energy ↻"),
        Binding("[", "away_timeout_dec", "Away-5m", show=False),
        Binding("]", "away_timeout_inc", "Away+5m", show=False),
        Binding("{", "return_timeout_dec", "Return-1m", show=False),
        Binding("}", "return_timeout_inc", "Return+1m", show=False),
        # Presence fence adjustment (status tab)
        Binding("ctrl+up", "fence_fwd_inc", "Fence Depth+", show=False),
        Binding("ctrl+down", "fence_fwd_dec", "Fence Depth-", show=False),
        Binding("ctrl+right", "fence_lr_inc", "Fence L/R+", show=False),
        Binding("ctrl+left", "fence_lr_dec", "Fence L/R-", show=False),
        Binding("alt+r", "radar_height_inc", "Radar H+", show=False),
        Binding("alt+t", "radar_height_dec", "Radar H-", show=False),
    ]

    use_f: reactive[bool] = reactive(False)

    def __init__(
        self,
        space: Space,
        idu: IndoorUnit | None,
        controller: Controller | None,
        odu: OutdoorUnit | None,
        qsm: QuiltSmartModule | None,
        snapshot: SystemSnapshot,
        client: QuiltClient,
        use_f: bool = False,
    ) -> None:
        super().__init__()
        self._space = space
        self._idu = idu
        self._controller = controller
        self._odu = odu
        self._qsm = qsm
        self._snapshot = snapshot
        self._client = client
        self.use_f = use_f
        self.title = space.name
        self.sub_title = "Room"

    # ── Layout ──────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(id="room-tabs"):
            with TabPane("Status", id="tab-status"):
                yield from self._compose_status()
            with TabPane("Performance", id="tab-perf"):
                yield from self._compose_perf()
            with TabPane("Schedule", id="tab-schedule"):
                yield from self._compose_schedule()
            with TabPane("Energy", id="tab-energy"):
                yield from self._compose_energy()
        yield Footer()

    def _compose_status(self) -> ComposeResult:
        with Horizontal(classes="controls-sensors-row"):
            # Controls panel
            with Vertical(classes="panel controls-panel") as v:
                v.border_title = "Controls"
                yield _KVStatic(id="ctl-mode")
                yield _KVStatic(id="ctl-heat")
                yield _KVStatic(id="ctl-cool")
                yield _KVStatic(id="ctl-fan")
                yield _KVStatic(id="ctl-louver")
                yield _KVStatic(id="ctl-louver-pos")
                yield _KVStatic(id="ctl-boost")
                yield _KVStatic(id="ctl-led")
                yield _KVStatic(id="ctl-led-color")
                yield _KVStatic(id="ctl-led-anim")
                yield _KVStatic(id="ctl-preset")
                yield _KVStatic(id="ctl-preset-override")
                yield _KVStatic(id="ctl-state-preset")
                yield _KVStatic(id="ctl-occ-mode")
                yield _KVStatic(id="ctl-safety")
                yield _KVStatic(id="ctl-away-after")
                yield _KVStatic(id="ctl-return-after")
                yield _KVStatic(id="ctl-away-temps")
            # Sensors panel
            with Vertical(classes="panel sensors-panel", id="sensors-panel") as v:
                v.border_title = "Sensors"
                yield _KVStatic(id="sen-ambient")
                yield _KVStatic(id="sen-calc-ambient")
                yield _KVStatic(id="sen-humidity")
                yield _KVStatic(id="sen-fan-rpm")
                yield _KVStatic(id="sen-fan-setpoint-rpm")
                yield _KVStatic(id="sen-setpoint")
                yield _KVStatic(id="sen-inlet")
                yield _KVStatic(id="sen-outlet")
                yield _KVStatic(id="sen-louver-angle")
                yield _KVStatic(id="sen-state")
                yield _KVStatic(id="sen-occ-state")
                yield _KVStatic(id="sen-presence-l")
                yield _KVStatic(id="sen-presence-r")
                yield _KVStatic(id="sen-presence-level")
                yield _KVStatic(id="sen-fence-lr")
                yield _KVStatic(id="sen-fence-fwd")
                yield _KVStatic(id="sen-radar-height")
                yield _KVStatic(id="sen-idu-mode")
                yield _KVStatic(id="sen-idu-name")
                yield _KVStatic(id="sen-idu-light-default")
        yield Rule(classes="section-rule")
        # Dial and QSM panels side by side
        with Horizontal(classes="controls-sensors-row"):
            # Dial panel
            with Vertical(classes="panel dial-panel", id="dial-panel") as v:
                v.border_title = "Dial (Thermostat)"
                yield _KVStatic(id="dial-model")
                yield _KVStatic(id="dial-serial")
                yield _KVStatic(id="dial-fw")
                yield _KVStatic(id="dial-ambient")
                yield _KVStatic(id="dial-calib")
                yield _KVStatic(id="dial-pcb")
                yield _KVStatic(id="dial-wifi")
                yield _KVStatic(id="dial-wifi-ip")
                yield _KVStatic(id="dial-wifi-last")
                yield _KVStatic(id="dial-wifi-ap")
                yield _KVStatic(id="dial-wifi-p2p")
                yield _KVStatic(id="dial-remote-sensor")
                yield _KVStatic(id="dial-crs-temp")
                yield _KVStatic(id="dial-crs-humidity")
                yield _KVStatic(id="dial-crs-battery")
                yield _KVStatic(id="dial-crs-signal")
            # QSM panel
            with Vertical(classes="panel qsm-panel") as v:
                v.border_title = "QSM (Smart Module)"
                yield _KVStatic(id="qsm-wifi-hosted")
                yield _KVStatic(id="qsm-wifi-ap")
                yield _KVStatic(id="qsm-wifi-p2p")
                yield _KVStatic(id="qsm-presence")
                yield _KVStatic(id="qsm-als")
                yield _KVStatic(id="qsm-accel")

    def _compose_perf(self) -> ComposeResult:
        with Horizontal(classes="perf-row"):
            with ScrollableContainer(classes="panel perf-left") as v:
                v.border_title = "IDU / ODU"
                yield Label("IDU Temperatures", classes="section-label")
                yield _KVStatic(id="p-coil")
                yield _KVStatic(id="p-outlet")
                yield _KVStatic(id="p-inlet")
                yield _KVStatic(id="p-gas")
                yield _KVStatic(id="p-liquid")
                yield Rule()
                yield Label("HVAC Inputs (Controller→IDU)", classes="section-label")
                yield _KVStatic(id="p-hi-ext-ambient")
                yield _KVStatic(id="p-hi-setpoint")
                yield _KVStatic(id="p-hi-mode")
                yield _KVStatic(id="p-hi-state")
                yield _KVStatic(id="p-hi-source")
                yield _KVStatic(id="p-hi-ctrl-type")
                yield Rule()
                yield Label("ODU Compressor", classes="section-label")
                yield _KVStatic(id="p-odu-state")
                yield _KVStatic(id="p-odu-freq")
                yield _KVStatic(id="p-odu-coil")
                yield _KVStatic(id="p-odu-exhaust")
                yield _KVStatic(id="p-odu-hi")
                yield _KVStatic(id="p-odu-lo")
                yield _KVStatic(id="p-odu-ambient")
            with ScrollableContainer(classes="panel perf-right") as v:
                v.border_title = "Energy / Efficiency"
                yield Label("IDU Energy", classes="section-label")
                yield _KVStatic(id="p-interval")
                yield _KVStatic(id="p-energy-j")
                yield _KVStatic(id="p-energy-kwh")
                yield _KVStatic(id="p-fan-actual")
                yield _KVStatic(id="p-pd-mode")
                yield _KVStatic(id="p-pd-state")
                yield Rule()
                yield Label("Efficiency", classes="section-label")
                yield _KVStatic(id="p-capacity")
                yield _KVStatic(id="p-cop")
                yield _KVStatic(id="p-hvac-power")
                yield _KVStatic(id="p-led-power")
                yield _KVStatic(id="p-pm-mode")
                yield _KVStatic(id="p-pm-state")
                yield _KVStatic(id="p-pm-duration")
                yield _KVStatic(id="p-pm-energy-total")
                yield _KVStatic(id="p-pm-hvac-energy")
                yield _KVStatic(id="p-pm-led-energy")
                yield Rule()
                yield Label("IDU Conditions", classes="section-label")
                yield _KVStatic(id="p-cond-defrost")
                yield _KVStatic(id="p-cond-oilreturn")
                yield _KVStatic(id="p-cond-coilpreheat")
                yield _KVStatic(id="p-cond-safetyheat")
                yield _KVStatic(id="p-cond-anticold")
                yield _KVStatic(id="p-cond-modeswitch")
                yield _KVStatic(id="p-cond-modeconflict")
                yield _KVStatic(id="p-cond-modeconflictavoid")
                yield _KVStatic(id="p-cond-abnormal-odu-air")
                yield _KVStatic(id="p-cond-odu-comm")
                yield _KVStatic(id="p-cond-modbus")
                yield Rule()
                yield Label("ODU Hardware", classes="section-label")
                yield _KVStatic(id="p-odu-model")
                yield _KVStatic(id="p-odu-serial")
                yield _KVStatic(id="p-odu-fw")
                yield Rule()
                yield Label("IDU Commands", classes="section-label")
                yield _KVStatic(id="p-cmd-fallback")

    def _compose_schedule(self) -> ComposeResult:
        yield Static("", id="sched-status")
        with Horizontal(classes="sched-row"):
            with ScrollableContainer(classes="sched-days-panel") as v:
                v.border_title = "Schedule"
                yield DataTable(id="sched-week", show_cursor=True, cursor_type="row")
            with ScrollableContainer(classes="sched-events-panel", id="sched-events-panel") as v:
                v.border_title = "Events"
                yield DataTable(id="sched-day", show_cursor=False)

    def _compose_energy(self) -> ComposeResult:
        yield Static("", id="energy-status")
        with Vertical(classes="energy-summary") as v:
            v.border_title = "Energy Summary"
            yield _KVStatic(id="e-today")
            yield _KVStatic(id="e-yesterday")
            yield _KVStatic(id="e-7day")
            yield _KVStatic(id="e-30day")
        with Vertical(classes="energy-chart") as v:
            v.border_title = "Last 24 Hours — Hourly (kWh)"
            yield Static("", id="e-sparkline")
        yield DataTable(id="e-table")

    # ── Mount: populate all panels ───────────────────────────────

    def on_mount(self) -> None:
        self._populate_status()
        self._populate_perf()
        self._populate_schedule()
        self._fetch_energy()

    def _populate_status(self) -> None:
        space = self._space
        idu = self._idu
        ctrl = self._controller
        use_f = self.use_f

        c = space.controls
        s = space.state
        sets = space.settings

        # Look up comfort preset name
        preset_name = "--"
        if c.comfort_setting_id:
            cs = next(
                (x for x in self._snapshot.comfort_settings if x.id == c.comfort_setting_id),
                None,
            )
            if cs:
                preset_name = f"{cs.name} ({cs.type.name})"

        if space.is_away:
            mode_label, mode_style = "AWAY", "yellow dim"
        elif space.is_off:
            mode_label, mode_style = "OFF", "dim"
        else:
            mode_label = space.controls.hvac_mode.name
            mode_style = _MODE_STYLE.get(space.controls.hvac_mode, "")
        self._kv("ctl-mode", "Mode", mode_label, mode_style)
        self._kv("ctl-heat", "Heat Setpoint", _tc(c.heating_setpoint_c, use_f), "red")
        self._kv(
            "ctl-cool",
            "Cool Setpoint",
            _tc(c.cooling_setpoint_c, use_f),
            "cyan",
        )
        self._kv("ctl-fan", "Fan Speed", idu.controls.fan_speed.name if idu else "--")
        self._kv(
            "ctl-louver",
            "Louver",
            idu.controls.louver_mode.name if idu else "--",
        )
        if idu and idu.controls.louver_mode.name == "FIXED" and idu.controls.louver_fixed_position:
            self._kv(
                "ctl-louver-pos",
                "  Fixed Pos",
                f"{idu.controls.louver_fixed_position:.1f}°",
            )
        else:
            self._kv("ctl-louver-pos", "  Fixed Pos", "--")
        boost_str = "--"
        if idu and c.boost_mode.name not in ("UNSPECIFIED",):
            boost_str = "ON" if c.boost_mode.name == "ON" else "Off"
        elif idu:
            boost_str = "Off"
        self._kv(
            "ctl-boost",
            "Boost Mode",
            boost_str,
            "bold yellow" if boost_str == "ON" else "",
        )
        led_str = "--"
        led_color_str = "--"
        led_anim_str = "--"
        if idu:
            if not idu.is_online:
                led_str = "OFF (offline)"
                led_color_str = "--"
                led_anim_str = "--"
            elif idu.led_on:
                led_str = f"ON  {idu.controls.led_brightness * 100:.0f}%"
                led_color_str = _led_color_str(idu.controls.led_color_code)
                anim = idu.controls.led_animation
                led_anim_str = (
                    anim.name.replace("_", " ").title()
                    if anim not in (LedAnimation.UNSPECIFIED, LedAnimation.NONE)
                    else "None"
                )
            else:
                led_str = "OFF"
                led_color_str = "--"
                led_anim_str = "--"
        self._kv("ctl-led", "LED", led_str)
        self._kv("ctl-led-color", "  Color", led_color_str)
        self._kv("ctl-led-anim", "  Effect", led_anim_str)
        self._kv("ctl-preset", "Comfort Preset", preset_name, "yellow")
        # Comfort setting override: why the current preset was applied
        override = c.comfort_setting_override
        from quilt_hp.models.enums import ComfortSettingOverride

        override_labels = {
            ComfortSettingOverride.NONE: ("Schedule", "dim"),
            ComfortSettingOverride.UNTIL_NEXT_SCHEDULE: (
                "Manual (until next event)",
                "yellow",
            ),
            ComfortSettingOverride.INDEFINITE: (
                "Manual (indefinite)",
                "yellow",
            ),
            ComfortSettingOverride.SCHEDULE: ("Schedule", "dim"),
            ComfortSettingOverride.UNOCCUPIED: ("Auto-Away", "yellow dim"),
            ComfortSettingOverride.OCCUPIED: ("Auto-Return", "green dim"),
        }
        ov_str, ov_style = override_labels.get(
            override, (override.name.replace("_", " ").title(), "")
        )
        self._kv("ctl-preset-override", "  Applied Via", ov_str, ov_style)
        # State-reported active comfort setting may differ from controls preset.
        state_preset_name = "--"
        if s.comfort_setting_id:
            cs_state = next(
                (x for x in self._snapshot.comfort_settings if x.id == s.comfort_setting_id),
                None,
            )
            if cs_state:
                state_preset_name = cs_state.name
            elif s.comfort_setting_id != c.comfort_setting_id:
                state_preset_name = f"…{s.comfort_setting_id[-8:]}"
        self._kv(
            "ctl-state-preset",
            "  Active (state)",
            state_preset_name,
            "yellow dim",
        )
        occ_mode_label = sets.occupancy_mode.name.capitalize()
        self._kv("ctl-occ-mode", "Occupancy Mode", occ_mode_label)
        self._kv(
            "ctl-safety",
            "Safety Heating",
            sets.safety_heating.name.capitalize(),
        )

        # Auto-away / auto-return timeouts (editable with [ ] { })
        away_style = "" if sets.occupancy_mode == OccupancyMode.ENABLED else "dim"
        self._kv(
            "ctl-away-after",
            "Auto-Away After",
            _fmt_timeout(sets.unoccupied_timeout_s),
            away_style,
        )
        self._kv(
            "ctl-return-after",
            "Auto-Return After",
            _fmt_timeout(sets.occupied_timeout_s),
            away_style,
        )

        # Away temperatures — from the space's AWAY comfort setting
        away_cs = next(
            (
                cs
                for cs in self._snapshot.comfort_settings
                if cs.space_id == space.id and cs.type.name == "AWAY"
            ),
            None,
        )
        if away_cs:
            away_temps = (
                f"Heat {_tc(away_cs.heating_setpoint_c, use_f)} / "
                f"Cool {_tc(away_cs.cooling_setpoint_c, use_f)}"
            )
            self._kv("ctl-away-temps", "Away Temps", away_temps, "yellow dim")
        else:
            self._kv("ctl-away-temps", "Away Temps", "not configured", "dim")

        # Update panel titles with offline status
        idu_title = "Sensors  [dim]F/G depth  X/Z L/R  R/T height[/dim]"
        if idu and not idu.is_online:
            idu_title = "Sensors  [bold red]⚠ IDU OFFLINE[/]"
        with contextlib.suppress(Exception):
            self.query_one("#sensors-panel").border_title = idu_title

        dial_title = "Dial (Thermostat)"
        if ctrl and not ctrl.is_online:
            dial_title = "Dial (Thermostat)  [bold red]⚠ OFFLINE[/]"
        with contextlib.suppress(Exception):
            self.query_one("#dial-panel").border_title = dial_title

        self._kv(
            "sen-ambient",
            "Ambient Temp",
            _tc(s.ambient_temperature_c, use_f),
            "green",
        )
        if idu and idu.state.calculated_ambient_temperature_c:
            self._kv(
                "sen-calc-ambient",
                "Ambient (calc)",
                _tc(idu.state.calculated_ambient_temperature_c, use_f),
            )
        else:
            self._kv("sen-calc-ambient", "Ambient (calc)", "--")
        self._kv(
            "sen-humidity",
            "Humidity",
            f"{idu.state.ambient_humidity_percent:.0f}%"
            if idu and idu.state.ambient_humidity_percent
            else "--",
        )
        fan_rpm = idu.state.fan_speed_rpm if idu and idu.state else None
        self._kv(
            "sen-fan-rpm",
            "Fan Speed (actual)",
            f"{fan_rpm:.0f} RPM" if fan_rpm else "Off",
        )
        fan_sp_rpm = idu.state.fan_speed_setpoint_rpm if idu and idu.state else None
        self._kv(
            "sen-fan-setpoint-rpm",
            "Fan Speed (setpoint)",
            f"{fan_sp_rpm:.0f} RPM" if fan_sp_rpm else "--",
        )
        self._kv("sen-setpoint", "Active Setpoint", _tc(s.setpoint_c, use_f))
        if idu and idu.state.inlet_temperature_c:
            self._kv(
                "sen-inlet",
                "Inlet Temp",
                _tc(idu.state.inlet_temperature_c, use_f),
            )
        else:
            self._kv("sen-inlet", "Inlet Temp", "--")
        if idu and idu.state.outlet_temperature_c:
            self._kv(
                "sen-outlet",
                "Outlet Temp",
                _tc(idu.state.outlet_temperature_c, use_f),
            )
        else:
            self._kv("sen-outlet", "Outlet Temp", "--")
        if idu and idu.state.louver_angle_up_down_degrees:
            self._kv(
                "sen-louver-angle",
                "Louver Angle",
                f"{idu.state.louver_angle_up_down_degrees:.1f}°",
            )
        else:
            self._kv("sen-louver-angle", "Louver Angle", "--")
        state_fmt = _fmt_state(s.hvac_state)
        self._kv("sen-state", "HVAC State", state_fmt.plain, str(state_fmt.style))
        raw_occ = idu.effective_occupancy_state if idu else None
        occ_state = OccupancyState(raw_occ) if raw_occ is not None else None
        if occ_state == OccupancyState.DETECTED:
            occ_str, occ_style = "Occupied", "green"
        elif occ_state == OccupancyState.UNDETECTED:
            occ_str, occ_style = "Vacant", "dim"
        elif idu and not idu.is_online:
            occ_str, occ_style = "offline", "dim italic"
        else:
            occ_str, occ_style = "--", "dim italic"
        # occupancy_state is the auto-away engine decision (lags real presence
        # unoccupied_timeout_s).  It controls HVAC setback, not live radar.
        self._kv("sen-occ-state", "Occupancy", occ_str, occ_style)

        # Presence sensors — binary DETECTED / UNDETECTED per radar sensor.
        # KMP uses sensor0Presence / sensor1Presence as Presence enum
        # (DETECTED/UNDETECTED); these are NOT analog values.
        if idu and idu.presence:
            from quilt_hp.models.enums import Presence

            def _presence_str(p: Presence) -> tuple[str, str]:
                if p == Presence.DETECTED:
                    return "Detected", "green bold"
                if p == Presence.UNDETECTED:
                    return "Not Detected", "dim"
                return "--", "dim italic"

            l_str, l_style = _presence_str(idu.presence.sensor0_presence)
            r_str, r_style = _presence_str(idu.presence.sensor1_presence)
            self._kv("sen-presence-l", "Radar L", l_str, l_style)
            self._kv("sen-presence-r", "Radar R", r_str, r_style)
        else:
            self._kv("sen-presence-l", "Radar L", "--")
            self._kv("sen-presence-r", "Radar R", "--")

        # Presence detection level and fence geometry (from IDU settings)
        if idu:
            pdl = idu.state.presence_detection_level
            pdl_str = f"{pdl:.2f}" if pdl is not None else "--"
            self._kv("sen-presence-level", "Detection Level", pdl_str)
            st = idu.settings
            if st.presence_fence_left_m or st.presence_fence_right_m:
                lr_str = (
                    f"L {st.presence_fence_left_m:.2f} m  /  R {st.presence_fence_right_m:.2f} m"
                )
            else:
                lr_str = "[dim]unconfigured (max range)[/dim]"
            if st.presence_fence_forward_m:
                fwd_str = f"{st.presence_fence_forward_m:.2f} m"
            else:
                fwd_str = "[dim]unconfigured (max range)[/dim]"
            h_str = (
                f"{st.radar_sensor_distance_from_floor_m:.2f} m"
                if st.radar_sensor_distance_from_floor_m
                else "[dim]unconfigured[/dim]"
            )
            self._kv("sen-fence-lr", "Fence L/R", lr_str)
            self._kv("sen-fence-fwd", "Fence Depth", fwd_str)
            self._kv("sen-radar-height", "Radar Height", h_str)
        else:
            self._kv("sen-presence-level", "Detection Level", "--")
            self._kv("sen-fence-lr", "Fence L/R", "--")
            self._kv("sen-fence-fwd", "Fence Depth", "--")
            self._kv("sen-radar-height", "Radar Height", "--")

        idu_mode_str = idu.state.hvac_mode.name if idu and idu.state else "--"
        idu_mode_style = _MODE_STYLE.get(idu.state.hvac_mode, "") if idu and idu.state else ""
        self._kv("sen-idu-mode", "IDU Mode", idu_mode_str, idu_mode_style)
        if idu and idu.settings:
            self._kv("sen-idu-name", "IDU Name", idu.settings.name or "--")
            light_pct = idu.settings.light_brightness_default_percent
            self._kv(
                "sen-idu-light-default",
                "Default Brightness",
                f"{light_pct * 100:.0f}%" if light_pct else "--",
            )
        else:
            self._kv("sen-idu-name", "IDU Name", "--")
            self._kv("sen-idu-light-default", "Default Brightness", "--")

        # Dial / Controller
        def _wifi_str(w: object | None) -> str:
            if not w:
                return "--"
            parts = []
            if w.ssid:
                parts.append(w.ssid)
            if w.ip:
                parts.append(w.ip)
            if w.signal_dbm:
                parts.append(f"{w.signal_dbm} dBm")
            return "  ·  ".join(parts) if parts else "--"

        if ctrl:
            self._kv("dial-model", "Model", _sku_or_none(ctrl.model_sku) or "--")
            self._kv("dial-serial", "Serial", ctrl.serial_number or "--")
            self._kv("dial-fw", "Firmware", ctrl.firmware_version or "--")
            self._kv(
                "dial-ambient",
                "Ambient",
                _tc(ctrl.calibrated_ambient_c, use_f),
                "green",
            )
            self._kv(
                "dial-calib",
                "Raw Thermistor",
                _tc(ctrl.raw_thermistor_c, use_f),
            )
            self._kv(
                "dial-pcb",
                "PCB A / B",
                f"{_tc(ctrl.pcb_temperature_a_c, use_f)}  /  "
                f"{_tc(ctrl.pcb_temperature_b_c, use_f)}",
            )
            # Wi-Fi status: SSID, band, signal
            wifi_parts = []
            if ctrl.wifi_ssid:
                wifi_parts.append(ctrl.wifi_ssid)
            if ctrl.wifi_band:
                wifi_parts.append(ctrl.wifi_band)
            if ctrl.wifi_signal_dbm:
                wifi_parts.append(f"{ctrl.wifi_signal_dbm} dBm")
            self._kv("dial-wifi", "WiFi", "  ·  ".join(wifi_parts) or "--")
            self._kv("dial-wifi-ip", "  IP", ctrl.wifi_ip or "--")
            # Last seen: format as local time if available
            if ctrl.wifi_last_seen:
                local_ts = ctrl.wifi_last_seen.astimezone()
                last_seen_str = local_ts.strftime("%Y-%m-%d %H:%M:%S")
            else:
                last_seen_str = "--"
            self._kv("dial-wifi-last", "  Last Seen", last_seen_str)
            self._kv("dial-wifi-ap", "WiFi (AP)", _wifi_str(ctrl.ap_wifi))
            self._kv("dial-wifi-p2p", "WiFi (P2P)", _wifi_str(ctrl.p2p_wifi))
            rsm = ctrl.remote_sensor_mode
            rsm_str = (
                "Enabled"
                if rsm.name == "ENABLED"
                else ("Disabled" if rsm.name == "DISABLED" else "--")
            )
            rsm_style = "green" if rsm.name == "ENABLED" else "dim"
            self._kv("dial-remote-sensor", "Zone Sensor", rsm_str, rsm_style)
            # ControllerRemoteSensor — Dial acting as zone sensor
            crs = next(
                (
                    r
                    for r in self._snapshot.controller_remote_sensors
                    if r.controller_id == ctrl.id
                ),
                None,
            )
            if crs:
                self._kv(
                    "dial-crs-temp",
                    "  Zone Temp",
                    _tc(crs.ambient_temperature_c, use_f),
                    "green",
                )
                self._kv(
                    "dial-crs-humidity",
                    "  Zone Humidity",
                    f"{crs.humidity_percent:.0f}%" if crs.humidity_percent else "--",
                )
                self._kv(
                    "dial-crs-battery",
                    "  Battery",
                    f"{crs.battery_level_percent:.0f}%" if crs.battery_level_percent else "--",
                )
                self._kv(
                    "dial-crs-signal",
                    "  Signal",
                    f"{crs.signal_level_dbm} dBm" if crs.signal_level_dbm else "--",
                )
            else:
                self._kv("dial-crs-temp", "  Zone Temp", "--")
                self._kv("dial-crs-humidity", "  Zone Humidity", "--")
                self._kv("dial-crs-battery", "  Battery", "--")
                self._kv("dial-crs-signal", "  Signal", "--")
        else:
            for nid in (
                "dial-model",
                "dial-serial",
                "dial-fw",
                "dial-ambient",
                "dial-calib",
                "dial-pcb",
                "dial-wifi",
                "dial-wifi-ip",
                "dial-wifi-last",
                "dial-wifi-ap",
                "dial-wifi-p2p",
                "dial-remote-sensor",
                "dial-crs-temp",
                "dial-crs-humidity",
                "dial-crs-battery",
                "dial-crs-signal",
            ):
                self._kv(
                    nid,
                    nid.replace("dial-", "").replace("-", " ").title(),
                    "--",
                )

        # QSM / Smart Module
        qsm = self._qsm

        if qsm:
            self._kv("qsm-wifi-hosted", "WiFi (hosted)", _wifi_str(qsm.hosted_wifi))
            self._kv("qsm-wifi-ap", "WiFi (AP)", _wifi_str(qsm.ap_wifi))
            self._kv("qsm-wifi-p2p", "WiFi (P2P)", _wifi_str(qsm.p2p_wifi))
            if qsm.sensors:
                s = qsm.sensors
                self._kv(
                    "qsm-presence",
                    "Presence",
                    f"phase {s.phase_detected_raw:.3f}  target {s.target_detected_raw:.3f}",
                )
                self._kv(
                    "qsm-als",
                    "Light (ALS)",
                    f"illum {s.als_illuminance_raw}  IR {s.als_ir_raw}  both {s.als_both_raw}",
                )
                self._kv(
                    "qsm-accel",
                    "Accel X/Y/Z",
                    f"{s.accel_x_raw}  /  {s.accel_y_raw}  /  {s.accel_z_raw}",
                )
            else:
                for nid, lbl in [
                    ("qsm-presence", "Presence"),
                    ("qsm-als", "ALS"),
                    ("qsm-accel", "Accel"),
                ]:
                    self._kv(nid, lbl, "--")
        else:
            for nid, lbl in [
                ("qsm-wifi-hosted", "WiFi (hosted)"),
                ("qsm-wifi-ap", "WiFi (AP)"),
                ("qsm-wifi-p2p", "WiFi (P2P)"),
                ("qsm-presence", "Presence"),
                ("qsm-als", "ALS"),
                ("qsm-accel", "Accel"),
            ]:
                self._kv(nid, lbl, "no QSM")

    def _populate_perf(self) -> None:
        idu = self._idu
        odu = self._odu
        use_f = self.use_f

        _COND_STATE_LABELS = {0: "—", 1: "inactive", 2: "ACTIVE"}
        _COND_ACTIVE_STYLE = "bold red"

        if idu and idu.performance_data:
            pd = idu.performance_data
            self._kv("p-coil", "Coil Temp", _tc(pd.coil_temperature_c, use_f))
            self._kv("p-outlet", "Outlet Temp", _tc(pd.outlet_temperature_c, use_f))
            self._kv("p-inlet", "Inlet Temp", _tc(pd.inlet_temperature_c, use_f))
            self._kv("p-gas", "Gas Pipe Temp", _tc(pd.gas_pipe_temperature_c, use_f))
            self._kv(
                "p-liquid",
                "Liquid Pipe Temp",
                _tc(pd.liquid_pipe_temperature_c, use_f),
            )
            self._kv(
                "p-interval",
                "Sample Interval",
                f"{pd.measurement_interval_s:.1f} s",
            )
            # energy_measurement_j is IDU electronics (QSM + fan board),
            # not HVAC/compressor energy.
            # Actual HVAC power is in performance_metrics below.
            pwr = (
                pd.energy_measurement_j / pd.measurement_interval_s
                if pd.measurement_interval_s > 0
                else 0
            )
            self._kv("p-energy-j", "IDU Module Power", f"{pwr:.1f} W")
            self._kv(
                "p-energy-kwh",
                "IDU Module Energy",
                f"{pd.energy_measurement_j:.1f} J",
            )
            self._kv(
                "p-fan-actual",
                "Fan (actual)",
                f"{pd.actual_fan_speed_rpm:.0f} RPM",
            )
            self._kv(
                "p-pd-mode",
                "Mode (perf)",
                pd.hvac_mode.name,
                _MODE_STYLE.get(pd.hvac_mode, ""),
            )
            pd_state_fmt = _fmt_state(pd.hvac_state)
            self._kv(
                "p-pd-state",
                "State (perf)",
                pd_state_fmt.plain,
                str(pd_state_fmt.style),
            )
        else:
            for nid, label in [
                ("p-coil", "Coil"),
                ("p-outlet", "Outlet"),
                ("p-inlet", "Inlet"),
                ("p-gas", "Gas Pipe"),
                ("p-liquid", "Liquid Pipe"),
                ("p-interval", "Interval"),
                ("p-energy-j", "Energy J"),
                ("p-energy-kwh", "Energy kWh"),
                ("p-fan-actual", "Fan actual"),
                ("p-pd-mode", "Mode (perf)"),
                ("p-pd-state", "State (perf)"),
            ]:
                self._kv(nid, label, "no data")

        if idu and idu.performance_metrics:
            pm = idu.performance_metrics
            self._kv("p-capacity", "Capacity", f"{pm.capacity_w:.0f} W")
            self._kv("p-cop", "COP", f"{pm.coefficient_of_performance:.2f}")
            self._kv("p-hvac-power", "HVAC Power", f"{pm.hvac_power_w:.0f} W")
            self._kv("p-led-power", "LED Power", f"{pm.led_power_w:.1f} W")
            self._kv(
                "p-pm-mode",
                "Mode (metrics)",
                pm.hvac_mode.name,
                _MODE_STYLE.get(pm.hvac_mode, ""),
            )
            pm_state_fmt = _fmt_state(pm.hvac_state)
            self._kv(
                "p-pm-state",
                "State (metrics)",
                pm_state_fmt.plain,
                str(pm_state_fmt.style),
            )
            self._kv("p-pm-duration", "Window", f"{pm.measurement_duration_s:.1f} s")
            self._kv(
                "p-pm-energy-total",
                "Energy (total)",
                f"{pm.energy_total_j:.1f} J",
            )
            self._kv("p-pm-hvac-energy", "Energy (HVAC)", f"{pm.hvac_energy_j:.1f} J")
            self._kv("p-pm-led-energy", "Energy (LED)", f"{pm.led_energy_j:.1f} J")
        else:
            for nid, label in [
                ("p-capacity", "Capacity"),
                ("p-cop", "COP"),
                ("p-hvac-power", "HVAC Power"),
                ("p-led-power", "LED Power"),
                ("p-pm-mode", "Mode (metrics)"),
                ("p-pm-state", "State (metrics)"),
                ("p-pm-duration", "Window"),
                ("p-pm-energy-total", "Energy (total)"),
                ("p-pm-hvac-energy", "Energy (HVAC)"),
                ("p-pm-led-energy", "Energy (LED)"),
            ]:
                self._kv(nid, label, "no data")

        if idu and idu.hvac_inputs:
            hi = idu.hvac_inputs
            self._kv(
                "p-hi-ext-ambient",
                "Ext. Ambient",
                _tc(hi.external_ambient_temperature_c, use_f),
            )
            self._kv(
                "p-hi-setpoint",
                "Setpoint (ctrl)",
                _tc(hi.temperature_setpoint_c, use_f),
            )
            self._kv(
                "p-hi-mode",
                "Mode (ctrl)",
                hi.hvac_mode.name,
                _MODE_STYLE.get(hi.hvac_mode, ""),
            )
            hi_state_fmt = _fmt_state(hi.hvac_state)
            self._kv(
                "p-hi-state",
                "State (ctrl)",
                hi_state_fmt.plain,
                str(hi_state_fmt.style),
            )
            self._kv(
                "p-hi-source",
                "Ambient Source",
                str(hi.ambient_temperature_source),
            )
            ctrl_type = hi.hvac_controller_type
            ctrl_type_short = (
                ctrl_type.name.replace("HVAC_CONTROLLER_TYPE_", "").replace("_", " ").title()
            )
            self._kv("p-hi-ctrl-type", "Controller Type", ctrl_type_short)
        else:
            for nid, label in [
                ("p-hi-ext-ambient", "Ext. Ambient"),
                ("p-hi-setpoint", "Setpoint (ctrl)"),
                ("p-hi-mode", "Mode (ctrl)"),
                ("p-hi-state", "State (ctrl)"),
                ("p-hi-source", "Ambient Source"),
                ("p-hi-ctrl-type", "Controller Type"),
            ]:
                self._kv(nid, label, "no data")

        if idu and idu.conditions:
            co = idu.conditions

            def _cs(val: int) -> tuple[str, str]:
                return _COND_STATE_LABELS.get(val, str(val)), (
                    _COND_ACTIVE_STYLE if val == 2 else ""
                )

            for nid, label, val in [
                ("p-cond-defrost", "Defrost Cycle", co.defrost_cycle),
                ("p-cond-oilreturn", "Oil Return", co.oil_return),
                ("p-cond-coilpreheat", "Coil Preheat", co.coil_preheat),
                ("p-cond-safetyheat", "Safety Heating", co.safety_heating),
                ("p-cond-anticold", "Anti-Cold Wind", co.anti_cold_wind),
                (
                    "p-cond-modeswitch",
                    "Mode Switch Delay",
                    co.hvac_mode_switching_delay,
                ),
                ("p-cond-modeconflict", "Mode Conflict", co.mode_conflict),
                (
                    "p-cond-modeconflictavoid",
                    "Mode Conflict Avoid",
                    co.mode_conflict_avoidance,
                ),
                (
                    "p-cond-abnormal-odu-air",
                    "Abnormal ODU Air",
                    co.abnormal_outdoor_air_temperature,
                ),
                (
                    "p-cond-odu-comm",
                    "ODU Comm Error",
                    co.outdoor_unit_communication_error,
                ),
                (
                    "p-cond-modbus",
                    "Modbus Comm Error",
                    co.modbus_communication_error,
                ),
            ]:
                text, style = _cs(val)
                self._kv(nid, label, text, style)
        else:
            for nid, label in [
                ("p-cond-defrost", "Defrost Cycle"),
                ("p-cond-oilreturn", "Oil Return"),
                ("p-cond-coilpreheat", "Coil Preheat"),
                ("p-cond-safetyheat", "Safety Heating"),
                ("p-cond-anticold", "Anti-Cold Wind"),
                ("p-cond-modeswitch", "Mode Switch Delay"),
                ("p-cond-modeconflict", "Mode Conflict"),
                ("p-cond-modeconflictavoid", "Mode Conflict Avoid"),
                ("p-cond-abnormal-odu-air", "Abnormal ODU Air"),
                ("p-cond-odu-comm", "ODU Comm Error"),
                ("p-cond-modbus", "Modbus Comm Error"),
            ]:
                self._kv(nid, label, "no data")

        if odu:
            hs = HVACState(odu.hvac_state)
            odu_state_str = hs.name if odu.hvac_state else "—"
            odu_state_style = _STATE_STYLE.get(hs, "dim") if odu.hvac_state else "dim"
            self._kv("p-odu-state", "ODU State", odu_state_str, odu_state_style)
            self._kv("p-odu-model", "Model", _sku_or_none(odu.model_sku) or "--")
            self._kv("p-odu-serial", "Serial", odu.serial_number or "--")
            self._kv("p-odu-fw", "Firmware", odu.firmware_version or "--")
            if odu.performance_data:
                pd = odu.performance_data
                self._kv(
                    "p-odu-freq",
                    "Compressor Freq",
                    f"{pd.compressor_frequency_hz:.1f} Hz",
                )
                self._kv(
                    "p-odu-coil",
                    "ODU Coil Temp",
                    _tc(pd.coil_temperature_c, use_f),
                )
                self._kv(
                    "p-odu-exhaust",
                    "Exhaust Temp",
                    _tc(pd.exhaust_temperature_c, use_f),
                )
                self._kv(
                    "p-odu-hi",
                    "High Pressure",
                    f"{pd.high_pressure_kpa:.1f} kPa",
                )
                self._kv("p-odu-lo", "Low Pressure", f"{pd.low_pressure_kpa:.1f} kPa")
                self._kv(
                    "p-odu-ambient",
                    "ODU Ambient",
                    _tc(pd.ambient_temperature_c, use_f),
                )
            else:
                for nid in (
                    "p-odu-freq",
                    "p-odu-coil",
                    "p-odu-exhaust",
                    "p-odu-hi",
                    "p-odu-lo",
                    "p-odu-ambient",
                ):
                    self._kv(nid, nid, "no data")
        else:
            for nid in (
                "p-odu-state",
                "p-odu-freq",
                "p-odu-coil",
                "p-odu-exhaust",
                "p-odu-hi",
                "p-odu-lo",
                "p-odu-ambient",
                "p-odu-model",
                "p-odu-serial",
                "p-odu-fw",
            ):
                self._kv(nid, nid, "no ODU")

        # IDU Commands (fallback control on connectivity loss)
        if idu and idu.commands:
            fc = idu.commands.fallback_control_command
            fc_str = fc.name.replace("FALLBACK_CONTROL_COMMAND_", "").replace("_", " ").title()
            self._kv("p-cmd-fallback", "Fallback Command", fc_str)
        else:
            self._kv("p-cmd-fallback", "Fallback Command", "--")

    def _populate_schedule(self) -> None:
        space_id = self._space.id
        snap = self._snapshot

        week = next((w for w in snap.schedule_weeks if w.space_id == space_id), None)
        self._sched_day_by_id = {d.id: d for d in snap.schedule_days}
        self._sched_cs_by_id = {cs.id: cs for cs in snap.comfort_settings}

        _DAYS = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]

        week_table: DataTable = self.query_one("#sched-week", DataTable)
        if not week_table.columns:
            week_table.add_columns("Day")

        week_table.clear()
        # Each weekday can map to multiple day programs (one event each).
        # _sched_row_day_ids[i] is a list of day_ids for weekday i+1.
        self._sched_row_day_ids: list[list[str]] = [[] for _ in _DAYS]

        if week:
            for wd in week.days:
                idx = wd.weekday - 1  # weekday 1=Mon … 7=Sun → 0-based
                if 0 <= idx < 7:
                    self._sched_row_day_ids[idx].append(wd.day_id)
            for day_name in _DAYS:
                week_table.add_row(day_name)
            # Show Monday's events by default
            self._populate_day_events(
                [
                    self._sched_day_by_id[did]
                    for did in self._sched_row_day_ids[0]
                    if did in self._sched_day_by_id
                ],
                self._sched_cs_by_id,
                label="Monday",
            )
        else:
            for day_name in _DAYS:
                week_table.add_row(day_name)
            self._populate_day_events([], {}, label="Monday")

        loc = snap.primary_location
        self._update_schedule_status(loc.schedule_paused if loc else False)

    @on(DataTable.RowHighlighted, "#sched-week")
    def _on_sched_week_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        _DAYS = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
        idx = event.cursor_row
        row_ids = getattr(self, "_sched_row_day_ids", [[] for _ in _DAYS])
        cs_by_id = getattr(self, "_sched_cs_by_id", {})
        day_by_id = getattr(self, "_sched_day_by_id", {})
        day_ids = row_ids[idx] if idx < len(row_ids) else []
        days = [day_by_id[did] for did in day_ids if did in day_by_id]
        self._populate_day_events(days, cs_by_id, label=_DAYS[idx] if idx < 7 else "")

    def _populate_day_events(self, days: list, cs_by_id: dict, label: str = "") -> None:
        from quilt_hp.models.enums import HVACMode as _HM
        from quilt_hp.models.enums import LouverMode as _LM
        from quilt_hp.models.schedule import ScheduleDay

        if label:
            with contextlib.suppress(Exception):
                self.query_one("#sched-events-panel").border_title = label

        day_table: DataTable = self.query_one("#sched-day", DataTable)
        if not day_table.columns:
            day_table.add_columns("Time", "Mode", "Heat", "Cool", "Fan", "Preset")
        day_table.clear()

        # Gather events across day programs for this weekday, sorted by time.
        all_events = sorted(
            (ev for day in days if isinstance(day, ScheduleDay) for ev in day.events),
            key=lambda e: e.start_s,
        )

        if not all_events:
            day_table.add_row("--", "[dim]no events[/dim]", "--", "--", "--", "--")
            return

        for ev in all_events:
            ev_mode = _HM(ev.hvac_mode) if ev.hvac_mode else _HM.UNSPECIFIED
            preset_name = ""
            fan_str = "--"
            heat = ev.heating_setpoint_c
            cool = ev.cooling_setpoint_c

            if ev.comfort_setting_id:
                cs = cs_by_id.get(ev.comfort_setting_id)
                if cs:
                    preset_name = cs.name
                    ev_mode = cs.hvac_mode
                    heat = cs.heating_setpoint_c
                    cool = cs.cooling_setpoint_c
                    fan_str = cs.fan_speed.name.replace("FAN_SPEED_", "").title()
                    lm = cs.louver_mode
                    if lm not in (_LM.UNSPECIFIED, _LM.AUTO):
                        louver = (
                            f"FIXED {cs.louver_fixed_position:.0f}°"
                            if lm == _LM.FIXED and cs.louver_fixed_position
                            else lm.name
                        )
                        fan_str = f"{fan_str} / {louver}"

            mode_str = ev_mode.name.replace("HVAC_MODE_", "").replace("_", " ").title()
            day_table.add_row(
                ev.start_time or "--",
                mode_str,
                _tc(heat, self.use_f) if heat else "--",
                _tc(cool, self.use_f) if cool else "--",
                fan_str,
                preset_name or "--",
            )

    def _update_schedule_status(self, paused: bool) -> None:
        try:
            status = (
                "[yellow]⏸ PAUSED[/yellow]  [dim](p to resume)[/dim]"
                if paused
                else "[green]▶ RUNNING[/green]"
            )
            self.query_one("#sched-status", Static).update(status)
        except NoMatches:
            pass

    # ── Energy ──────────────────────────────────────────────────

    @work
    async def _fetch_energy(self) -> None:
        """Fetch 30 days of hourly room energy data for summary totals."""
        try:
            self._set_energy_status("⟳ Loading energy data…")
            tz = datetime.UTC
            snap_tz = self._snapshot.timezone
            if snap_tz:
                try:
                    import zoneinfo

                    tz = zoneinfo.ZoneInfo(snap_tz)
                except Exception:
                    pass
            now = datetime.datetime.now(tz)
            start = (now - datetime.timedelta(days=30)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            metrics = await self._client.get_energy(start=start, end=now)
            space_metrics = next((m for m in metrics if m.space_id == self._space.id), None)
            self._populate_energy(space_metrics, tz)
            self._set_energy_status("")
        except Exception as exc:
            self._set_energy_status(f"[red]Energy fetch failed: {exc}[/red]")

    def _set_energy_status(self, msg: str) -> None:
        try:
            self.query_one("#energy-status", Static).update(msg)
        except NoMatches:
            pass

    def _populate_energy(self, metrics: object | None, tz: datetime.timezone) -> None:
        from quilt_hp.models.energy import SpaceEnergyMetrics

        table: DataTable = self.query_one("#e-table", DataTable)
        if not table.columns:
            table.add_columns("Date", "Hour", "kWh", "Status")

        if metrics is None or not isinstance(metrics, SpaceEnergyMetrics) or not metrics.buckets:
            self._kv("e-today", "Today", "no data")
            self._kv("e-yesterday", "Yesterday", "no data")
            self._kv("e-7day", "Last 7 days", "no data")
            self._kv("e-30day", "Last 30 days", "no data")
            try:
                self.query_one("#e-sparkline", Static).update("no energy data")
            except NoMatches:
                pass
            return

        now = datetime.datetime.now(tz)
        today = now.date()
        yesterday = today - datetime.timedelta(days=1)

        # Group buckets by local date.
        # Buckets are UTC-aware from the service; astimezone converts them.
        by_date: dict[datetime.date, list] = {}
        for b in metrics.buckets:
            bt = b.start_time
            if bt.tzinfo is None:
                # Defensive: treat naive datetimes as UTC.
                bt = bt.replace(tzinfo=datetime.UTC)
            bt_local = bt.astimezone(tz)
            d = bt_local.date()
            by_date.setdefault(d, []).append((bt_local, b.energy_kwh, b.status))

        def _day_total(d: datetime.date) -> float:
            return sum(kwh for _, kwh, _ in by_date.get(d, []))

        today_kwh = _day_total(today)
        yest_kwh = _day_total(yesterday)
        week_kwh = sum(_day_total(today - datetime.timedelta(days=i)) for i in range(7))
        month_kwh = sum(_day_total(today - datetime.timedelta(days=i)) for i in range(30))

        self._kv("e-today", "Today", f"{today_kwh:.3f} kWh", "cyan")
        self._kv("e-yesterday", "Yesterday", f"{yest_kwh:.3f} kWh")
        self._kv("e-7day", "Last 7 days", f"{week_kwh:.3f} kWh")
        self._kv("e-30day", "Last 30 days", f"{month_kwh:.3f} kWh")

        # Sparkline — today so far, 24 fixed hourly slots (00–23 local time)
        cutoff = now - datetime.timedelta(hours=24)
        today_hours = by_date.get(today, [])
        blocks = " ▁▂▃▄▅▆▇█"
        if today_hours:
            max_kwh = max(kwh for _, kwh, _ in today_hours) or 1.0
            hour_map = {bt.hour: kwh for bt, kwh, _ in today_hours}
            bar_chars = []
            for h in range(24):
                kwh = hour_map.get(h, 0.0)
                idx = min(int(kwh / max_kwh * 8), 8)
                bar_chars.append(blocks[idx])
            sparkline = "".join(bar_chars)
            labels = "00  03  06  09  12  15  18  21  23"
            spark_str = f"{sparkline}\n[dim]{labels}[/dim]"
        else:
            spark_str = "[dim]no energy data for today[/dim]"

        try:
            self.query_one("#e-sparkline", Static).update(spark_str)
        except NoMatches:
            pass

        # Populate hourly table — last 24 hours only (most recent first)
        table.clear()
        status_labels = {0: "—", 1: "✓", 2: "~"}
        recent_buckets = [
            (bt, kwh, s) for buckets in by_date.values() for bt, kwh, s in buckets if bt >= cutoff
        ]
        for bt, kwh, status in sorted(recent_buckets, reverse=True):
            table.add_row(
                bt.strftime("%Y-%m-%d"),
                bt.strftime("%H:00"),
                f"{kwh:.4f}",
                status_labels.get(status, str(status)),
            )

    def _kv(self, widget_id: str, key: str, value: str, val_style: str = "") -> None:
        try:
            w = self.query_one(f"#{widget_id}", _KVStatic)
            w.set_kv(key, value, val_style)
        except NoMatches:
            pass

    # ── Live update entry points ─────────────────────────────────

    def update_space(self, space: Space) -> None:
        self._space = space
        self._populate_status()

    def update_idu(self, idu: IndoorUnit) -> None:
        self._idu = idu
        odu = self._snapshot.odu_for_idu(idu)
        if odu is None:
            space_ids = _id_tokens(self._space.id)
            odu = next(
                (u for u in self._snapshot.outdoor_units if _id_tokens(u.space_id) & space_ids),
                None,
            )
        self._odu = odu
        self._populate_status()
        self._populate_perf()

    def update_odu(self, odu: OutdoorUnit) -> None:
        self._odu = odu
        self._populate_status()
        self._populate_perf()

    def update_ctrl(self, ctrl: Controller) -> None:
        self._controller = ctrl
        self._populate_status()

    def update_qsm(self, qsm: QuiltSmartModule) -> None:
        self._qsm = qsm
        self._populate_status()

    # ── Actions ─────────────────────────────────────────────────

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_refresh_energy(self) -> None:
        self._fetch_energy()

    def action_toggle_units(self) -> None:
        self.use_f = not self.use_f
        self.app._persist()
        self._populate_status()
        self._populate_perf()

    def action_cycle_mode(self) -> None:
        if not self._space or not self._space.controls:
            return
        # If the room is currently AWAY (STANDBY + comfort setting), the next
        # meaningful step is plain STANDBY (OFF), not skipping ahead to HEAT.
        if self._space.is_away:
            self._mutate_space(mode=HVACMode.STANDBY)
        else:
            nxt = _cycle_next(self._space.controls.hvac_mode, _MODE_CYCLE)
            self._mutate_space(mode=nxt)

    def action_heat_up(self) -> None:
        self._delta_setpoint("heat", +0.5)

    def action_heat_down(self) -> None:
        self._delta_setpoint("heat", -0.5)

    def action_cool_up(self) -> None:
        self._delta_setpoint("cool", +0.5)

    def action_cool_down(self) -> None:
        self._delta_setpoint("cool", -0.5)

    def _delta_setpoint(self, which: str, delta: float) -> None:
        if not self._space or not self._space.controls:
            return
        c = self._space.controls
        if which == "heat":
            val = (c.heating_setpoint_c or 20.0) + delta
            self._mutate_space(heat_setpoint_c=val)
        else:
            val = (c.cooling_setpoint_c or 26.0) + delta
            self._mutate_space(cool_setpoint_c=val)

    def action_cycle_fan(self) -> None:
        if not self._idu:
            return
        nxt = _cycle_next(self._idu.controls.fan_speed, _FAN_CYCLE)
        self._mutate_idu(fan_speed=nxt)

    def action_cycle_louver(self) -> None:
        if not self._idu:
            return
        nxt = _cycle_next(self._idu.controls.louver_mode, _LOUVER_CYCLE)
        self._mutate_idu(louver_mode=nxt)

    def action_toggle_led(self) -> None:
        if not self._idu:
            return
        new_brightness = 0.0 if self._idu.controls.light_on else 1.0
        self._mutate_idu(led_brightness=new_brightness)

    def action_cycle_occupancy(self) -> None:
        if not self._space:
            return
        nxt = _cycle_next(self._space.settings.occupancy_mode, _OCC_CYCLE)
        # occupancy_mode is a settings field; mutate via a future API if added.
        # For now notify the user it's read-only in this version.
        self.notify(f"Occupancy mode would → {nxt.name} (not yet wired)", timeout=3)

    _AWAY_TIMEOUT_STEP_S: float = 300.0  # 5 minutes
    _RETURN_TIMEOUT_STEP_S: float = 60.0  # 1 minute
    _TIMEOUT_MIN_S: float = 60.0  # 1 minute minimum

    def action_away_timeout_dec(self) -> None:
        if not self._space:
            return
        cur = self._space.settings.unoccupied_timeout_s
        self._mutate_settings(
            unoccupied_timeout_s=max(self._TIMEOUT_MIN_S, cur - self._AWAY_TIMEOUT_STEP_S)
        )

    def action_away_timeout_inc(self) -> None:
        if not self._space:
            return
        cur = self._space.settings.unoccupied_timeout_s
        self._mutate_settings(unoccupied_timeout_s=cur + self._AWAY_TIMEOUT_STEP_S)

    def action_return_timeout_dec(self) -> None:
        if not self._space:
            return
        cur = self._space.settings.occupied_timeout_s
        self._mutate_settings(
            occupied_timeout_s=max(self._TIMEOUT_MIN_S, cur - self._RETURN_TIMEOUT_STEP_S)
        )

    def action_return_timeout_inc(self) -> None:
        if not self._space:
            return
        cur = self._space.settings.occupied_timeout_s
        self._mutate_settings(occupied_timeout_s=cur + self._RETURN_TIMEOUT_STEP_S)

    def action_toggle_schedule(self) -> None:
        loc = self._snapshot.primary_location
        if loc is None:
            self.notify("No location found", severity="error")
            return
        self._do_toggle_schedule(not loc.schedule_paused)

    @work
    async def _mutate_space(
        self,
        mode: HVACMode | None = None,
        heat_setpoint_c: float | None = None,
        cool_setpoint_c: float | None = None,
    ) -> None:
        try:
            updated = await self._client.set_space(
                self._space,
                mode=mode,
                heat_setpoint_c=heat_setpoint_c,
                cool_setpoint_c=cool_setpoint_c,
            )
            self._space = updated
            self._populate_status()
        except Exception as exc:
            self.notify(f"Error: {exc}", severity="error")

    @work
    async def _mutate_settings(
        self,
        unoccupied_timeout_s: float | None = None,
        occupied_timeout_s: float | None = None,
    ) -> None:
        """Update space auto-away / auto-return timeouts."""
        try:
            updated = await self._client.set_space_settings(
                self._space,
                unoccupied_timeout_s=unoccupied_timeout_s,
                occupied_timeout_s=occupied_timeout_s,
            )
            self._space = updated
            self._populate_status()
        except Exception as exc:
            self.notify(f"Error: {exc}", severity="error")

    @work
    async def _mutate_idu(
        self,
        fan_speed: FanSpeed | None = None,
        louver_mode: LouverMode | None = None,
        led_brightness: float | None = None,
    ) -> None:
        if not self._idu:
            return
        try:
            updated = await self._client.set_indoor_unit(
                self._idu,
                fan_speed=fan_speed,
                louver_mode=louver_mode,
                led_brightness=led_brightness,
            )
            self._idu = updated
            self._populate_status()
        except Exception as exc:
            self.notify(f"Error: {exc}", severity="error")

    _FENCE_STEP_M = 0.5

    def action_fence_fwd_inc(self) -> None:
        if self._idu:
            cur = self._idu.settings.presence_fence_forward_m
            self._mutate_idu_settings(fence_forward_m=round(cur + self._FENCE_STEP_M, 2))

    def action_fence_fwd_dec(self) -> None:
        if self._idu:
            cur = self._idu.settings.presence_fence_forward_m
            self._mutate_idu_settings(fence_forward_m=max(0.0, round(cur - self._FENCE_STEP_M, 2)))

    def action_fence_lr_inc(self) -> None:
        if self._idu:
            st = self._idu.settings
            step = self._FENCE_STEP_M
            self._mutate_idu_settings(
                fence_left_m=round(st.presence_fence_left_m + step, 2),
                fence_right_m=round(st.presence_fence_right_m + step, 2),
            )

    def action_fence_lr_dec(self) -> None:
        if self._idu:
            st = self._idu.settings
            step = self._FENCE_STEP_M
            self._mutate_idu_settings(
                fence_left_m=max(0.0, round(st.presence_fence_left_m - step, 2)),
                fence_right_m=max(0.0, round(st.presence_fence_right_m - step, 2)),
            )

    def action_radar_height_inc(self) -> None:
        if self._idu:
            cur = self._idu.settings.radar_sensor_distance_from_floor_m
            self._mutate_idu_settings(radar_height_m=round(cur + self._FENCE_STEP_M, 2))

    def action_radar_height_dec(self) -> None:
        if self._idu:
            cur = self._idu.settings.radar_sensor_distance_from_floor_m
            self._mutate_idu_settings(radar_height_m=max(0.0, round(cur - self._FENCE_STEP_M, 2)))

    @work
    async def _mutate_idu_settings(
        self,
        fence_left_m: float | None = None,
        fence_right_m: float | None = None,
        fence_forward_m: float | None = None,
        radar_height_m: float | None = None,
    ) -> None:
        if not self._idu:
            return
        try:
            updated = await self._client.set_indoor_unit_settings(
                self._idu,
                fence_left_m=fence_left_m,
                fence_right_m=fence_right_m,
                fence_forward_m=fence_forward_m,
                radar_height_m=radar_height_m,
            )
            self._idu = updated
            self._populate_status()
        except Exception as exc:
            self.notify(f"Fence update error: {exc}", severity="error")

    @work
    async def _do_toggle_schedule(self, paused: bool) -> None:
        try:
            await self._client.set_schedule_execution(paused)
            loc = self._snapshot.primary_location
            if loc:
                # patch local cache
                from dataclasses import replace

                patched = replace(loc, schedule_paused=paused)
                self._snapshot.locations[0] = patched
            self._update_schedule_status(paused)
            self.notify("Schedules " + ("paused" if paused else "resumed"), timeout=2)
        except Exception as exc:
            self.notify(f"Error: {exc}", severity="error")


# ──────────────────────────────────────────────────────────────────
# SystemScreen
# ──────────────────────────────────────────────────────────────────


class SystemScreen(Screen):
    """System-wide overview: ODU, controllers, remote sensors."""

    BINDINGS: ClassVar = [
        Binding("escape,b", "back", "Back"),
        Binding("u", "toggle_units", "°C/°F"),
        Binding("p", "toggle_schedule", "Pause Sched"),
    ]

    use_f: reactive[bool] = reactive(False)

    def __init__(
        self,
        snapshot: SystemSnapshot,
        client: QuiltClient,
        *,
        use_f: bool = False,
    ) -> None:
        super().__init__()
        self._snapshot = snapshot
        self._client = client
        self.use_f = use_f

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="system-container"):
            # System header
            with Vertical(classes="odu-panel") as v:
                v.border_title = "System"
                yield Static(id="sys-header")

            # ODU row — one panel per outdoor unit
            with Horizontal(id="odu-row"):
                if self._snapshot.outdoor_units:
                    for i in range(len(self._snapshot.outdoor_units)):
                        with Vertical(classes="odu-panel") as v:
                            v.border_title = (
                                f"Outdoor Unit {i + 1}"
                                if len(self._snapshot.outdoor_units) > 1
                                else "Outdoor Unit"
                            )
                            yield Static(id=f"sys-odu-{i}")
                else:
                    yield Static("[dim]No outdoor unit data[/dim]", id="sys-odu-0")

            # Controllers
            with Vertical(classes="odu-panel") as v:
                v.border_title = "Controllers (Dials)"
                yield DataTable(id="sys-ctrls")

            # Remote sensors
            with Vertical(classes="odu-panel") as v:
                v.border_title = "Remote Sensors"
                yield DataTable(id="sys-sensors")

            # Firmware / software update status
            with Vertical(classes="odu-panel") as v:
                v.border_title = "Firmware / Software Updates"
                yield DataTable(id="sys-firmware")
        yield Footer()

    def on_mount(self) -> None:
        self._populate()

    def _populate(self) -> None:
        snap = self._snapshot
        use_f = self.use_f

        # Header
        loc = snap.primary_location
        tz = snap.timezone or "?"
        sched = (
            "[yellow]⏸ PAUSED[/yellow]"
            if (loc and loc.schedule_paused)
            else "[green]▶ RUNNING[/green]"
        )
        loc_name = loc.name if loc and loc.name else ""
        header_parts = []
        if loc_name:
            header_parts.append(f"[bold]{loc_name}[/bold]")
        header_parts.append(f"[bold]Timezone:[/bold] {tz}")
        header_parts.append(f"[bold]Schedule:[/bold] {sched}")
        self.query_one("#sys-header", Static).update("   ".join(header_parts))

        # ODU panels — one per unit
        for i, odu in enumerate(snap.outdoor_units):
            odu_lines: list[str] = []
            hs = HVACState(odu.hvac_state)
            state = hs.name if odu.hvac_state else "—"
            state_style = _STATE_STYLE.get(hs, "dim") if odu.hvac_state else "dim"
            odu_lines.append(f"[{state_style}]State: {state}[/{state_style}]")
            model = _sku_or_none(odu.model_sku)
            if model:
                odu_lines.append(f"Model:    {model}")
            if odu.serial_number:
                odu_lines.append(f"Serial:   {odu.serial_number}")
            if odu.firmware_version:
                odu_lines.append(f"Firmware: {odu.firmware_version}")
            if odu.performance_data:
                pd = odu.performance_data
                odu_lines.append(f"Compressor:  {pd.compressor_frequency_hz:.1f} Hz")
                odu_lines.append(f"ODU Coil:    {_tc(pd.coil_temperature_c, use_f)}")
                odu_lines.append(f"Exhaust:     {_tc(pd.exhaust_temperature_c, use_f)}")
                odu_lines.append(f"Hi Pressure: {pd.high_pressure_kpa:.1f} kPa")
                odu_lines.append(f"Lo Pressure: {pd.low_pressure_kpa:.1f} kPa")
                odu_lines.append(f"ODU Ambient: {_tc(pd.ambient_temperature_c, use_f)}")
            self.query_one(f"#sys-odu-{i}", Static).update("\n".join(odu_lines))

        # Controllers table
        ctrl_table: DataTable = self.query_one("#sys-ctrls", DataTable)
        if not ctrl_table.columns:
            ctrl_table.add_columns(
                "Name",
                "Model",
                "Serial",
                "Ambient",
                "Raw Thermistor",
                "PCB-A",
                "PCB-B",
                "WiFi SSID",
                "IP",
                "Signal",
            )
        ctrl_table.clear()
        for ctrl in snap.controllers:
            ctrl_table.add_row(
                ctrl.name or ctrl.id[:8],
                _sku_or_none(ctrl.model_sku) or "--",
                ctrl.serial_number or "--",
                _tc(ctrl.calibrated_ambient_c, use_f),
                _tc(ctrl.raw_thermistor_c, use_f),
                _tc(ctrl.pcb_temperature_a_c, use_f),
                _tc(ctrl.pcb_temperature_b_c, use_f),
                ctrl.wifi_ssid or "--",
                ctrl.wifi_ip or "--",
                f"{ctrl.wifi_signal_dbm} dBm" if ctrl.wifi_signal_dbm else "--",
            )

        # Remote sensors table
        sensor_table: DataTable = self.query_one("#sys-sensors", DataTable)
        if not sensor_table.columns:
            sensor_table.add_columns(
                "Sensor",
                "Room",
                "Mode",
                "Temp",
                "Humidity",
                "Battery",
                "Signal",
            )
        sensor_table.clear()
        # Build IDU→room name map for display
        idu_to_room: dict[str, str] = {}
        for room in snap.rooms:
            for idu in snap.indoor_units:
                if idu.space_id == room.id:
                    idu_to_room[idu.id] = room.name or room.id[:8]
        for rs in sorted(
            snap.remote_sensors,
            key=lambda r: idu_to_room.get(r.indoor_unit_id, ""),
        ):
            mode_str = "EN" if rs.control_mode == RemoteSensorControlMode.ENABLED else "DIS"
            mode_style = "green" if rs.control_mode == RemoteSensorControlMode.ENABLED else "dim"
            sensor_table.add_row(
                rs.mac or rs.id[:8],
                idu_to_room.get(rs.indoor_unit_id, rs.indoor_unit_id[:8]),
                Text(mode_str, style=mode_style),
                _tc(rs.ambient_temperature_c, use_f),
                f"{rs.humidity_percent:.0f}%" if rs.humidity_percent else "--",
                f"{rs.battery_level_percent:.0f}%" if rs.battery_level_percent else "--",
                f"{rs.signal_level_dbm} dBm" if rs.signal_level_dbm else "--",
            )
        for crs in snap.controller_remote_sensors:
            ctrl = next((c for c in snap.controllers if c.id == crs.controller_id), None)
            label = (
                f"Dial {ctrl.serial_number or ctrl.name or crs.controller_id[:8]}"
                if ctrl
                else crs.id[:8]
            )
            room = next(
                (c.space_id for c in snap.controllers if c.id == crs.controller_id),
                None,
            )
            room_name = (
                next(
                    (s.name for s in snap.rooms if s.id == room),
                    room[:8] if room else "--",
                )
                if room
                else "--"
            )
            mode_str = "EN" if crs.control_mode == RemoteSensorControlMode.ENABLED else "DIS"
            mode_style = "green" if crs.control_mode == RemoteSensorControlMode.ENABLED else "dim"
            sensor_table.add_row(
                label,
                room_name,
                Text(mode_str, style=mode_style),
                _tc(crs.ambient_temperature_c, use_f),
                f"{crs.humidity_percent:.0f}%" if crs.humidity_percent else "--",
                f"{crs.battery_level_percent:.0f}%" if crs.battery_level_percent else "--",
                f"{crs.signal_level_dbm} dBm" if crs.signal_level_dbm else "--",
            )

        # Firmware / software update table
        fw_table: DataTable = self.query_one("#sys-firmware", DataTable)
        if not fw_table.columns:
            fw_table.add_columns(
                "Device",
                "Type",
                "Current Version",
                "Target Version",
                "Progress",
                "State",
            )
        fw_table.clear()
        sui_by_id = {s.id: s for s in snap.software_update_infos}

        def _fw_row(device_name: str, sw_id: str | None, fw_id: str | None) -> None:
            for label, uid in [("SW", sw_id), ("FW", fw_id)]:
                if not uid:
                    continue
                sui = sui_by_id.get(uid)
                if not sui:
                    continue
                ver = sui.current_version or "--"
                target = sui.target_version or "--"
                prog = (
                    f"{sui.current_progress:.0f}/{sui.total_progress:.0f}"
                    if sui.total_progress
                    else "--"
                )
                state = str(sui.state) if sui.state else "--"
                fw_table.add_row(device_name, label, ver, target, prog, state)

        for idu in snap.indoor_units:
            room = next((s.name for s in snap.rooms if s.id == idu.space_id), idu.id[:8])
            _fw_row(f"IDU {room}", None, idu.firmware_update_info_id)
        for odu in snap.outdoor_units:
            model = _sku_or_none(odu.model_sku)
            _fw_row(
                f"ODU {model or odu.serial_number or odu.id[:8]}",
                None,
                odu.firmware_update_info_id,
            )
        for ctrl in snap.controllers:
            model = _sku_or_none(ctrl.model_sku)
            _fw_row(
                f"Dial {model or ctrl.serial_number or ctrl.name or ctrl.id[:8]}",
                ctrl.software_update_info_id,
                ctrl.firmware_update_info_id,
            )
        for qsm in snap.quilt_smart_modules:
            _fw_row(
                f"QSM {qsm.id[:8]}",
                qsm.software_update_info_id,
                qsm.firmware_update_info_id,
            )

    def action_back(self) -> None:
        self.app.pop_screen()

    def update_odu(self, odu: OutdoorUnit) -> None:
        """Called by QuiltApp stream dispatcher when an ODU update arrives."""
        self._populate()

    def update_remote_sensor(self, rs: RemoteSensor) -> None:
        """Called by QuiltApp stream dispatcher on RemoteSensor updates."""
        self._populate()

    def action_toggle_units(self) -> None:
        self.use_f = not self.use_f
        self._populate()
        self.app._persist()

    def action_toggle_schedule(self) -> None:
        loc = self._snapshot.primary_location
        if loc is None:
            self.notify("No location found", severity="error")
            return
        self._do_toggle_schedule(not loc.schedule_paused)

    @work
    async def _do_toggle_schedule(self, paused: bool) -> None:
        try:
            await self._client.set_schedule_execution(paused)
            loc = self._snapshot.primary_location
            if loc:
                from dataclasses import replace

                patched = replace(loc, schedule_paused=paused)
                self._snapshot.locations[0] = patched
            self._populate()
            self.notify("Schedules " + ("paused" if paused else "resumed"), timeout=2)
        except Exception as exc:
            self.notify(f"Error: {exc}", severity="error")


# ──────────────────────────────────────────────────────────────────
# QuiltApp
# ──────────────────────────────────────────────────────────────────


class QuiltApp(App[None]):
    """Quilt HVAC TUI application."""

    CSS = _APP_CSS
    TITLE = "Quilt HVAC"
    BINDINGS: ClassVar = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("d", "toggle_dark", "Dark/Light", priority=True),
    ]

    def __init__(self, email: str, home: str | None = None) -> None:
        super().__init__()
        self._email = email
        self._home = home
        self._client = QuiltClient(email, home=home, snapshot_ttl_s=30, token_store=_token_store)
        self._stream = None
        self._snapshot = None
        self._settings = _settings_store.load()
        # Apply persisted dark/light before first render
        if self._settings.dark is not None:
            self.theme = "textual-dark" if self._settings.dark else "textual-light"

    @property
    def _is_dark(self) -> bool:
        return self.theme != "textual-light"

    def _persist(self) -> None:
        """Save current toggleable settings to disk."""
        screen = self.screen
        use_f = getattr(screen, "use_f", self._settings.use_fahrenheit)
        self._settings = _settings_store.update(use_fahrenheit=use_f, dark=self._is_dark)

    def action_toggle_dark(self) -> None:
        self.theme = "textual-light" if self._is_dark else "textual-dark"
        self._persist()

    def on_mount(self) -> None:
        self._loading_screen = LoadingScreen()
        self.push_screen(self._loading_screen)
        self._boot()

    @work
    async def _boot(self) -> None:
        """Log in, fetch snapshot, and replace LoadingScreen."""
        loading = self._loading_screen

        # _boot is an async @work — it runs on the main event loop, so UI
        # methods can be called directly (no call_from_thread needed).
        def _set_status(msg: str) -> None:
            if isinstance(loading, LoadingScreen):
                loading.set_status(msg)

        try:
            _set_status("Authenticating…")
            await self._client.login()
            _set_status("Loading system snapshot…")
            snap = await self._client.get_snapshot()
            self._snapshot = snap

            # Auto-save home name to settings so future runs don't need --home
            if self._client.system_name and not self._settings.home:
                self._settings = _settings_store.update(home=self._client.system_name)

            # Set app title to the home name once resolved
            if self._client.system_name:
                self.title = self._client.system_name

            dashboard = DashboardScreen(snap, self._client)
            await self.switch_screen(dashboard)

            # Restore persisted use_fahrenheit
            # (dark mode already applied in __init__)
            if self._settings.use_fahrenheit:
                dashboard.use_f = True

            # Start the shared stream
            self._start_stream(snap)

        except Exception as exc:
            self.notify(f"Boot failed: {exc}", severity="error")

    @work(exclusive=True)
    async def _start_stream(self, snap: SystemSnapshot) -> None:
        """Open shared NotifierStream, dispatch events to the active screen."""
        stream = self._client.stream(snap.stream_topics())

        # Stream callbacks are invoked from within async code on the same event
        # loop — call UI dispatch methods directly (no call_from_thread).
        stream.on_space_update(self._dispatch_space)
        stream.on_indoor_unit_update(self._dispatch_idu)
        stream.on_outdoor_unit_update(self._dispatch_odu)
        stream.on_controller_update(self._dispatch_ctrl)
        stream.on_qsm_update(self._dispatch_qsm)
        stream.on_remote_sensor_update(self._dispatch_remote_sensor)

        with contextlib.suppress(Exception):
            await stream.run_forever()

    def _dispatch_space(self, space: Space) -> None:
        if self._snapshot:
            space = self._snapshot.apply_space(space)
        screen = self.screen
        if isinstance(screen, DashboardScreen) or (
            isinstance(screen, RoomScreen) and screen._space.id == space.id
        ):
            screen.update_space(space)

    def _dispatch_idu(self, idu: IndoorUnit) -> None:
        if self._snapshot:
            idu = self._snapshot.apply_indoor_unit(idu)
        screen = self.screen
        if isinstance(screen, RoomScreen) and screen._idu and screen._idu.id == idu.id:
            screen.update_idu(idu)
        elif isinstance(screen, DashboardScreen):
            space = (
                next(
                    (s for s in self._snapshot.rooms if s.id == idu.space_id),
                    None,
                )
                if self._snapshot
                else None
            )
            if space:
                item = screen._items.get(space.id)
                if item:
                    item.update_space(space, idu, screen.use_f)
                    item.refresh()

    def _dispatch_odu(self, odu: OutdoorUnit) -> None:
        if self._snapshot:
            odu = self._snapshot.apply_outdoor_unit(odu)
        screen = self.screen
        if isinstance(screen, (DashboardScreen, SystemScreen)) or (
            isinstance(screen, RoomScreen) and screen._odu and screen._odu.id == odu.id
        ):
            screen.update_odu(odu)

    def _dispatch_ctrl(self, ctrl: Controller) -> None:
        if self._snapshot:
            ctrl = self._snapshot.apply_controller(ctrl)
        screen = self.screen
        if (
            isinstance(screen, RoomScreen)
            and screen._controller
            and screen._controller.id == ctrl.id
        ):
            screen.update_ctrl(ctrl)

    def _dispatch_qsm(self, qsm: QuiltSmartModule) -> None:
        if self._snapshot:
            qsm = self._snapshot.apply_qsm(qsm)
        screen = self.screen
        if isinstance(screen, RoomScreen) and screen._qsm and screen._qsm.id == qsm.id:
            screen.update_qsm(qsm)

    def _dispatch_remote_sensor(self, rs: RemoteSensor) -> None:
        if self._snapshot:
            rs = self._snapshot.apply_remote_sensor(rs)
        screen = self.screen
        if isinstance(screen, SystemScreen):
            screen.update_remote_sensor(rs)

    async def on_unmount(self) -> None:
        await self._client.close()
