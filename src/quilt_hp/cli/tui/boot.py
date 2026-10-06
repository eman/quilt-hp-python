"""Startup screens: loading, boot error and OTP prompt."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from textual import on
from textual.containers import (
    Container,
    Vertical,
)
from textual.css.query import NoMatches
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Input,
    Label,
    LoadingIndicator,
)

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


class LoadingScreen(Screen[None]):
    """Spinner shown while logging in and fetching the initial snapshot."""

    def compose(self) -> ComposeResult:
        with Container(id="loading-container"):
            yield LoadingIndicator()
            yield Label("Connecting to Quilt Cloud…", id="loading-label")

    def set_status(self, msg: str) -> None:
        with contextlib.suppress(NoMatches):
            self.query_one("#loading-label", Label).update(msg)


class BootErrorScreen(Screen[None]):
    """Shown when startup fails — no perpetual spinner."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__()
        self._message = message
        self._hint = hint or "Check your connection and try again."

    def compose(self) -> ComposeResult:
        with Container(id="boot-error-container"):
            yield Label("✗ Failed to start", id="boot-error-title")
            yield Label(self._message, id="boot-error-message")
            yield Label(f"{self._hint}\nPress q to quit.", id="boot-error-hint")


class OtpScreen(ModalScreen[str]):
    """Modal prompting for the one-time passcode emailed during login."""

    def __init__(self, email: str) -> None:
        super().__init__()
        self._email = email

    def compose(self) -> ComposeResult:
        with Vertical(id="otp-dialog"):
            yield Label(
                f"✉ A one-time code was sent to {self._email}.\nEnter it below:",
                id="otp-label",
            )
            yield Input(placeholder="123456", id="otp-input")

    def on_mount(self) -> None:
        self.query_one("#otp-input", Input).focus()

    @on(Input.Submitted, "#otp-input")
    def _submit(self, event: Input.Submitted) -> None:
        code = event.value.strip()
        if code:
            self.dismiss(code)
