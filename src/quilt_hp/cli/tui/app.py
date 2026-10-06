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
from quilt_hp.cli.tui.dashboard import DashboardScreen
from quilt_hp.cli.tui.room import RoomScreen
from quilt_hp.cli.tui.styles import _APP_CSS
from quilt_hp.cli.tui.system import SystemScreen
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
        Binding("d", "toggle_dark", "Dark/Light", priority=True),
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
        self._settings_store = settings_store or _settings_store
        self._settings = self._settings_store.load()
        # Apply persisted preferences before first render; set_reactive avoids
        # triggering watch_use_f before the app is running.
        self.set_reactive(QuiltApp.use_f, self._settings.use_fahrenheit)
        if self._settings.dark is not None:
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

    @property
    def _is_dark(self) -> bool:
        return self.theme != "textual-light"

    def _persist(self) -> None:
        """Save current toggleable settings to disk."""
        self._settings = self._settings_store.update(use_fahrenheit=self.use_f, dark=self._is_dark)

    def action_toggle_dark(self) -> None:
        self.theme = "textual-light" if self._is_dark else "textual-dark"
        self._persist()

    def on_mount(self) -> None:
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

            dashboard = DashboardScreen(snap, self._client)
            await self.switch_screen(dashboard)

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
            self.notify(
                f"A {kind.replace('_', ' ')} was removed from this system; press r to refresh."
            )

    def _dispatch_space(self, space: Space) -> None:
        if self._snapshot:
            space = self._snapshot.apply_space(space)
        screen = self.screen
        if isinstance(screen, DashboardScreen) or (
            isinstance(screen, RoomScreen) and screen.space_id == space.id
        ):
            screen.update_space(space)

    def _dispatch_idu(self, idu: IndoorUnit) -> None:
        if self._snapshot:
            idu = self._snapshot.apply_indoor_unit(idu)
        screen = self.screen
        if (isinstance(screen, RoomScreen) and screen.idu_id == idu.id) or isinstance(
            screen, DashboardScreen
        ):
            screen.update_idu(idu)

    def _dispatch_odu(self, odu: OutdoorUnit) -> None:
        if self._snapshot:
            odu = self._snapshot.apply_outdoor_unit(odu)
        screen = self.screen
        if isinstance(screen, (DashboardScreen, SystemScreen)) or (
            isinstance(screen, RoomScreen) and screen.odu_id == odu.id
        ):
            screen.update_odu(odu)

    def _dispatch_ctrl(self, ctrl: Controller) -> None:
        if self._snapshot:
            ctrl = self._snapshot.apply_controller(ctrl)
        screen = self.screen
        if isinstance(screen, RoomScreen) and screen.controller_id == ctrl.id:
            screen.update_ctrl(ctrl)

    def _dispatch_qsm(self, qsm: QuiltSmartModule) -> None:
        if self._snapshot:
            qsm = self._snapshot.apply_qsm(qsm)
        screen = self.screen
        if isinstance(screen, RoomScreen) and screen.qsm_id == qsm.id:
            screen.update_qsm(qsm)

    def _dispatch_remote_sensor(self, rs: RemoteSensor) -> None:
        if self._snapshot:
            rs = self._snapshot.apply_remote_sensor(rs)
        screen = self.screen
        if isinstance(screen, SystemScreen):
            screen.update_remote_sensor(rs)

    async def on_unmount(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None:
            with contextlib.suppress(Exception):
                await stream.stop()
        await self._client.close()
