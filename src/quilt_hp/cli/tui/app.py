"""QuiltApp: boot flow, shared snapshot and live-update dispatch."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, ClassVar

from textual import work
from textual.app import App
from textual.binding import Binding
from textual.reactive import reactive

from quilt_hp.cli.settings import SettingsStore
from quilt_hp.cli.store import FileStore
from quilt_hp.cli.tui.boot import BootErrorScreen, LoadingScreen, OtpScreen
from quilt_hp.cli.tui.home import HomeScreen
from quilt_hp.cli.tui.styles import _APP_CSS
from quilt_hp.client import QuiltClient
from quilt_hp.exceptions import QuiltAuthError
from quilt_hp.models.controller import Controller
from quilt_hp.models.indoor_unit import IndoorUnit
from quilt_hp.models.outdoor_unit import OutdoorUnit
from quilt_hp.models.qsm import QuiltSmartModule
from quilt_hp.models.sensor import RemoteSensor

if TYPE_CHECKING:
    from quilt_hp.models.space import Space
    from quilt_hp.models.system import SystemSnapshot
    from quilt_hp.services.streaming import NotifierStream


logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# Persistent settings (delegates to quilt_hp.cli.settings)
# ──────────────────────────────────────────────────────────────────

# Persistent stores (tokens separate from non-secret settings)
_token_store = FileStore()
_settings_store = SettingsStore()

# ──────────────────────────────────────────────────────────────────
# QuiltApp
# ──────────────────────────────────────────────────────────────────


class QuiltApp(App[None]):
    """Quilt HVAC TUI application."""

    CSS = _APP_CSS
    TITLE = "Quilt HVAC"
    BINDINGS: ClassVar = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("question_mark", "help", "Help", key_display="?"),
    ]

    _STREAM_RECOVERY_DELAYS_S: ClassVar = (5.0, 15.0, 30.0)

    use_f: reactive[bool] = reactive(False)

    def __init__(
        self,
        email: str,
        home: str | None = None,
        *,
        client: QuiltClient | None = None,
        settings_store: SettingsStore | None = None,
    ) -> None:
        """Create the app. ``client`` and ``settings_store`` are for tests and embedding."""
        super().__init__()
        self._email = email
        self._home = home
        self._client = client or QuiltClient(
            email, home=home, snapshot_ttl_s=30, token_store=_token_store
        )
        self._stream: NotifierStream | None = None
        self._snapshot: SystemSnapshot | None = None
        self.control_locks: dict[str, asyncio.Lock] = {}  # see controls.room_lock
        self._settings_store = settings_store or _settings_store
        self._settings = self._settings_store.load()
        # Apply persisted preferences before first render; set_reactive avoids
        # triggering watch_use_f before the app is running.
        self.set_reactive(QuiltApp.use_f, self._settings.use_fahrenheit)
        if self._settings.theme and self._settings.theme in self.available_themes:
            self.theme = self._settings.theme
        elif self._settings.dark is not None:  # settings saved before themes were remembered
            self.theme = "textual-dark" if self._settings.dark else "textual-light"

    # ── Shared state (single source of truth for all screens) ────

    @property
    def snapshot(self) -> SystemSnapshot | None:
        """The current system snapshot shared by all screens."""
        return self._snapshot

    def update_snapshot(self, snap: SystemSnapshot) -> None:
        """Adopt a freshly fetched snapshot as the shared source of truth."""
        self._snapshot = snap

    def watch_use_f(self, use_f: bool) -> None:
        """Persist the °C/°F preference and re-render every stacked screen."""
        self._persist()
        for screen in self.screen_stack:
            refresh = getattr(screen, "refresh_units", None)
            if callable(refresh):
                refresh()

    def _persist(self) -> None:
        """Save current toggleable settings to disk."""
        self._settings = self._settings_store.update(
            use_fahrenheit=self.use_f, theme=self.theme, dark=self.current_theme.dark
        )

    def action_help(self) -> None:
        from quilt_hp.cli.tui.devices import DevicesScreen
        from quilt_hp.cli.tui.energy import EnergyScreen
        from quilt_hp.cli.tui.help import HelpScreen
        from quilt_hp.cli.tui.room import RoomScreen

        if isinstance(self.screen, HelpScreen):
            return
        self.push_screen(
            HelpScreen(
                [
                    ("Home", HomeScreen),
                    ("Room", RoomScreen),
                    ("Devices", DevicesScreen),
                    ("Energy", EnergyScreen),
                ]
            )
        )

    def _on_theme_changed(self, _theme: object) -> None:
        """Persist a theme chosen from the command palette (ctrl+p → Change theme)."""
        self._persist()

    def on_mount(self) -> None:
        self.theme_changed_signal.subscribe(self, self._on_theme_changed)
        self._loading_screen = LoadingScreen()
        self.push_screen(self._loading_screen)
        self._boot()

    async def _prompt_otp(self, email: str) -> str:
        """OTP callback for first-time logins — modal input in the TUI."""
        return await self.push_screen_wait(OtpScreen(email))

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
            await self._client.login(otp_callback=self._prompt_otp)
            _set_status("Loading system snapshot…")
            snap = await self._client.get_snapshot()
            self._snapshot = snap

            # Auto-save home name to settings so future runs don't need --home
            if self._client.system_name and not self._settings.home:
                self._settings = self._settings_store.update(home=self._client.system_name)

            # Set app title to the home name once resolved
            if self._client.system_name:
                self.title = self._client.system_name

            await self.switch_screen(HomeScreen(snap, self._client))

            # Start the shared stream
            self._start_stream(snap)

        except QuiltAuthError as exc:
            self._show_boot_error(
                str(exc),
                "Authentication failed. Run `quilt login` in a terminal and retry.",
            )
        except Exception as exc:
            logger.exception("TUI boot failed")
            self._show_boot_error(str(exc))

    def _show_boot_error(self, message: str, hint: str | None = None) -> None:
        """Replace the loading spinner with an actionable error screen."""
        self.notify(f"Boot failed: {message}", severity="error")
        self.switch_screen(BootErrorScreen(message, hint))

    # ── Stream lifecycle ─────────────────────────────────────────

    @work(exclusive=True, group="stream")
    async def _start_stream(self, snap: SystemSnapshot) -> None:
        """Open shared NotifierStream, dispatch events to the active screen."""
        stream = self._client.stream(snap.stream_topics())
        self._stream = stream

        # Stream callbacks are invoked from within async code on the same event
        # loop — call UI dispatch methods directly (no call_from_thread).
        stream.on_space_update(self._dispatch_space)
        stream.on_indoor_unit_update(self._dispatch_idu)
        stream.on_outdoor_unit_update(self._dispatch_odu)
        stream.on_controller_update(self._dispatch_ctrl)
        stream.on_qsm_update(self._dispatch_qsm)
        stream.on_remote_sensor_update(self._dispatch_remote_sensor)
        stream.on_delete(self._dispatch_delete)
        stream.on_error(self._on_stream_error)

        try:
            await stream.run_forever()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Fatal errors are normally reported via on_error; anything that
            # still escapes run_forever is unexpected — surface it too.
            logger.exception("NotifierStream terminated unexpectedly")
            self._on_stream_error(exc)

    def _on_stream_error(self, exc: Exception) -> None:
        """Fatal stream error — tell the user and try to recover."""
        logger.error("Notifier stream failed: %s", exc)
        self._set_stream_disconnected(True)
        self.notify(
            f"Live updates disconnected: {exc}. Attempting to reconnect…",
            severity="error",
            timeout=8,
        )
        self._recover_stream()

    def _set_stream_disconnected(self, disconnected: bool) -> None:
        """Show/clear a visible 'stream disconnected' indicator."""
        self.sub_title = "⚠ live updates disconnected" if disconnected else ""

    @work(exclusive=True, group="stream-recovery")
    async def _recover_stream(self) -> None:
        """Re-fetch a snapshot and restart the stream, with backoff."""
        for delay in self._STREAM_RECOVERY_DELAYS_S:
            await asyncio.sleep(delay)
            try:
                snap = await self._client.get_snapshot()
            except Exception as exc:
                logger.warning("Stream recovery snapshot fetch failed: %s", exc)
                continue
            self.update_snapshot(snap)
            for screen in self.screen_stack:
                refresh = getattr(screen, "refresh_units", None)
                if callable(refresh):
                    refresh()
            self._set_stream_disconnected(False)
            self.notify("Live updates restored", timeout=3)
            self._start_stream(snap)
            return
        self.notify(
            "Could not restore live updates. Data may be stale — press r to refresh, "
            "or restart the app.",
            severity="error",
            timeout=10,
        )

    # ── Stream event dispatchers ─────────────────────────────────

    def _dispatch_delete(self, kind: str, entity_id: str) -> None:
        if self._snapshot and self._snapshot.remove(kind, entity_id):
            self._notify_screen(kind, None)
            self.notify(
                f"A {kind.replace('_', ' ')} was removed from this system; press r to refresh."
            )

    def _notify_screen(self, kind: str, entity: object) -> None:
        """Tell the active screen about an update already merged into the snapshot."""
        hook = getattr(self.screen, "snapshot_changed", None)
        if callable(hook):
            hook(kind, entity)

    def _dispatch_space(self, space: Space) -> None:
        if self._snapshot:
            space = self._snapshot.apply_space(space)
        self._notify_screen("space", space)

    def _dispatch_idu(self, idu: IndoorUnit) -> None:
        if self._snapshot:
            idu = self._snapshot.apply_indoor_unit(idu)
        self._notify_screen("indoor_unit", idu)

    def _dispatch_odu(self, odu: OutdoorUnit) -> None:
        if self._snapshot:
            odu = self._snapshot.apply_outdoor_unit(odu)
        self._notify_screen("outdoor_unit", odu)

    def _dispatch_ctrl(self, ctrl: Controller) -> None:
        if self._snapshot:
            ctrl = self._snapshot.apply_controller(ctrl)
        self._notify_screen("controller", ctrl)

    def _dispatch_qsm(self, qsm: QuiltSmartModule) -> None:
        if self._snapshot:
            qsm = self._snapshot.apply_qsm(qsm)
        self._notify_screen("qsm", qsm)

    def _dispatch_remote_sensor(self, rs: RemoteSensor) -> None:
        if self._snapshot:
            rs = self._snapshot.apply_remote_sensor(rs)
        self._notify_screen("remote_sensor", rs)

    async def on_unmount(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None:
            with contextlib.suppress(Exception):
                await stream.stop()
        await self._client.close()
