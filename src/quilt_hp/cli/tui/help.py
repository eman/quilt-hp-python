"""Help screen: every key, generated from each screen's bindings so it can't drift."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.screen import Screen

_KEY_NAMES = {
    "escape": "esc",
    "left_square_bracket": "[",
    "right_square_bracket": "]",
    "plus": "+",
    "minus": "−",
    "equals_sign": "=",
    "question_mark": "?",
    "left": "←",
    "right": "→",
    "enter": "enter",
}
_NOTES = {
    "Home": "↑ ↓ choose a room. The summary and Needs attention panels follow the selection.",
    "Room": (
        "On Overview, ↑ ↓ choose a control, ← → change it, enter types a setpoint.\n"
        "+ / − change the setpoint the mode uses; in Auto, the one nearer the room temperature."
    ),
    "Devices": "↑ ↓ choose a device; its details are shown below.",
}


# Actions shown together on one row: (action prefix, row label).
_GROUPS = (
    ("setpoint(", "Raise / lower the setpoint the mode uses"),
    ("switch_room(", "Previous / next room"),
    ("adjust(", "Change the selected control"),
    ("tab(", "Tabs: Overview, Climate, Schedule, Energy, Devices"),
)


def binding_rows(screen: type[Screen[None]]) -> list[tuple[str, str]]:
    """(keys, description) for a screen's bindings; related actions share a row."""
    rows: dict[str, list[str]] = {}
    labels: dict[str, str] = {}
    for binding in screen.BINDINGS:
        if not isinstance(binding, Binding):
            continue
        keys = [_KEY_NAMES.get(k, k) for k in binding.key.split(",")]
        if "=" in keys and "+" in keys:
            keys.remove("=")
        group = next(((p, label) for p, label in _GROUPS if binding.action.startswith(p)), None)
        action, label = group if group else (binding.action, binding.description)
        rows.setdefault(action, []).extend(keys)
        labels.setdefault(action, label)
    out = []
    for action, keys in rows.items():
        unique = list(dict.fromkeys(keys))
        text = f"{unique[0]}–{unique[-1]}" if action == "tab(" else " ".join(unique)
        out.append((text, labels[action]))
    return out


class HelpScreen(ModalScreen[None]):
    """All keys, by screen."""

    DEFAULT_CSS = """
    HelpScreen { align: center middle; }
    HelpScreen > VerticalScroll {
        width: 76; height: auto; max-height: 100%; padding: 0 2;
        border: round $primary; background: $surface;
    }
    """
    BINDINGS: ClassVar = [Binding("escape,question_mark,q", "dismiss", "Close")]

    def __init__(self, screens: list[tuple[str, type[Screen[None]]]]) -> None:
        super().__init__()
        self._screens = screens

    def compose(self) -> ComposeResult:
        lines: list[Text] = [Text("Keys  (esc closes)", style="bold")]
        for name, screen in self._screens:
            lines.append(Text(""))
            lines.append(Text(name, style="bold underline"))
            for keys, label in binding_rows(screen):
                lines.append(Text.assemble((f"  {keys:<14}", "bold yellow"), label))
            if name in _NOTES:
                lines.append(Text(_NOTES[name], style="dim"))
        lines.append(Text(""))
        lines.append(Text("Everywhere", style="bold underline"))
        for keys, label in (
            ("?", "This help"),
            ("u", "°C / °F"),
            ("ctrl+p", "Command palette (theme, quit)"),
            ("q", "Quit"),
        ):
            lines.append(Text.assemble((f"  {keys:<14}", "bold yellow"), label))
        with VerticalScroll():
            yield Static(Text("\n").join(lines))

    async def action_dismiss(self, result: None = None) -> None:
        self.dismiss(result)
