# Stream real-time updates

Use this guide to subscribe to and process live HVAC events from the Quilt streaming API. For background on how the stream works, see [The streaming protocol](../explanation/streaming-protocol.md).

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
    stream.on_indoor_unit_update(lambda idu: print(snapshot.apply_indoor_unit(idu).id))
    stream.on_outdoor_unit_update(snapshot.apply_outdoor_unit)
    stream.on_controller_update(snapshot.apply_controller)
    stream.on_qsm_update(snapshot.apply_qsm)
    stream.on_remote_sensor_update(snapshot.apply_remote_sensor)
    stream.on_controller_remote_sensor_update(snapshot.apply_controller_remote_sensor)
    stream.on_software_update_info(lambda info: print(f"Update info: {info.id}"))
    stream.on_error(lambda e: print(f"Fatal error: {e}"))
    await asyncio.sleep(3600)  # run for 1 hour
```

`snapshot.stream_topics()` returns the full list of `hds/<type>/<id>` topic strings for every entity in your snapshot.

---

## Merge stream updates into a snapshot

Stream events carry only the fields that changed. Each event is a sparse diff. Always merge into the snapshot to preserve unchanged fields:

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
    print(f"{merged.id}: online={merged.is_online}")
```

For background on why sparse diffs require merging, see [Snapshot and stream data model](../explanation/snapshot-and-stream.md).

---

## Callback registration methods

`NotifierStream` accepts both synchronous and async callbacks. Register whichever entity types you care about:

| Method | Callback argument | Typical use |
| --- | --- | --- |
| `on_space_update()` | `Space` | Merge room diffs with `snapshot.apply_space()` |
| `on_indoor_unit_update()` | `IndoorUnit` | Merge IDU diffs with `snapshot.apply_indoor_unit()` |
| `on_outdoor_unit_update()` | `OutdoorUnit` | Merge ODU diffs with `snapshot.apply_outdoor_unit()` |
| `on_controller_update()` | `Controller` | Merge Dial diffs with `snapshot.apply_controller()` |
| `on_qsm_update()` | `QuiltSmartModule` | Merge QSM diffs with `snapshot.apply_qsm()` |
| `on_remote_sensor_update()` | `RemoteSensor` | Merge standalone sensor diffs with `snapshot.apply_remote_sensor()` |
| `on_controller_remote_sensor_update()` | `ControllerRemoteSensor` | Merge Dial sensor diffs with `snapshot.apply_controller_remote_sensor()` |
| `on_software_update_info()` | `SoftwareUpdateInfo` | Observe firmware/software update records |
| `on_error()` | `Exception` | Handle fatal stream failure after reconnects are exhausted |

---

## Lifecycle methods

Use these methods to control the stream explicitly:

| Method / property | What it does |
| --- | --- |
| `await stream.start()` | Starts the listener in the background |
| `await stream.run_forever()` | Runs inline until cancelled or a fatal error stops it |
| `await stream.stop()` | Cancels the background task and closes the stream |
| `await stream.subscribe(topics)` | Adds topic subscriptions after startup |
| `await stream.unsubscribe(topics)` | Removes topic subscriptions |
| `stream.error` | Last fatal exception, or `None` while healthy |

### Run the stream as a background task

To run the stream while doing other work concurrently:

```python
stream = client.stream(snapshot.stream_topics())
stream.on_space_update(on_space)
await stream.start()
try:
    result = await do_something_else()
    await asyncio.sleep(3600)
finally:
    await stream.stop()
    if stream.error is not None:
        print(f"Stream stopped with error: {stream.error}")
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

The stream reconnects automatically with exponential back-off (1 s, 2 s, 4 s, … up to a 60 s cap). Use `on_error()` or the `error` property to observe only fatal failures after the reconnect budget is exhausted. Configure the reconnect budget like this:

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

To observe fatal stream failures:

```python
stream.on_error(lambda e: print(f"Fatal error (budget exhausted): {e}"))

await stream.run_forever()
if stream.error is not None:
    print(f"Last fatal error: {stream.error}")
```

`on_error()` is called only when the reconnect budget is exhausted. Until then, disconnects and transient errors trigger automatic reconnection without surfacing a fatal error to your callback.

For the full reconnect state machine, see [The streaming protocol](../explanation/streaming-protocol.md).
