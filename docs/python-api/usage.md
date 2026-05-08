# Usage patterns

This page covers the most common patterns for using the `quilt_hp` library. For complete parameter documentation see [QuiltClient API reference](client-reference.md).

## Installation and imports

```bash
pip install quilt-hp-python
```

```python
import asyncio
from quilt_hp import QuiltClient, Environment, QuiltError, QuiltAuthError
from quilt_hp.models.enums import HVACMode, FanSpeed, LouverMode
```

## First login (OTP)

The first time you connect, Quilt sends a one-time password to your email. Provide an `otp_callback` that accepts the email address and returns the code:

```python
async def main() -> None:
    async with QuiltClient("you@example.com") as client:
        await client.login(otp_callback=lambda email: input(f"OTP for {email}: "))
        print("Logged in.")

asyncio.run(main())
```

The callback can also be async:

```python
async def get_otp(email: str) -> str:
    return input(f"Enter OTP sent to {email}: ")

await client.login(otp_callback=get_otp)
```

## Login with token persistence

To avoid the OTP prompt on subsequent runs, pass a `token_store`. The `FileStore` that ships with the CLI stores tokens in `~/.config/quilt-hp/tokens.json`:

```python
from quilt_hp.cli.store import FileStore

store = FileStore()

async with QuiltClient("you@example.com", token_store=store) as client:
    # First run: OTP required. Subsequent runs: uses cached token silently.
    await client.login(otp_callback=lambda email: input(f"OTP for {email}: "))
    # Do work here...
```

If the cached access token is expired but the refresh token is still valid, `login()` performs a silent refresh with no user interaction.

## Listing systems (multi-home accounts)

If your account has access to multiple systems (homes), list them first:

```python
systems = await client.list_systems()
for s in systems:
    print(f"{s.name} — {s.id}")
```

For a single-home account, `QuiltClient` automatically uses the first system. For multi-home accounts, pass `home="My Home Name"` to the constructor to filter by name:

```python
client = QuiltClient("you@example.com", home="Beach House")
```

## Fetching a snapshot

`get_snapshot()` returns a `SystemSnapshot` with the complete current state of the system:

```python
snapshot = await client.get_snapshot()

# All spaces (including root home space)
for space in snapshot.spaces:
    print(f"{space.name}: {space.state.ambient_temperature_c}°C")

# Room spaces only (leaf nodes with a parent)
for room in snapshot.rooms:
    mode = room.controls.hvac_mode
    temp = room.state.ambient_temperature_c
    print(f"{room.name}: mode={mode}, temp={temp:.1f}°C")
```

For read-heavy integrations, enable the snapshot cache:

```python
client = QuiltClient("you@example.com", snapshot_ttl_s=30.0)
# Subsequent get_snapshot() calls within 30s return the cached copy.
```

## Listing spaces and temperatures

```python
async with QuiltClient("you@example.com", token_store=store) as client:
    await client.login()
    for space in await client.list_spaces():
        temp = space.state.ambient_temperature_c
        mode = space.controls.hvac_mode
        setpoint = space.controls.display_setpoint  # human-readable setpoint string
        print(f"{space.name:20s}: {temp:.1f}°C  mode={mode}  setpoint={setpoint}")
```

## Setting a space's HVAC mode

`set_space()` accepts either a `Space` object (from a snapshot) or a space ID string. Passing the `Space` object avoids a snapshot lookup:

```python
snapshot = await client.get_snapshot()
living_room = snapshot.space_by_name("Living Room")

if living_room:
    updated = await client.set_space(living_room, mode=HVACMode.HEAT)
    print(f"Set to HEAT: {updated.controls.hvac_mode}")
```

Setting by ID (performs a snapshot lookup internally):

```python
updated = await client.set_space("room-uuid-here", mode=HVACMode.COOL, cool_setpoint_c=22.0)
```

## Setting setpoints

Pass `heat_setpoint_c` and/or `cool_setpoint_c` along with the mode:

```python
updated = await client.set_space(
    room,
    mode=HVACMode.AUTO,
    heat_setpoint_c=20.0,
    cool_setpoint_c=24.0,
)
```

In AUTO mode, the library enforces a minimum 2.5°C gap: if `cool - heat < 2.5`, the cooling setpoint is raised to `heat + 2.5` automatically.

## Turning off a room (STANDBY)

```python
await client.set_space(room, mode=HVACMode.STANDBY)
```

Setting STANDBY clears the active comfort setting so occupancy automation cannot re-activate the room. If you want the room to turn back on when someone enters, use the AWAY comfort setting instead.

## Updating auto-away settings

```python
await client.set_space_settings(
    room,
    unoccupied_timeout_s=900.0,   # 15 min of no presence → auto-away
    occupied_timeout_s=120.0,     # 2 min of presence → auto-return
)
```

## Controlling an indoor unit

Set fan speed, louver mode, and LED:

```python
snapshot = await client.get_snapshot()
idu = snapshot.indoor_units[0]

updated = await client.set_indoor_unit(
    idu,
    fan_speed=FanSpeed.MEDIUM,
    louver_mode=LouverMode.SWEEP,
)
```

Set the LED to a warm white colour:

```python
from quilt_hp.models.enums import LightPreset

updated = await client.set_indoor_unit(
    idu,
    led_color_code=LightPreset.WARM,
    led_brightness=0.5,
)
```

## Updating a comfort setting

```python
settings = await client.list_comfort_settings()
active = next(s for s in settings if s.name == "Active")

updated = await client.update_comfort_setting(
    active,
    heat_setpoint_c=21.0,
    cool_setpoint_c=25.0,
    fan_speed=FanSpeed.AUTO,
)
```

## Subscribing to real-time updates

Use `client.stream()` with the topic list from `snapshot.stream_topics()`:

```python
snapshot = await client.get_snapshot()

def on_space_update(space: Space) -> None:
    merged = snapshot.apply_space(space)  # merge sparse diff into snapshot
    print(f"{merged.name}: {merged.state.ambient_temperature_c:.1f}°C, mode={merged.controls.hvac_mode}")

stream = client.stream(snapshot.stream_topics())
stream.on_space_update(on_space_update)
stream.on_error(lambda e: print(f"Stream error: {e}"))

# Block until cancelled:
await stream.run_forever()
```

As a background task (useful in integrations that do other work concurrently):

```python
async with client.stream(snapshot.stream_topics()) as stream:
    stream.on_space_update(on_space_update)
    # The stream runs in the background. Do other things here.
    await asyncio.sleep(3600)
```

## Querying energy metrics

```python
from datetime import datetime, timezone, timedelta

now = datetime.now(tz=timezone.utc)
week_ago = now - timedelta(days=7)

metrics = await client.get_energy(start=week_ago, end=now)
for space_metrics in metrics:
    total_kwh = sum(b.energy_kwh for b in space_metrics.buckets)
    print(f"Space {space_metrics.space_id}: {total_kwh:.2f} kWh over 7 days")
```

## Error handling

```python
from quilt_hp import QuiltError, QuiltAuthError, QuiltNotFoundError

try:
    await client.login(otp_callback=lambda email: input("OTP: "))
except QuiltAuthError as e:
    print(f"Authentication failed: {e}")

try:
    snapshot = await client.get_snapshot()
except QuiltError as e:
    print(f"API error: {e}")
```

All library exceptions inherit from `QuiltError`. Catch `QuiltAuthError` specifically for authentication failures, `QuiltNotFoundError` for missing resources, and `QuiltError` for everything else.
