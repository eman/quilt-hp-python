# Control spaces and indoor units

This page covers how to change HVAC settings on spaces (rooms) and indoor units. All examples assume you have an authenticated `QuiltClient` and a `SystemSnapshot`. For authentication setup, see [Authenticate and manage tokens](authenticate.md).

---

## Set a space to a specific HVAC mode

To set a space's mode using a `Space` object from a snapshot:

```python
from quilt_hp.models.enums import HVACMode

snapshot = await client.get_snapshot()
living_room = snapshot.space_by_name("Living Room")

if living_room:
    updated = await client.set_space(living_room, mode=HVACMode.COOL)
    print(f"Mode: {updated.controls.hvac_mode}")
```

To set by space ID string (performs an internal snapshot lookup):

```python
updated = await client.set_space("room-uuid-here", mode=HVACMode.HEAT)
```

Available modes: `HVACMode.STANDBY`, `COOL`, `HEAT`, `AUTO`, `FAN`.

---

## Set heating and cooling setpoints

To set only the cooling setpoint without changing the mode:

```python
updated = await client.set_space(room, cool_setpoint_c=22.0)
```

To set only the heating setpoint:

```python
updated = await client.set_space(room, heat_setpoint_c=19.0)
```

To set mode and a single setpoint together:

```python
updated = await client.set_space(room, mode=HVACMode.COOL, cool_setpoint_c=22.0)
```

---

## Set AUTO mode with a setpoint range

To set AUTO mode with both heating and cooling setpoints:

```python
updated = await client.set_space(
    room,
    mode=HVACMode.AUTO,
    heat_setpoint_c=20.0,
    cool_setpoint_c=24.0,
)
```

In AUTO mode, the library enforces a minimum 2.5°C gap between heating and cooling setpoints. If `cool - heat < 2.5`, the cooling setpoint is automatically raised to `heat + 2.5`.

---

## Turn off a room (STANDBY)

To turn a room off:

```python
updated = await client.set_space(room, mode=HVACMode.STANDBY)
```

Setting STANDBY clears the active comfort setting association — the room stays off regardless of occupancy automation. To turn the room back on, set a different mode.

---

## Control fan speed on an indoor unit

To set the fan speed on an indoor unit:

```python
from quilt_hp.models.enums import FanSpeed

snapshot = await client.get_snapshot()
idu = snapshot.indoor_units[next(iter(snapshot.indoor_units))]  # first IDU

updated = await client.set_indoor_unit(idu, fan_speed=FanSpeed.MEDIUM)
print(f"Fan speed: {updated.controls.fan_speed}")
```

Available fan speeds: `FanSpeed.AUTO`, `QUIET`, `LOW`, `MEDIUM`, `HIGH`, `BLAST`.

---

## Set louver mode and position

To sweep the louver continuously:

```python
from quilt_hp.models.enums import LouverMode

updated = await client.set_indoor_unit(idu, louver_mode=LouverMode.SWEEP)
```

To fix the louver at a specific position (0.0 = fully down, 1.0 = fully up):

```python
updated = await client.set_indoor_unit(
    idu,
    louver_mode=LouverMode.FIXED,
    louver_position=0.5,
)
```

---

## Set LED color and brightness

To set the LED to a warm white color at 50% brightness:

```python
from quilt_hp.models.enums import LightPreset

updated = await client.set_indoor_unit(
    idu,
    led_color_code=LightPreset.WARM,
    led_brightness=0.5,
)
```

To turn the LED off:

```python
updated = await client.set_indoor_unit(idu, led_brightness=0.0)
```

`led_color_code` is an RGBW-packed `int32`. Use `LightPreset` constants for common colors, or compute the value manually.

---

## Configure auto-away timeouts

To set how long a room waits before switching to away mode (and back):

```python
updated = await client.set_space_settings(
    room,
    unoccupied_timeout_s=900.0,   # 15 min of no presence → auto-away
    occupied_timeout_s=120.0,     # 2 min of presence → auto-return
)
```

Omit either parameter to leave its current value unchanged.
