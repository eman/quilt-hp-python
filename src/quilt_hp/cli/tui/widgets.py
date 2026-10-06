"""Reusable widgets."""

from __future__ import annotations

import logging

from rich.text import Text
from textual.widgets import (
    Static,
)

logger = logging.getLogger(__name__)


class _KVStatic(Static):
    """A key: value line as Rich markup."""

    def set_kv(self, key: str, value: str, val_style: str = "") -> None:
        if val_style:
            val = Text(value, style=val_style)
        else:
            val = Text.from_markup(value)
        self.update(Text.assemble(Text(f"{key:<22}", style="dim"), val))
