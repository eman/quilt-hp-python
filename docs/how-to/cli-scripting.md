# Automate with the CLI

The `quilt` CLI exposes the same operations as the Python API through subcommands that print JSON, making it easy to pipe output into `jq`, use in shell scripts, or call from CI pipelines.

---

## Authenticate from the command line

To log in and cache tokens:

```bash
quilt login
```

The CLI prompts for your Quilt account email and OTP. Tokens are stored in `~/.config/quilt-hp/tokens.json` with permissions `0o600`. All subsequent commands read from this cache without prompting.

To log out and clear the token cache:

```bash
quilt logout
```

To avoid specifying `--email` on every command, set the environment variable:

```bash
export QUILT_EMAIL="you@example.com"
```

---

## Get a system snapshot as JSON

```bash
quilt snapshot
```

Pipe to `jq` for filtering:

```bash
# All room names and current temperatures
quilt snapshot | jq '.rooms[] | {name, temp: .state.current_temp_c}'

# Rooms currently in COOL mode
quilt snapshot | jq '[.rooms[] | select(.controls.mode == "cool")]'

# All indoor units that are offline
quilt snapshot | jq '[.indoor_units[] | select(.state.is_online == false)]'
```

---

## Check diagnostics

```bash
# Human-readable: per-IDU fault conditions, refrigerant temps, and power
quilt diagnostics

# Only indoor units with an active fault
quilt diagnostics --faults-only

# JSON for scripting — e.g. list every active fault system-wide
quilt diagnostics --output json | jq '.indoor_units[] | select(.active_faults | length > 0) | {name, active_faults}'
```

The outdoor unit's own raw sensors (compressor Hz, pressures, discharge temp)
are withheld from the cloud plane; the diagnostic conditions and refrigerant
pipe temperatures for each ODU circuit are surfaced through its indoor units.

---

## Control spaces from the shell

```bash
# Set a space to COOL mode at 22°C
quilt set-space "Living Room" --mode cool --cool-setpoint 22

# Set to AUTO with a setpoint range
quilt set-space "Bedroom" --mode auto --heat-setpoint 19 --cool-setpoint 24

# Turn off a space
quilt set-space "Guest Room" --mode standby
```

---

## Write a bash script to set all rooms to a setpoint

```bash
#!/usr/bin/env bash
set -euo pipefail

SETPOINT="${1:-22}"

quilt snapshot \
  | jq -r '.rooms[] | .name' \
  | while read -r room; do
      echo "Setting '$room' to ${SETPOINT}°C…"
      quilt set-space "$room" --mode cool --cool-setpoint "$SETPOINT"
    done
```

---

## Process snapshot output in Python without importing the library

When you want Python's expressiveness but don't need to import the library directly:

```python
#!/usr/bin/env python3
import json
import subprocess

result = subprocess.run(
    ["quilt", "snapshot", "--output", "json"],
    capture_output=True,
    text=True,
    check=True,
)
data = json.loads(result.stdout)

print(f"System: {data['system_id']}")
for room in data["rooms"]:
    temp = room["state"]["current_temp_c"]
    mode = room["controls"]["mode"]
    temp_str = f"{temp:.1f}°C" if temp is not None else "unknown"
    print(f"  {room['name']:<20} {mode:<8} {temp_str}")
```

---

## Set up a cron job for nightly standby

Put all rooms in STANDBY at midnight:

```cron
0 0 * * * QUILT_EMAIL=you@example.com /usr/local/bin/quilt set-all-spaces --mode standby
```

Or use a script that reads the snapshot to avoid a CLI call per room:

```bash
#!/usr/bin/env bash
# /usr/local/bin/quilt-standby
set -euo pipefail
quilt snapshot | jq -r '.rooms[] | .id' | while read -r id; do
    quilt set-space "$id" --mode standby
done
```

---

## Write snapshot metrics to a Prometheus textfile

```bash
#!/usr/bin/env bash
# Runs every minute via cron
OUTFILE="/var/lib/node_exporter/quilt.prom"
TMPFILE="${OUTFILE}.tmp"

quilt snapshot --output json | python3 - << 'PYEOF' > "$TMPFILE"
import sys, json
data = json.load(sys.stdin)
for room in data["rooms"]:
    name = room["name"].lower().replace(" ", "_")
    mode = room["controls"]["mode"]
    temp = room["state"]["current_temp_c"] or "NaN"
    print(f'quilt_room_temp_celsius{{room="{name}"}} {temp}')
    print(f'quilt_room_mode{{room="{name}",mode="{mode}"}} 1')
PYEOF

mv "$TMPFILE" "$OUTFILE"
```

---

## Query energy usage

```bash
# Last 7 days
quilt energy --days 7

# Specific date range
quilt energy --start 2024-01-01 --end 2024-01-31

# As JSON, summed per space
quilt energy --days 7 --output json \
  | jq '[.[] | {space: .space_id, kwh: ([.buckets[].energy_kwh] | add)}]'
```

---

## CLI exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Authentication error (re-run `quilt login`) |
| 2 | Space or resource not found |
| 3 | Network or gRPC error |
| 4 | Invalid arguments |
