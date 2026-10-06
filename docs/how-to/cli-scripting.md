# Automate with the CLI

The `quilt` CLI exposes the library's read and control operations as subcommands. `info`,
`devices`, `values` and `diagnostics` take `--output json`, so you can pipe them into `jq`, use
them in shell scripts, or call them from CI pipelines.

---

## Authenticate from the command line

To log in and cache tokens:

```bash
quilt login --email you@example.com
```

The CLI emails you a one-time code and prompts for it. Tokens are cached in `tokens.json` in the
user config directory (`~/.config/quilt-hp/` on Linux, `~/Library/Application Support/quilt-hp/`
on macOS) with permissions `0o600`. Later commands reuse the cache without prompting. To log out,
delete that file.

To avoid passing `--email` on every command, set the environment variable:

```bash
export QUILT_EMAIL="you@example.com"
```

---

## Get a system snapshot as JSON

```bash
quilt info --output json
```

`info` returns every entity: `spaces`, `indoor_units`, `outdoor_units`, `controllers` (Dials),
`quilt_smart_modules`, `remote_sensors`, plus `timezone` and `version_at`. The `spaces` list
includes the home itself; rooms have `"is_room": true`.

Pipe to `jq` for filtering:

```bash
# Every room with its temperature
quilt info --output json \
  | jq '.spaces[] | select(.is_room) | {name, temp_c: .state.ambient_temperature_c}'

# Rooms currently in COOL mode
quilt info --output json \
  | jq '[.spaces[] | select(.is_room and .controls.hvac_mode == "COOL") | .name]'

# Dials that are offline
quilt info --output json | jq '[.controllers[] | select(.is_online == false) | .name]'
```

`quilt values --output json` is a smaller payload with only setpoints and sensor readings.

---

## Read Dial presence and display state

Each Dial reports what its screen is doing and whether its own radar sees someone:

```bash
quilt info --output json | jq '.controllers[] | {
  room: .space_name,
  display: .view_state,          # SLEEP, GLANCE or ACTIVE
  brightness: .screen_brightness,
  presence: .presence_detected,  # Dial radar: target or phase detection
  light_lx: .ambient_light_lux
}'
```

---

## Detect configuration changes

`version_at` is the time of the last write to any control, setting or configuration in the
system. It doesn't change on sensor telemetry. Poll it to re-sync only when something changed:

```bash
#!/usr/bin/env bash
set -euo pipefail
STATE=/var/tmp/quilt-version
now=$(quilt info --output json | jq -r '.version_at')
if [[ "$now" != "$(cat "$STATE" 2>/dev/null)" ]]; then
    echo "$now" > "$STATE"
    echo "Quilt configuration changed at $now"
fi
```

---

## Check diagnostics

```bash
# Human-readable: per-IDU fault conditions, refrigerant temps, dew point and power
quilt diagnostics

# Only indoor units with an active fault
quilt diagnostics --faults-only

# JSON for scripting: every active fault system-wide
quilt diagnostics --output json \
  | jq '.indoor_units[] | select(.active_faults | length > 0) | {name, active_faults}'

# Indoor units running a health check or commissioning test
quilt diagnostics --output json | jq '[.indoor_units[] | select(.under_test) | {name, test}]'
```

The outdoor unit's own raw sensors (compressor Hz, pressures, discharge temp)
are withheld from the cloud plane; the diagnostic conditions and refrigerant
pipe temperatures for each ODU circuit are surfaced through its indoor units.

---

## Control rooms from the shell

`quilt set` takes the room's exact name (case-insensitive) and at least one of `--mode`,
`--heat`, `--cool` or `--fan`. Setpoints are in °C.

```bash
# Cool the living room to 22°C
quilt set "Living Room" --mode COOL --cool 22

# Auto with a heating/cooling range
quilt set "Bedroom" --mode AUTO --heat 19 --cool 24

# Turn a room off
quilt set "Guest Room" --mode STANDBY

# Change the fan speed on every indoor unit in the room
quilt set "Office" --fan QUIET
```

Modes: `COOL`, `HEAT`, `AUTO`, `FAN`, `DRY`, `STANDBY`. Fan speeds: `AUTO`, `QUIET`, `LOW`,
`MEDIUM`, `HIGH`, `BLAST`.

---

## Write a bash script to set all rooms to a setpoint

```bash
#!/usr/bin/env bash
set -euo pipefail

SETPOINT="${1:-22}"

quilt info --output json \
  | jq -r '.spaces[] | select(.is_room) | .name' \
  | while IFS= read -r room; do
      echo "Setting $room to ${SETPOINT}°C"
      quilt set "$room" --mode COOL --cool "$SETPOINT"
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
    ["quilt", "info", "--output", "json"],
    capture_output=True,
    text=True,
    check=True,
)
data = json.loads(result.stdout)

for space in data["spaces"]:
    if not space["is_room"]:
        continue
    temp = space["state"]["ambient_temperature_c"]
    mode = space["controls"]["hvac_mode"]
    temp_str = f"{temp:.1f}°C" if temp is not None else "unknown"
    print(f"  {space['name']:<20} {mode:<8} {temp_str}")
```

---

## Set up a cron job for nightly standby

Put every room in STANDBY at midnight with a small script:

```bash
#!/usr/bin/env bash
# /usr/local/bin/quilt-standby
set -euo pipefail
quilt info --output json \
  | jq -r '.spaces[] | select(.is_room) | .name' \
  | while IFS= read -r room; do
      quilt set "$room" --mode STANDBY
    done
```

```cron
0 0 * * * QUILT_EMAIL=you@example.com /usr/local/bin/quilt-standby
```

---

## Write snapshot metrics to a Prometheus textfile

```bash
#!/usr/bin/env bash
# Runs every minute via cron
OUTFILE="/var/lib/node_exporter/quilt.prom"
TMPFILE="${OUTFILE}.tmp"

# The program goes in a variable: `python3 - <<EOF` would read the script from
# stdin and lose the piped JSON.
read -r -d '' PROG << 'PYEOF' || true
import sys, json
data = json.load(sys.stdin)
for space in data["spaces"]:
    if not space["is_room"]:
        continue
    name = space["name"].lower().replace(" ", "_")
    mode = space["controls"]["hvac_mode"]
    temp = space["state"]["ambient_temperature_c"]
    print(f'quilt_room_temp_celsius{{room="{name}"}} {"NaN" if temp is None else temp}')
    print(f'quilt_room_mode{{room="{name}",mode="{mode}"}} 1')
for dial in data["controllers"]:
    room = (dial["space_name"] or dial["id"]).lower().replace(" ", "_")
    print(f'quilt_dial_presence{{room="{room}"}} {int(bool(dial["presence_detected"]))}')
    print(f'quilt_dial_online{{room="{room}"}} {int(dial["is_online"])}')
PYEOF

quilt info --output json | python3 -c "$PROG" > "$TMPFILE"
mv "$TMPFILE" "$OUTFILE"
```

---

## Query energy usage

```bash
# Today, per room (kWh)
quilt energy --period day

# This week or this month
quilt energy --period week
quilt energy --period month
```

`energy` prints a human-readable table only. For per-bucket data in scripts, use
`QuiltClient.get_energy()` from Python.

---

## CLI exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Any error: authentication failure (re-run `quilt login`), room not found, invalid mode or fan speed, nothing to update, or a gRPC/network failure. The message is printed in red. |
| 2 | Invalid command-line usage (unknown option, out-of-range setpoint), reported by the argument parser |
