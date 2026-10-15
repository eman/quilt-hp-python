# Control a Dial over Bluetooth

`BluetoothControlClient` drives a Quilt Dial directly over Bluetooth Low Energy, with no cloud
and no account. It reads the Dial's live climate and damper state and writes setpoint, mode, fan,
and power commands, mirroring the app's installer "Remote Control" tool (added in app 1.0.34).

!!! warning "Experimental and reconstructed"
    This protocol was reconstructed by decompiling the Quilt app and is **not yet verified against
    physical hardware**. The GATT layout and message shapes may be wrong. There is no encryption or
    pairing: physical access is "proven" only by being close enough to read the Dial over BLE.

## Install the BLE extra

The transport needs [`bleak`](https://bleak.readthedocs.io/), an optional dependency:

```bash
pip install "quilt-hp-python[ble]"
```

Without it, constructing a `BluetoothControlClient` raises `QuiltBluetoothError` with install
instructions.

## Find a Dial

A Dial that is connectable for remote control advertises Quilt's manufacturer id. Scan for one:

```python
from quilt_hp.bluetooth import discover_dials

for address, name in await discover_dials(duration=8.0):
    print(address, name)
```

## Connect and read state

Use the client as an async context manager. On connect it reads the Dial's serial (the
physical-access challenge) and verifies the control service is present.

```python
from quilt_hp.bluetooth import BluetoothControlClient

async with BluetoothControlClient("AA:BB:CC:DD:EE:FF") as dial:
    print("serial", dial.serial)

    controls = await dial.read_climate_controls()   # power, mode, setpoints, fan
    state = await dial.read_climate_state()          # status, operation, ambient temp
    dampers = await dial.read_damper_state()         # ducted-zone dampers
    print(state.status, state.operation, state.ambient_temperature_c)
```

## Send commands

Each command writes one action and waits for the Dial's response. A non-OK response raises
`QuiltBluetoothError`, with the device's `BluetoothActionResult` on the exception's `result`.

```python
from quilt_hp.bluetooth import ClimateMode, FanSpeedMode

async with BluetoothControlClient("AA:BB:CC:DD:EE:FF") as dial:
    await dial.set_power(True, mode=ClimateMode.HEAT)
    await dial.set_temperatures(heat_c=20.0)           # omit cool_c to leave it unchanged
    await dial.set_mode(ClimateMode.COOL)
    await dial.set_fan_speed(FanSpeedMode.PERCENT, percent=60)
```

## React to changes without polling

The Dial exposes a change-counter notification. Subscribe, then re-read only the characteristic
whose counter moved:

```python
async with BluetoothControlClient(address) as dial:
    last = None

    def on_change(counters):
        nonlocal last
        # compare counters.climate_state / climate_controls / damper_state to decide what to re-read
        last = counters

    await dial.subscribe_changes(on_change)
    # ... keep the connection open while you handle notifications ...
```

## Errors

`QuiltBluetoothError` covers every BLE failure: `bleak` missing, device not found or unreachable,
the control service absent, a timed-out action, or a Dial that rejects the command.
