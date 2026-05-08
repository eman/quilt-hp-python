# Integrations overview

`quilt-hp-python` is intentionally unopinionated about how you run it. The library is a pure async Python client — it has no built-in scheduler, no web framework, and no UI. It can be embedded in any async host that gives it an event loop.

This section provides concrete playbooks for the most common integration patterns.

---

## Choosing a pattern

| Pattern | Use when |
|---------|----------|
| [Home Assistant custom component](home-assistant-playbook.md) | You want HVAC control inside HA with automations, dashboards, and voice control |
| [Automation service](automation-service-playbook.md) | You need a standalone daemon with event-driven rules and external state |
| [CLI scripts](cli-automation-playbook.md) | You need quick read/write access from a shell, cron job, or CI pipeline |
| [Textual TUI](tui-event-driven-playbook.md) | You want an interactive terminal dashboard with real-time updates |

---

## Common threads across all integrations

### Token persistence

Every integration should supply a `token_store` so tokens survive restarts. The `FileStore` in `quilt_hp.cli.store` is appropriate for single-user CLI and daemon scenarios. For Home Assistant, implement a store backed by `hass.data` or the HA storage helper.

### Event-driven architecture

`NotifierStream` pushes sparse proto3 diffs through registered callbacks. The canonical integration pattern is:

1. Fetch a full `SystemSnapshot` on startup.
2. Start the stream with `snapshot.stream_topics()`.
3. Register callbacks to merge diffs into the snapshot (`snapshot.apply_space_update`, etc.).
4. Derive display state from the snapshot on each callback.

This means you never poll — the snapshot is always fresh as long as the stream is connected.

### Reconnection and resilience

The stream reconnects automatically with exponential back-off (1 s → 2 s → 4 s → … cap 60 s) after any disconnect. For daemons and integrations, set `max_reconnects=-1` (unlimited). Register `stream.on_connected` and `stream.on_disconnected` callbacks to update availability state in the host system.

### Graceful shutdown

Always `await stream.stop()` or use the stream as an async context manager before closing the gRPC channel. The gRPC channel is closed by `await client.__aexit__()` or implicitly by the `async with QuiltClient(...)` block. Skipping shutdown may log gRPC errors about unclosed channels.

---

## Capabilities matrix

| Capability | HA | Daemon | CLI | TUI |
|-----------|:--:|:------:|:---:|:---:|
| Read current state | ✓ | ✓ | ✓ | ✓ |
| Control spaces | ✓ | ✓ | ✓ | ✓ |
| Real-time streaming | ✓ | ✓ | — | ✓ |
| Token persistence | via HA storage | FileStore | FileStore | FileStore |
| Automation rules | via HA | custom | via shell | — |
| Multi-account | — | ✓ | ✓ | — |
