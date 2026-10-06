"""Small modal dialogs."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult


class ConfirmScreen(ModalScreen[bool]):
    """Ask a yes/no question; dismisses with True only when the action is confirmed."""

    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen > Vertical {
        width: 60; height: auto; padding: 1 2;
        border: round $warning; background: $surface;
    }
    ConfirmScreen #confirm-detail { color: $text-muted; margin-top: 1; }
    ConfirmScreen Horizontal { height: auto; margin-top: 1; align-horizontal: right; }
    ConfirmScreen Button { margin-left: 2; }
    """
    BINDINGS: ClassVar = [
        Binding("escape,n", "cancel", "Cancel"),
        Binding("y", "confirm", "Confirm"),
    ]

    def __init__(self, question: str, detail: str, confirm_label: str) -> None:
        super().__init__()
        self._question = question
        self._detail = detail
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self._question, id="confirm-question")
            yield Static(self._detail, id="confirm-detail")
            with Horizontal():
                yield Button("Cancel", id="confirm-cancel")
                yield Button(self._confirm_label, id="confirm-ok", variant="warning")

    def on_mount(self) -> None:
        self.query_one("#confirm-cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-ok")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)
