# CLI and scripting

The `quilt-hp` CLI is a thin wrapper around the Python client. It exposes the same operations as the Python API through subcommands that print JSON, making it easy to pipe output into `jq`, use in shell scripts, or call from CI pipelines.

---

## Authentication

Log in once to cache tokens:

```bash
quilt-hp login
```

The CLI prompts for your Quilt account email and OTP. Tokens are stored in `~/.config/quilt-hp/tokens.json` with permissions `0o600`. All subsequent commands read from this cache without prompting.

To log out and clear the token cache:

```bash
quilt-hp logout
```

---

## Environment variable

Set `QUILT_EMAIL` to avoid specifying `--email` on every command:

```bash
export QUILT_EMAIL="you@example.com"
```

---

## Getting a snapshot as JSON

```bash
quilt-hp snapshot
```

Outputs the full system state as JSON. Pipe to `jq` for filtering:

```bash
# All room names and current temperatures
quilt-hp snapshot | jq '.rooms[] | {name, temp: .state.current_temp_c}'

# Rooms currently in COOL mode
quilt-hp snapshot | jq '[.rooms[] | select(.controls.mode == "cool")]'

# All indoor units that are offline
quilt-hp snapshot | jq '[.indoor_units[] | select(.state.is_online == false)]'
```

---

## Controlling spaces from the shell

```bash
# Set a space to COOL mode at 22°C
quilt-hp set-space "Living Room" --mode cool --cool-setpoint 22

# Set to AUTO with a setpoint range
quilt-hp set-space "Bedroom" --mode auto --heat-setpoint 19 --cool-setpoint 24

# Turn off a space
quilt-hp set-space "Guest Room" --mode standby
```

---

## Bash script: set all rooms to a setpoint

```bash
#!/usr/bin/env bash
set -euo pipefail

SETPOINT="${1:-22}"

quilt-hp snapshot \
  | jq -r '.rooms[] | .name' \
  | while read -r room; do
      echo "Setting '$room' to ${SETPOINT}°C…"
      quilt-hp set-space "$room" --mode cool --cool-setpoint "$SETPOINT"
    done
```

---

## Python script: process snapshot from CLI output

When you want Python's expressiveness but don't need to import the library directly, call the CLI and parse its JSON output:

```python
#!/usr/bin/env python3
"""Parse quilt-hp snapshot JSON from stdout."""
import json
import subprocess
import sys

result = subprocess.run(
    ["quilt-hp", "snapshot", "--output", "json"],
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

## Cron job: nightly standby

Put all rooms in STANDBY at midnight:

```cron
0 0 * * * QUILT_EMAIL=you@example.com /usr/local/bin/quilt-hp set-all-spaces --mode standby
```

Or using a custom script that reads the snapshot to avoid calling the CLI per-room:

```bash
#!/usr/bin/env bash
# /usr/local/bin/quilt-standby
set -euo pipefail
quilt-hp snapshot | jq -r '.rooms[] | .id' | while read -r id; do
    quilt-hp set-space "$id" --mode standby
done
```

---

## Listing energy usage

```bash
# Last 7 days
quilt-hp energy --days 7

# Specific range
quilt-hp energy --start 2024-01-01 --end 2024-01-31

# As JSON for processing
quilt-hp energy --days 7 --output json | jq '[.[] | {space: .space_id, kwh: ([.buckets[].energy_kwh] | add)}]'
```

---

## Piping to monitoring tools

Write snapshot metrics to a file for Prometheus node_exporter's textfile collector:

```bash
#!/usr/bin/env bash
# /etc/cron.d/quilt-metrics — runs every minute
OUTFILE="/var/lib/node_exporter/quilt.prom"
TMPFILE="${OUTFILE}.tmp"

quilt-hp snapshot --output json | python3 - << 'PYEOF' > "$TMPFILE"
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

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Authentication error (re-run `quilt-hp login`) |
| 2 | Space or resource not found |
| 3 | Network or gRPC error |
| 4 | Invalid arguments |
