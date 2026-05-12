# Configure comfort settings

Comfort settings are named HVAC presets (Active, Sleep, Away, and any custom ones you create). Each preset stores a mode, heating setpoint, cooling setpoint, and fan speed. Assigning a preset to a room activates those settings.

---

## List all comfort settings for a system

To retrieve all comfort presets:

```python
settings = await client.list_comfort_settings()
for s in settings:
    print(f"{s.name}: mode={s.hvac_mode}, heat={s.heating_setpoint_c}°C, cool={s.cooling_setpoint_c}°C, fan={s.fan_speed}")
```

Alternatively, comfort settings are embedded in `SystemSnapshot`:

```python
snapshot = await client.get_snapshot()
for cs in snapshot.comfort_settings:
    print(f"{cs.name}: {cs.hvac_mode}")
```

---

## Update a comfort setting's setpoints and fan speed

To update a preset by name:

```python
from quilt_hp.models.enums import FanSpeed

settings = await client.list_comfort_settings()
active = next(s for s in settings if s.name == "Active")

updated = await client.update_comfort_setting(
    active,
    heat_setpoint_c=21.0,
    cool_setpoint_c=25.0,
    fan_speed=FanSpeed.AUTO,
)
print(f"Updated '{updated.name}': heat={updated.heating_setpoint_c}°C cool={updated.cooling_setpoint_c}°C")
```

Omit any parameter to keep its current value. You can also update by comfort setting ID string:

```python
updated = await client.update_comfort_setting(
    "comfort-setting-uuid",
    heat_setpoint_c=21.0,
)
```

---

## Apply a comfort setting to all rooms

To apply a named preset's mode and setpoints to every room:

```python
import asyncio
import sys
from quilt_hp import QuiltClient
from quilt_hp.cli.store import FileStore

PRESET_NAME = sys.argv[1] if len(sys.argv) > 1 else "Eco"

async def main() -> None:
    store = FileStore()
    async with QuiltClient("you@example.com", token_store=store) as client:
        await client.login()
        snapshot = await client.get_snapshot()

        preset = next(
            (cs for cs in snapshot.comfort_settings if cs.name == PRESET_NAME),
            None,
        )
        if preset is None:
            names = [cs.name for cs in snapshot.comfort_settings]
            print(f"Preset '{PRESET_NAME}' not found. Available: {names}")
            return

        for space in snapshot.rooms:
            updated = await client.set_space(
                space,
                mode=preset.hvac_mode,
                heat_setpoint_c=preset.heating_setpoint_c,
                cool_setpoint_c=preset.cooling_setpoint_c,
            )
            print(f"  {updated.name}: mode={updated.controls.hvac_mode}")

asyncio.run(main())
```

For the `ComfortSetting` model fields, see [Models reference](../reference/models.md).
