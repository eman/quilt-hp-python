"""Reusable widgets."""

from __future__ import annotations

import logging

from rich.text import Text
from textual.widgets import (
    Static,
)

logger = logging.getLogger(__name__)


class _KVStatic(Static):
    """A key: value line. The value is plain text: device and room names are never parsed as markup."""

    DEFAULT_CSS = """
    _KVStatic {
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    """

    def set_kv(self, key: str, value: str, val_style: str = "") -> None:
        val = Text(value, style=val_style)
        self.update(Text.assemble(Text(f"{key:<22}", style="dim"), val))
