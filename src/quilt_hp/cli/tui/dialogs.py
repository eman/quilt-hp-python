"""Small modal dialogs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

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


class ValueDialog(ModalScreen[float | None]):
    """Ask for one number; dismisses with the value, or None when cancelled."""

    DEFAULT_CSS = """
    ValueDialog { align: center middle; }
    ValueDialog > Vertical {
        width: 50; height: auto; padding: 1 2;
        border: round $primary; background: $surface;
    }
    ValueDialog Input { margin-top: 1; }
    ValueDialog #value-error { color: $error; height: auto; }
    ValueDialog #value-hint { color: $text-muted; }
    """
    BINDINGS: ClassVar = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, current: float, low: float, high: float, unit: str) -> None:
        super().__init__()
        self._title = title
        self._current = current
        self._low = low
        self._high = high
        self._unit = unit

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self._title)
            yield Input(value=f"{self._current:.1f}", id="value-input")
            yield Static(
                f"{self._low:.0f}–{self._high:.0f} {self._unit} · enter to set, esc to cancel",
                id="value-hint",
            )
            yield Static("", id="value-error")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        try:
            value = float(event.value.strip().replace(",", "."))
        except ValueError:
            self.query_one("#value-error", Static).update("Enter a number.")
            return
        if not self._low <= value <= self._high:
            self.query_one("#value-error", Static).update(
                f"Enter a value from {self._low:.0f} to {self._high:.0f} {self._unit}."
            )
            return
        self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class TextDialog(ModalScreen[str | None]):
    """Ask for one line of text; dismisses with it (trimmed), or None when cancelled."""

    DEFAULT_CSS = """
    TextDialog { align: center middle; }
    TextDialog > Vertical {
        width: 50; height: auto; padding: 1 2;
        border: round $primary; background: $surface;
    }
    TextDialog Input { margin-top: 1; }
    TextDialog #text-error { color: $error; height: auto; }
    TextDialog #text-hint { color: $text-muted; }
    """
    BINDINGS: ClassVar = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, current: str) -> None:
        super().__init__()
        self._title = title
        self._current = current

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self._title)
            yield Input(value=self._current, id="text-input")
            yield Static("enter to save, esc to cancel", id="text-hint")
            yield Static("", id="text-error")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if not value:
            self.query_one("#text-error", Static).update("Enter a name.")
            return
        self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)


@dataclass(frozen=True, slots=True)
class SettingField:
    """One editable number in the Room settings dialog."""

    key: str
    label: str
    value: float | None  # None: not available for this room (field is hidden)
    low: float
    high: float
    unit: str
    decimals: int = 1


class RoomSettingsScreen(ModalScreen[dict[str, float] | None]):
    """Edit a room's less frequent settings; dismisses with only the fields that changed."""

    DEFAULT_CSS = """
    RoomSettingsScreen { align: center middle; }
    RoomSettingsScreen > Vertical {
        width: 64; height: auto; max-height: 100%; padding: 0 2;
        border: round $primary; background: $surface;
    }
    RoomSettingsScreen VerticalScroll { height: auto; max-height: 1fr; }
    RoomSettingsScreen .setting-row { height: 1; }
    RoomSettingsScreen .setting-label { width: 32; }
    RoomSettingsScreen .setting-unit { width: 6; padding-left: 1; color: $text-muted; }
    RoomSettingsScreen Input { width: 12; }
    RoomSettingsScreen .setting-section { margin-top: 1; text-style: bold; }
    RoomSettingsScreen #settings-error { color: $error; height: auto; margin-top: 1; }
    RoomSettingsScreen #settings-buttons { height: auto; align-horizontal: right; }
    RoomSettingsScreen Button { margin-left: 2; }
    """
    BINDINGS: ClassVar = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, room: str, sections: list[tuple[str, list[SettingField]]]) -> None:
        super().__init__()
        self._room = room
        self._sections = [
            (title, [f for f in fields if f.value is not None]) for title, fields in sections
        ]
        self._fields = {f.key: f for _, fields in self._sections for f in fields}

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"{self._room} settings  [dim](enter or Save applies, esc cancels)[/dim]")
            with VerticalScroll():
                for title, fields in self._sections:
                    if not fields:
                        continue
                    yield Static(title, classes="setting-section")
                    for f in fields:
                        with Horizontal(classes="setting-row"):
                            yield Static(f.label, classes="setting-label")
                            yield Input(
                                value=f"{f.value:.{f.decimals}f}", id=f"set-{f.key}", compact=True
                            )
                            yield Static(f.unit, classes="setting-unit")
            yield Static("", id="settings-error")
            with Horizontal(id="settings-buttons"):
                yield Button("Cancel", id="settings-cancel")
                yield Button("Save", id="settings-save", variant="primary")

    def on_mount(self) -> None:
        inputs = self.query(Input)
        if inputs:
            inputs.first().focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "settings-cancel":
            self.dismiss(None)
        else:
            self._save()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self._save()

    def _save(self) -> None:
        changed: dict[str, float] = {}
        for key, f in self._fields.items():
            text = self.query_one(f"#set-{key}", Input).value.strip().replace(",", ".")
            try:
                value = float(text)
            except ValueError:
                self._error(f"{f.label}: enter a number.")
                return
            if not f.low <= value <= f.high:
                self._error(f"{f.label}: enter a value from {f.low:g} to {f.high:g} {f.unit}.")
                return
            assert f.value is not None
            if round(value, f.decimals) != round(f.value, f.decimals):
                changed[key] = value
        self.dismiss(changed)

    def _error(self, message: str) -> None:
        self.query_one("#settings-error", Static).update(message)

    def action_cancel(self) -> None:
        self.dismiss(None)
