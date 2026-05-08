# Get started with quilt-hp-python

In this tutorial you'll build a script that does four things: logs in to the Quilt API, reads all your rooms with their current temperatures, sets one room to cooling mode, and receives a live update over the real-time stream. By the end you'll have a working script and a clear mental model of how the library fits together.

**Prerequisites:**
- Python 3.12 or newer
- A Quilt account with at least one system installed and set up
- Basic familiarity with `asyncio` and `async/await` in Python

---

## Install the package

```bash
pip install quilt-hp-python
```

That's the only dependency you need. The gRPC stubs are bundled, so there's nothing extra to install.

---

## Step 1 — First login

Create a file called `quilt_demo.py` and add this:

```python
import asyncio
from quilt_hp import QuiltClient

async def main() -> None:
    async with QuiltClient("you@example.com") as client:
        await client.login(otp_callback=lambda email: input(f"OTP for {email}: "))
        print("Logged in successfully!")

asyncio.run(main())
```

Run it:

```bash
python quilt_demo.py
```

Quilt will send a one-time password to your email address. Type it in when prompted. You'll see `Logged in successfully!` — the library exchanged your OTP for a Cognito session token and is now authenticated.

You'll notice that if you run the script again immediately, it still asks for an OTP. That's because we haven't told the library where to save the tokens yet. Let's fix that now — update your script to use `FileStore`:

```python
import asyncio
from quilt_hp import QuiltClient
from quilt_hp.cli.store import FileStore

store = FileStore()  # saves tokens in ~/.config/quilt-hp/tokens.json

async def main() -> None:
    async with QuiltClient("you@example.com", token_store=store) as client:
        await client.login(otp_callback=lambda email: input(f"OTP for {email}: "))
        print("Logged in successfully!")

asyncio.run(main())
```

Run it once more. After this run, the tokens are cached. Try running it a third time — no OTP prompt. The library found the cached tokens and reused them.

---

## Step 2 — Read your system

Now let's fetch the current state of your home and print every room's temperature. Add `get_snapshot()` after the login:

```python
import asyncio
from quilt_hp import QuiltClient
from quilt_hp.cli.store import FileStore

store = FileStore()

async def main() -> None:
    async with QuiltClient("you@example.com", token_store=store) as client:
        await client.login(otp_callback=lambda email: input(f"OTP for {email}: "))

        snapshot = await client.get_snapshot()
        print(f"System: {snapshot.system_id}")
        print()

        for room in snapshot.rooms:
            temp = room.state.ambient_temperature_c
            mode = room.controls.hvac_mode
            temp_str = f"{temp:.1f}°C" if temp is not None else "—"
            print(f"{room.name:<20} {mode:<8} {temp_str}")

asyncio.run(main())
```

You'll see something like:

```
System: a1b2c3d4-...

Bedroom              HEAT     21.3°C
Living Room          AUTO     20.8°C
Guest Room           STANDBY  —
```

`snapshot` is a `SystemSnapshot` — the object that represents your whole home at a point in time. It contains every room, indoor unit, outdoor unit, sensor, comfort setting, and schedule in a single data structure. Think of it as a complete photograph of your system.

`snapshot.rooms` gives you only the leaf-level room spaces (not floor-level groupings). Each room has a `state` (what the sensors are reading right now) and `controls` (what the system is set to do).

---

## Step 3 — Control a space

Now let's set a room to cooling mode. We'll look up the Living Room by name and tell it to cool:

```python
from quilt_hp.models.enums import HVACMode

# ... (inside main, after get_snapshot) ...

living_room = snapshot.space_by_name("Living Room")
if living_room:
    updated = await client.set_space(
        living_room,
        mode=HVACMode.COOL,
        cool_setpoint_c=22.0,
    )
    print(f"\nUpdated: {updated.name} → mode={updated.controls.hvac_mode}, setpoint={updated.controls.cool_setpoint_c}°C")
else:
    print("Living Room not found — check the name in your snapshot output above")
```

Run the script. You'll see the updated room state echoed back from the server. If you look at your Quilt app, the Living Room should now show COOL mode at 22°C.

A few things to notice: `set_space()` accepts the `Space` object directly (not just an ID), which saves a snapshot lookup. The returned `updated` is a fresh `Space` reflecting what the server has accepted.

---

## Step 4 — Stream a live update

The final step is subscribing to real-time updates. Instead of polling, the library opens a persistent gRPC stream that the server uses to push changes as they happen.

Replace your `main` function with this complete version:

```python
import asyncio
from quilt_hp import QuiltClient
from quilt_hp.cli.store import FileStore
from quilt_hp.models.enums import HVACMode
from quilt_hp.models.space import Space

store = FileStore()

async def main() -> None:
    async with QuiltClient("you@example.com", token_store=store) as client:
        await client.login(otp_callback=lambda email: input(f"OTP for {email}: "))

        snapshot = await client.get_snapshot()
        print(f"Loaded {len(snapshot.rooms)} rooms\n")

        # Set one room to cool (optional — just to trigger a stream event)
        living_room = snapshot.space_by_name("Living Room")
        if living_room:
            await client.set_space(living_room, mode=HVACMode.COOL, cool_setpoint_c=22.0)

        # Register a callback for space updates
        def on_space_update(space: Space) -> None:
            merged = snapshot.apply_space(space)
            temp = f"{merged.state.ambient_temperature_c:.1f}°C" if merged.state.ambient_temperature_c else "—"
            print(f"Update: {merged.name} → mode={merged.controls.hvac_mode}, temp={temp}")

        # Open the stream and wait 30 seconds for updates
        async with client.stream(snapshot.stream_topics()) as stream:
            stream.on_space_update(on_space_update)
            stream.on_error(lambda e: print(f"Stream error: {e}"))
            print("Streaming for 30 seconds…")
            await asyncio.sleep(30)

        print("Done.")

asyncio.run(main())
```

Run it. Within a few seconds you'll see update lines appearing as the server pushes the current state of your rooms. If you change something in the Quilt app while the script is running, you'll see the update arrive in real time.

Notice the `snapshot.apply_space(space)` call inside the callback. Stream events are *sparse* — they only carry the fields that changed. Calling `apply_space` merges the diff into the full snapshot so you always have a complete picture of each room. Without that merge, zero-valued proto3 defaults would overwrite real data.

---

## What just happened

You've covered the four fundamental operations of the library:

1. **`login()`** — authenticates with Cognito using an OTP, then caches tokens in `FileStore` for future runs. Subsequent calls reuse the cached token silently.
2. **`get_snapshot()`** — fetches the complete state of your Quilt installation in a single RPC call, returning a `SystemSnapshot` with all entities.
3. **`set_space()`** — sends a control command to change a room's HVAC mode and setpoints. The server returns the updated state.
4. **`client.stream()`** — opens a bidirectional gRPC stream, registers callbacks, and delivers real-time change events as they happen.

Everything else in the library builds on these four patterns.

---

## Where to go next

- **[How-to guides](../how-to/authenticate.md)** — step-by-step recipes for specific tasks: custom token stores, controlling indoor units, scheduling, daemon patterns, and more.
- **[QuiltClient reference](../reference/client.md)** — complete API documentation for every method, parameter, and return type.
- **[Architecture](../explanation/architecture.md)** — a discussion of why the library is structured the way it is and what each layer does.
- **[Snapshot and stream data model](../explanation/snapshot-and-stream.md)** — a deeper look at `SystemSnapshot`, sparse diffs, and why `apply_space()` matters.
