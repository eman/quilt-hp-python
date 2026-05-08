# Stream real-time updates

This page covers how to subscribe to and process live HVAC events from the Quilt streaming API. For background on how the stream works, see [The streaming protocol](../explanation/streaming-protocol.md).

---

## Subscribe to real-time updates for all entities

To open a stream and receive updates for every entity in your system:

```python
from quilt_hp.models.space import Space
from quilt_hp.models.indoor_unit import IndoorUnit

snapshot = await client.get_snapshot()

def on_space(space: Space) -> None:
    merged = snapshot.apply_space(space)
    print(f"{merged.name}: {merged.state.ambient_temperature_c}°C")

def on_idu(idu: IndoorUnit) -> None:
    print(f"IDU {idu.id}: fan={idu.controls.fan_speed}")

async with client.stream(snapshot.stream_topics()) as stream:
    stream.on_space_update(on_space)
    stream.on_indoor_unit_update(on_idu)
    stream.on_error(lambda e: print(f"Fatal error: {e}"))
    await asyncio.sleep(3600)  # run for 1 hour
```

`snapshot.stream_topics()` returns the full list of `hds/<type>/<id>` topic strings for every entity in your snapshot.

---

## Merge stream updates into a snapshot

Stream events carry only the fields that changed — a sparse diff. Always merge into the snapshot to preserve unchanged fields:

```python
snapshot = await client.get_snapshot()

def on_space(space: Space) -> None:
    # Without apply_space, hvac_mode and setpoints would appear as UNSPECIFIED/0
    merged = snapshot.apply_space(space)
    print(f"{merged.name}: mode={merged.controls.hvac_mode}, temp={merged.state.ambient_temperature_c}°C")

stream = client.stream(snapshot.stream_topics())
stream.on_space_update(on_space)
await stream.run_forever()
```

For indoor units:

```python
def on_idu(idu: IndoorUnit) -> None:
    merged = snapshot.apply_indoor_unit(idu)
    print(f"{merged.id}: online={merged.state.is_online}")
```

For background on why sparse diffs require merging, see [Snapshot and stream data model](../explanation/snapshot-and-stream.md).

---

## Run the stream as a background task

To run the stream while doing other work concurrently:

```python
async with client.stream(snapshot.stream_topics()) as stream:
    stream.on_space_update(on_space)
    # Stream runs in the background — do other work here
    result = await do_something_else()
    await asyncio.sleep(3600)
# Stream is stopped when the async with block exits
```

Use this pattern in integrations (Home Assistant, automation daemons) where the stream is just one part of a larger async application.

---

## Run the stream as a blocking call

To block the current coroutine until the stream ends or encounters a fatal error:

```python
stream = client.stream(snapshot.stream_topics())
stream.on_space_update(on_space)
stream.on_error(lambda e: print(f"Fatal: {e}"))
await stream.run_forever()  # blocks until cancelled or budget exhausted
```

Use this pattern in standalone scripts and CLI tools.

---

## Handle dynamic subscription changes

To subscribe to additional topics while the stream is running:

```python
async with client.stream(snapshot.stream_topics()) as stream:
    stream.on_space_update(on_space)
    await asyncio.sleep(5)

    # Add a new topic for a newly discovered entity
    await stream.subscribe(["hds/space/new-room-uuid"])

    # Remove a topic you no longer need
    await stream.unsubscribe(["hds/space/old-room-uuid"])

    await asyncio.sleep(3600)
```

---

## Handle stream errors and reconnect

The stream reconnects automatically with exponential back-off (1 s, 2 s, 4 s, … up to 60 s cap). To configure the reconnect budget:

```python
# Unlimited reconnects (default: -1)
stream = client.stream(snapshot.stream_topics(), max_reconnects=-1)

# Exactly 5 reconnect attempts before giving up
stream = client.stream(snapshot.stream_topics(), max_reconnects=5)

# Adjust the initial back-off delay
stream = client.stream(
    snapshot.stream_topics(),
    max_reconnects=-1,
    reconnect_delay_s=2.0,  # start at 2s, doubles to 60s cap
)
```

To observe connection lifecycle events:

```python
stream.on_connected(lambda: print("Stream connected"))
stream.on_disconnected(lambda: print("Stream disconnected; will reconnect"))
stream.on_error(lambda e: print(f"Fatal error (budget exhausted): {e}"))
```

`on_error` is called only when the reconnect budget is exhausted. Until then, disconnects and errors trigger automatic reconnection without invoking `on_error`.

For the full reconnect state machine, see [The streaming protocol](../explanation/streaming-protocol.md).
