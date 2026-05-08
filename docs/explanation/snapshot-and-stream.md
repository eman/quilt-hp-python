# Snapshot and stream data model

`SystemSnapshot` and the `NotifierStream` together form the data model for a live Quilt integration. Understanding why both exist, and how they relate, is important for writing correct integrations.

---

## What `SystemSnapshot` is

`SystemSnapshot` is an in-memory model of a complete Quilt installation at a point in time. A single `GetHomeDatastoreSystem` RPC returns the entire state of one system: all spaces, indoor units, outdoor units, controllers, sensors, comfort settings, and schedules, in one flat response.

This is intentional. Quilt's cloud backend is designed to serve a full snapshot on demand. The alternative — separate RPCs for each entity type — would require a client to coordinate multiple concurrent requests and assemble a consistent view. A single snapshot RPC is simpler, faster, and gives clients a strongly consistent starting point.

`SystemSnapshot.from_proto()` does more than field-by-field translation. It cross-references comfort settings to resolve `active_comfort_setting_type` on spaces, and it resolves hardware lookup maps so outdoor units and controllers include hardware info (model SKU, serial number, firmware). This enrichment cannot be done from a sparse stream diff, which is one reason the snapshot is the authoritative starting point.

---

## The snapshot-and-stream pattern

The snapshot is a photograph; the stream is a change log. For a live integration, you take one photograph and then apply each change as it arrives:

```python
snapshot = await client.get_snapshot()   # full state at time T

def on_space_update(space: Space) -> None:
    updated = snapshot.apply_space(space)  # merge diff into snapshot
    # updated is now the current state of this room

stream = client.stream(snapshot.stream_topics())
stream.on_space_update(on_space_update)
await stream.run_forever()
```

This pattern is more efficient than polling for two reasons:

1. `get_snapshot()` is a heavyweight call — it transfers the entire system state. Polling it every few seconds would generate unnecessary traffic and adds latency.
2. Stream events arrive within milliseconds of a state change, while a poll would miss anything that happened between polls.

The snapshot is not just a performance optimisation; it is the source of truth for fields that are never sent in stream diffs. This is because…

---

## Why stream diffs are sparse

Stream events use proto3 and carry only the fields that changed. A space update triggered by a temperature sensor reading will carry a `state` sub-message with the new temperature, but the `controls` sub-message will be absent. In proto3, absent fields deserialise to their default values: empty string, `0`, `false`, or `None` for optional sub-messages.

This means a raw space from a stream event will have:
- `controls.hvac_mode == HVACMode.UNSPECIFIED` (not the real mode)
- `controls.heat_setpoint_c == 0.0` (not the real setpoint)
- `settings.name == ""` (not the real name)

The server sends only what changed. The `UNSPECIFIED` values are not errors — they are the proto3 default for absent fields.

This is the fundamental reason why you must always call `snapshot.apply_space(space)` rather than using the raw stream space directly.

---

## The `apply_*` merge methods

The `apply_*` family of methods (`apply_space`, `apply_indoor_unit`, `apply_outdoor_unit`, `apply_controller`, etc.) merge sparse stream diffs into the snapshot in-place.

For `apply_space()`, the logic is approximately:

1. If the diff's `controls` sub-message is absent (detected by `hvac_mode == UNSPECIFIED`), preserve the snapshot's existing `controls`.
2. If the diff's `controls` is present, use it (it contains the new full controls state for this space).
3. Apply the same logic for `state`, `settings`, and other sub-messages.
4. After merging, call `enrich_space()` to resolve `active_comfort_setting_type` from the snapshot's comfort-setting list.

The `UNSPECIFIED` sentinel detection is necessary because proto3 has no way to distinguish "field was explicitly set to its default value" from "field was absent". The library uses domain knowledge: a real space always has a non-UNSPECIFIED hvac_mode, so `UNSPECIFIED` reliably signals absence.

Step 4 — `enrich_space()` — is also important. Stream diffs do not carry comfort-setting metadata (the full `ComfortSetting` object). Without enrichment, `space.is_away` and `space.is_off` would not work correctly on stream-updated spaces because those properties depend on the `active_comfort_setting_type` resolved from the snapshot's comfort-setting list.

---

## The risk of using raw stream diffs without merging

If you use the raw stream space directly (without `apply_space`), you will see incorrect data:

```python
# DO NOT DO THIS
def on_space_update(space: Space) -> None:
    # space.controls.hvac_mode is UNSPECIFIED (not the real mode)
    # space.controls.heat_setpoint_c is 0.0 (not the real setpoint)
    print(f"{space.name}: mode={space.controls.hvac_mode}")  # always UNSPECIFIED
```

The bug is subtle: the name and temperature are correct (those fields were present in the diff), but the HVAC controls look wrong. This is a common mistake when first working with the library.

---

## Why this design matters for long-running integrations

A Home Assistant integration, automation daemon, or TUI dashboard may run for days or weeks without restarting. During that time, the snapshot is the only source of truth for fields that don't change frequently (room names, space hierarchies, comfort setting definitions). Re-fetching the full snapshot periodically is expensive and introduces a window where the in-memory state is stale.

The snapshot-and-stream pattern avoids this: the snapshot is fetched once at startup, and the stream keeps it current indefinitely. As long as the stream is healthy, the in-memory state is as current as the server's state. If the stream reconnects after a gap, the `max_reconnects=-1` setting ensures automatic recovery, and a periodic `invalidate_snapshot() + get_snapshot()` can be added as a consistency check for very long-running processes.

To implement this pattern, see [Stream real-time updates](../how-to/stream-updates.md) and [Build an automation daemon](../how-to/automation-daemon.md).
