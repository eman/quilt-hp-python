# Quilt Python Client

Python client library for [Quilt](https://www.quilt.com/) mini-split HVAC systems.

Communicates with the Quilt cloud API via gRPC to control spaces (rooms), indoor units,
comfort presets, schedules, and stream real-time updates.

## Installation

```bash
pip install quilt-hp-python
```

With the optional CLI:

```bash
pip install "quilt-hp-python[cli]"
```

## Quick Start

```python
import asyncio
from quilt_hp import QuiltClient

async def main():
    async with QuiltClient("user@example.com") as client:
        await client.login(otp_callback=lambda email: input(f"OTP for {email}: "))

        # List spaces
        for space in await client.list_spaces():
            print(f"{space.name}: {space.state.ambient_temperature_c}°C")

        # Set a room to COOL at 22°C
        from quilt_hp.models.enums import HVACMode
        spaces = await client.list_spaces()
        await client.set_space(spaces[0].id, mode=HVACMode.COOL, cool_setpoint_c=22.0)

        # Stream real-time updates
        spaces = await client.list_spaces()
        topics = [f"hds/space/{s.id}" for s in spaces]
        async with client.stream(topics) as stream:
            stream.on_space_update(lambda s: print(f"{s.name}: {s.state.ambient_temperature_c}°C"))
            await asyncio.sleep(60)

asyncio.run(main())
```

## CLI

```bash
# Authenticate (caches tokens for subsequent commands)
quilt login --email user@example.com

# Full system inventory + telemetry (summary)
quilt info

# Full system snapshot as JSON for automation
quilt info --output json

# All device/entity IDs (includes update entities)
quilt devices

# Current sensor values + setpoints
quilt values

# Machine-readable values for scripting
quilt values --output json

# Energy usage
quilt energy --period week

# Set a room to cooling mode
quilt set "Living Room" --mode cool --cool 22
```

## Related Projects

- **[homeassistant-quilt-hp](https://github.com/eman/homeassistant-quilt-hp)** — Home Assistant custom integration built on this library. Exposes Quilt spaces, indoor/outdoor units, sensors, and schedules as HA entities with full climate control.

## Development

```bash
git clone https://github.com/eman/quilt-hp-python.git
cd quilt-hp-python
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,cli]"

# Run checks
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/quilt_hp/
pytest
python -m build
twine check dist/*

# Recompile protobuf stubs (requires grpcio-tools)
# Proto sources are vendored in ./proto/cleaned for standalone use.
# Optional but recommended: install protobuf includes (e.g. `brew install protobuf`)
./scripts/regen_protos.sh

# Build project docs (MkDocs Material)
pip install -e ".[docs]"
python scripts/check_docs_nav.py
mkdocs build --strict
```

## License

MIT
