# Build a TUI app

[Textual](https://github.com/Textualize/textual) is an async Python TUI framework built on asyncio. Because `quilt-hp-python` is also async, both run in the same event loop. You can call `QuiltClient` from Textual event handlers or background workers without thread bridging.

---

## Architecture

A Quilt Textual integration uses three layers:

1. **`App.on_mount`**: Log in and fetch the initial snapshot.
2. **A `Worker`**: Runs the `NotifierStream` indefinitely; stream callbacks post `Message` objects to the Textual app.
3. **Reactive widgets**: Re-render when they receive Quilt messages.

```
Textual event loop
└── QuiltApp
    ├── on_mount → login → initial snapshot → render
    ├── Worker → NotifierStream (runs in same loop)
    │   └── on_space_update → app.post_message(SpaceUpdate(space))
    └── SpaceUpdateHandler → update reactive widget
```

---

## Full example

```python
#!/usr/bin/env python3
"""
quilt-tui — real-time HVAC dashboard using Textual.

Install: pip install quilt-hp textual
Run:     QUILT_EMAIL=you@example.com python quilt_tui.py
"""
from __future__ import annotations
import asyncio
import os
from dataclasses import dataclass

from textual.app import App, ComposeResult
from textual.message import Message
from textual.widgets import DataTable, Header, Footer, Label
from textual.reactive import reactive

from quilt_hp import QuiltClient
from quilt_hp.cli.store import FileStore
from quilt_hp.models.space import Space
from quilt_hp.models.indoor_unit import IndoorUnit
from quilt_hp.models.system import SystemSnapshot

EMAIL = os.environ["QUILT_EMAIL"]


class SpaceUpdate(Message):
    def __init__(self, space: Space) -> None:
        super().__init__()
        self.space = space


class IDUUpdate(Message):
    def __init__(self, idu: IndoorUnit) -> None:
        super().__init__()
        self.idu = idu


class StreamConnected(Message):
    pass


class StreamDisconnected(Message):
    pass


class QuiltApp(App):
    CSS = """
    DataTable { height: 1fr; }
    #status-bar { height: 1; background: $panel; }
    """

    BINDINGS = [("q", "quit", "Quit"), ("r", "refresh", "Refresh")]

    _snapshot: SystemSnapshot | None = None
    _client: QuiltClient | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield DataTable(id="spaces-table")
        yield Label("Connecting…", id="status-bar")
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#spaces-table", DataTable)
        table.add_columns("Room", "Mode", "Temp", "Setpoint (heat/cool)")

        self._client = QuiltClient(EMAIL, token_store=FileStore(), snapshot_ttl_s=300)
        await self._client.__aenter__()
        await self._client.login()

        self._snapshot = await self._client.get_snapshot()
        self._refresh_table()

        self.run_worker(self._run_stream(), exclusive=True)

    async def _run_stream(self) -> None:
        assert self._snapshot is not None
        assert self._client is not None

        topics = self._snapshot.stream_topics()
        stream = self._client.stream(topics, max_reconnects=-1)
        stream.on_space_update(self._on_space)
        stream.on_indoor_unit_update(self._on_idu)
        stream.on_connected(lambda: self.post_message(StreamConnected()))
        stream.on_disconnected(lambda: self.post_message(StreamDisconnected()))

        async with stream:
            await asyncio.Event().wait()

    def _on_space(self, space: Space) -> None:
        if self._snapshot is not None:
            self._snapshot.spaces[space.id] = space
        self.post_message(SpaceUpdate(space))

    def _on_idu(self, idu: IndoorUnit) -> None:
        if self._snapshot is not None:
            self._snapshot.indoor_units[idu.id] = idu
        self.post_message(IDUUpdate(idu))

    def on_space_update(self, msg: SpaceUpdate) -> None:
        self._update_row(msg.space)

    def on_stream_connected(self, msg: StreamConnected) -> None:
        self.query_one("#status-bar", Label).update("● Connected")

    def on_stream_disconnected(self, msg: StreamDisconnected) -> None:
        self.query_one("#status-bar", Label).update("○ Disconnected — reconnecting…")

    def _refresh_table(self) -> None:
        if self._snapshot is None:
            return
        for space in sorted(self._snapshot.rooms, key=lambda s: s.name):
            self._update_row(space)

    def _update_row(self, space: Space) -> None:
        table = self.query_one("#spaces-table", DataTable)
        temp = (
            f"{space.state.current_temp_c:.1f}°C"
            if space.state.current_temp_c is not None
            else "—"
        )
        setpoints = (
            f"{space.controls.heat_setpoint_c:.0f} / "
            f"{space.controls.cool_setpoint_c:.0f}°C"
        )
        row = (space.name, space.controls.mode.value, temp, setpoints)

        key = f"space-{space.id}"
        if key in table.rows:
            table.update_row(key, *row)
        else:
            table.add_row(*row, key=key)

    async def action_refresh(self) -> None:
        if self._client is not None:
            self._client.invalidate_snapshot()
            self._snapshot = await self._client.get_snapshot()
            self._refresh_table()

    async def on_unmount(self) -> None:
        if self._client is not None:
            await self._client.__aexit__(None, None, None)


if __name__ == "__main__":
    QuiltApp().run()
```

---

## Post messages from callbacks

Textual is not thread-safe, but `post_message()` is. Stream callbacks run in the same event loop as Textual, so calling `post_message()` directly from an `async def` callback is safe. If you use synchronous callbacks, use `self.call_from_thread()` instead.

---

## Manage worker lifecycle

`run_worker(exclusive=True)` makes sure only one stream worker runs at a time. If the user calls `action_refresh`, a new worker replaces the old one. The stream's `max_reconnects=-1` means the reconnect loop runs inside the worker, and the worker task exits only when the app shuts down.

The worker coroutine ends with `await asyncio.Event().wait()`, a never-resolved event that blocks indefinitely. When Textual cancels the worker on app shutdown, this is the task that gets cancelled, which causes the `async with stream:` block to call `stream.stop()`.

---

## Add space control

To let the user set the HVAC mode from the TUI:

```python
BINDINGS = [..., ("s", "set_mode", "Set mode")]

async def action_set_mode(self) -> None:
    table = self.query_one("#spaces-table", DataTable)
    row_key = table.cursor_row_key
    if row_key is None:
        return
    space_id = row_key.removeprefix("space-")
    space = self._snapshot.spaces.get(space_id)
    if space is None:
        return

    from textual.screen import Screen
    from textual.widgets import Select

    class ModeScreen(Screen):
        def compose(self) -> ComposeResult:
            from quilt_hp.models.enums import HVACMode
            yield Select([(m.value, m) for m in HVACMode], id="mode-select")

        def on_select_changed(self, event: Select.Changed) -> None:
            self.dismiss(event.value)

    mode = await self.push_screen_wait(ModeScreen())
    if mode is not None and self._client is not None:
        await self._client.set_space(space, mode=mode)
```
