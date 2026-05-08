# HDS entities and field semantics

The Home Datastore (HDS) manages all entities that make up a Quilt installation. This page documents the main entity types, their important fields, how they map to Python model classes, and any behavioural semantics that are not obvious from field names alone.

## Space

A Space is a zone within a Quilt installation, typically a room. Spaces are hierarchical: there is a root "home" space (no parent) and leaf room spaces (each with a `parent_space_id`). Most operations work with leaf spaces only. `Space.is_room` returns `True` for leaf spaces.

**Python model**: `quilt_hp.models.space.Space`

### Fields

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | `str` | Unique object ID (UUID) |
| `system_id` | `str` | System this space belongs to |
| `name` | `str` | Display name (e.g. "Living Room") |
| `parent_space_id` | `str \| None` | Parent space ID; `None` for the root home space |
| `controls.hvac_mode` | `HVACMode` | The mode the user has set: `STANDBY`, `COOL`, `HEAT`, `AUTO`, `FAN` |
| `controls.heating_setpoint_c` | `float` | Heating setpoint in °C |
| `controls.cooling_setpoint_c` | `float` | Cooling setpoint in °C |
| `controls.comfort_setting_id` | `str` | ID of the currently active comfort preset |
| `controls.comfort_setting_override` | `ComfortSettingOverride` | Why the active comfort setting differs from the schedule |
| `state.ambient_temperature_c` | `float \| None` | Current measured temperature; `None` if no recent reading |
| `state.hvac_state` | `HVACState` | What the system is actually doing (may differ from `hvac_mode` if e.g. deferred) |
| `settings.occupancy_mode` | `OccupancyMode` | Whether auto-away/return is enabled |
| `settings.unoccupied_timeout_s` | `float` | Seconds of no-presence before auto-away (default ~1200 s = 20 min) |
| `settings.occupied_timeout_s` | `float` | Seconds of presence before auto-return (default ~180 s = 3 min) |
| `settings.safety_heating` | `SafetyHeatingMode` | Freeze-protection mode |

### Behavioural semantics

**STANDBY vs. AWAY**: Setting `hvac_mode=STANDBY` via `UpdateSpace` puts the room into plain off mode. It stays off regardless of occupancy. This is implemented by clearing `comfort_setting_id` (sending an empty string) in the wire diff. In contrast, AWAY mode is managed by the server's occupancy logic and preserves the active comfort setting ID. `Space.is_off` returns `True` for explicit STANDBY, `Space.is_away` returns `True` when the AWAY comfort preset is active.

**UpdateSpace requires echoing settings fields**: When calling `UpdateSpace` with a `settings` block, all existing settings fields must be echoed back (name, timezone, occupancy mode, timeouts, safety heating). The server replaces the entire `settings` sub-message, so absent fields are cleared to their proto3 defaults. This is why `HomeDatastoreService.update_space_settings()` reads all current settings from the `snapshot_space` parameter before building the diff.

**AUTO mode gap enforcement**: When mode is `AUTO`, the library enforces a minimum 2.5°C gap between heating and cooling setpoints: `cool = max(cool, heat + 2.5)`. This matches the Quilt mobile app behaviour.

**Temperature setpoint routing**: The wire `temperature_setpoint_c` field is the "mode-relevant" setpoint. It is the heating setpoint when mode is HEAT and the cooling setpoint otherwise. Both `heating_temperature_setpoint_c` and `cooling_temperature_setpoint_c` are always sent.

---

## IndoorUnit

An IndoorUnit is a wall-mounted mini-split head unit (7⅞ in tall × 38¼ in wide × 8³⁄₁₆ in deep). It is one of the slimmest heads on the market. Each IDU is rated at 9,000 BTU and operates between 27–48 dBA. It belongs to exactly one Space and one OutdoorUnit. IDUs contain a QuiltSmartModule (the connectivity and radar hardware) and have multiple sub-messages covering controls, state, settings, performance metrics, presence detection, and fault conditions.

**Python model**: `quilt_hp.models.indoor_unit.IndoorUnit`

### Fields

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | `str` | Unique object ID |
| `space_id` | `str` | Space this IDU serves |
| `outdoor_unit_id` | `str \| None` | Connected outdoor unit |
| `qsm_id` | `str \| None` | Embedded QuiltSmartModule ID |
| `controls.fan_speed` | `FanSpeed` | `AUTO`, `QUIET`, `LOW`, `MEDIUM`, `HIGH`, `BLAST` |
| `controls.louver_mode` | `LouverMode` | `CLOSED`, `SWEEP`, `FIXED`, `AUTO` |
| `controls.louver_fixed_position` | `float` | Position 0.0–1.0 when `louver_mode=FIXED` |
| `controls.led_color_code` | `int` | RGBW packed colour (0 = black/off) |
| `controls.led_brightness` | `float` | Brightness 0.0–1.0 |
| `controls.led_state` | `LightState` | Explicit `ON`/`OFF`/`UNSPECIFIED` |
| `state.ambient_temperature_c` | `float` | Temperature measured at the IDU |
| `state.ambient_humidity_percent` | `float` | Relative humidity at the IDU |
| `state.updated_at` | `datetime \| None` | Timestamp of last state update; used for online detection |
| `settings.presence_fence_left_m` | `float` | Left boundary of presence detection zone in metres (0 = unconfigured) |

### Online detection

`IndoorUnit.is_online` returns `True` if the IDU sent a state update within the last 5 minutes (matches the `_ONLINE_THRESHOLD_MINUTES = 5` constant). An offline IDU's controls data is stale. `IndoorUnit.led_on` applies the online gate: it returns `False` for offline IDUs regardless of the LED color/brightness values.

### LED state semantics

LED state can be expressed two ways depending on whether the `mobile_led_scheduling_enabled` Statsig feature gate is active:

- **Explicit state** (`led_state = ON` or `OFF`): The server preserves brightness when the LED is turned off. So `led_brightness > 0` does not mean the LED is on.
- **Legacy brightness-based** (`led_state = UNSPECIFIED`): LED is considered on when `led_color_code != 0` AND `led_brightness > 0`.

`IndoorUnitControls.light_on` handles both cases. Always use `idu.led_on` (which also applies the online gate) rather than checking brightness directly.

### FanSpeed wire encoding

`FanSpeed` maps to two wire fields: `fan_speed_mode` (1=AUTO, 2=SETPOINT) and `fan_speed_percent`. The `FanSpeed.to_wire()` method returns the pair; `FanSpeed.from_wire()` decodes it. The mapping:

| FanSpeed | fan_speed_mode | fan_speed_percent |
| --- | --- | --- |
| AUTO | 1 | 0.0 |
| QUIET | 2 | 0.20 |
| LOW | 2 | 0.40 |
| MEDIUM | 2 | 0.60 |
| HIGH | 2 | 0.80 |
| BLAST | 2 | 1.00 |

---

## OutdoorUnit

The variable-speed compressor unit that provides heating and cooling capacity to all connected IDUs. Quilt sells two configurations: a 2-zone model (`QO1-M2Z18-NC-NA`, up to 18,000 BTU/h heating) and a 3-zone model (`QO1-M3Z27-NC-NA`, larger capacity). Both use R32 refrigerant and can operate down to -13°F while maintaining about 90% capacity. Hardware information (model SKU, serial number, firmware) comes from the `outdoor_unit_hardware` lookup map in the snapshot proto. It is not embedded in the main `outdoor_units` list. `SystemSnapshot.from_proto()` resolves this by building a hardware map.

**Python model**: `quilt_hp.models.outdoor_unit.OutdoorUnit`

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | `str` | Unique object ID |
| `space_id` | `str` | Associated space (home-level space) |
| `model_sku` | `str \| None` | Hardware model number (e.g. `QO1-M2Z18-NC-NA`) |
| `serial_number` | `str \| None` | Unit serial number |
| `firmware_version` | `str \| None` | Current firmware version string |
| `firmware_update_info_id` | `str \| None` | ID of pending firmware update entity, if any |
| `performance_data.compressor_frequency_hz` | `float \| None` | Live compressor speed in Hz |
| `performance_data.ambient_temperature_c` | `float \| None` | Outdoor ambient temperature |
| `performance_data.coil_temperature_c` | `float \| None` | Refrigerant coil temperature |

---

## Controller

The Quilt Dial is a compact circular thermostat (58 mm diameter) that can be wall-mounted or placed on a tabletop. It has a high-res OLED touchscreen, a rotary dial, and built-in sensors for ambient temperature, motion, and proximity. Each Controller is associated with one Space and reports its own ambient temperature independently of the IDU. The Dial is also the primary local control surface for room-by-room and whole-home adjustments.

**Python model**: `quilt_hp.models.controller.Controller`

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | `str` | Unique object ID |
| `space_id` | `str` | Space this Dial controls |
| `name` | `str` | Display name |
| `ambient_temperature_c` | `float` | Temperature measured by the Dial's built-in sensor |
| `raw_thermistor_c` | `float` | Raw uncalibrated thermistor reading |
| `remote_sensor_mode` | `HvacControllerType` | How the Dial's temperature reading influences the space setpoint |
| `model_sku` | `str \| None` | Hardware model identifier |
| `serial_number` | `str \| None` | Unit serial number |
| `software_update_info_id` | `str \| None` | Pending software update entity ID |
| `firmware_update_info_id` | `str \| None` | Pending firmware update entity ID |

---

## QuiltSmartModule (QSM)

The intelligent compute and sensor module embedded inside each Indoor Unit. It runs the on-device occupancy logic, hosts the millimeter-wave radar presence sensor, and handles over-the-air firmware updates. The QSM exposes raw sensor readings that the server-side occupancy algorithm uses to decide when a room transitions between occupied and unoccupied states.

**Python model**: `quilt_hp.models.qsm.QuiltSmartModule`

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | `str` | Unique object ID |
| `software_update_info_id` | `str \| None` | Pending software update entity ID |
| `firmware_update_info_id` | `str \| None` | Pending firmware update entity ID |
| `sensors.phase_detected_raw` | `float \| None` | Raw phase-detection reading from the radar (motion indication) |
| `sensors.target_detected_raw` | `float \| None` | Raw target-detection reading (presence indication, detects stationary people) |
| `sensors.als_illuminance_raw` | `float \| None` | Raw ambient light sensor reading |
| `sensors.accel_x_raw` | `float \| None` | Accelerometer X axis (used to detect unit orientation/mounting) |
| `sensors.accel_y_raw` | `float \| None` | Accelerometer Y axis |
| `sensors.accel_z_raw` | `float \| None` | Accelerometer Z axis |

The radar distinguishes between `phase_detected` (movement) and `target_detected` (presence including stationary humans up to 15 ft / 4.6 m away). That lets Auto-Away detect a person sitting still and reading a book, unlike PIR-based sensors that only respond to movement.

---

## RemoteSensor and ControllerRemoteSensor

Wireless temperature/humidity sensors. `RemoteSensor` is a standalone sensor attached to an IDU; `ControllerRemoteSensor` is the temperature/humidity sensor embedded in the Dial itself.

Both report:
- `ambient_temperature_c`
- `humidity_percent`
- `battery_level_percent`
- `signal_level_dbm`
- `control_mode`: Whether this sensor is used as the zone temperature source

**Python models**: `quilt_hp.models.sensor.RemoteSensor`, `ControllerRemoteSensor`

---

## ComfortSetting

A named comfort preset that can be assigned to a space or used in a schedule. Each preset defines a complete set of HVAC parameters. There are system-defined types (ACTIVE, SLEEP, AWAY, STANDBY) and user-defined CUSTOM presets.

**Python model**: `quilt_hp.models.comfort.ComfortSetting`

### Fields

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | `str` | Unique preset ID |
| `system_id` | `str` | System this preset belongs to |
| `space_id` | `str` | Space this preset is scoped to |
| `name` | `str` | Display name |
| `type` | `ComfortSettingType` | `ACTIVE`, `SLEEP`, `AWAY`, `STANDBY`, `CUSTOM` |
| `hvac_mode` | `HVACMode` | HVAC mode for this preset |
| `heating_setpoint_c` | `float` | Heating setpoint |
| `cooling_setpoint_c` | `float` | Cooling setpoint |
| `fan_speed` | `FanSpeed` | Fan speed |

---

## ScheduleDay

A schedule day program is a named set of time-based events that set comfort presets and HVAC behaviour throughout the day. Each event specifies a `start_s` (seconds since midnight), an optional `comfort_setting_id`, and explicit `hvac_mode`, `heating_temperature_setpoint_c`, `cooling_temperature_setpoint_c`.

**Python model**: `quilt_hp.models.schedule.ScheduleDay`

Fields of `ScheduleEvent`:
- `start_s`: Offset in seconds from midnight when this event starts.
- `comfort_setting_id`: The comfort preset to activate (can be empty for explicit setpoints).
- `hvac_mode`, `heating_setpoint_c`, `cooling_setpoint_c`: Direct setpoint override.
- `precondition`: Whether to pre-condition the space before the event time.

---

## ScheduleWeek

A schedule week assigns a `ScheduleDay` program to each day of the week. Each `ScheduleWeekDay` maps a `weekday` (enum: MON, TUE, WED, THU, FRI, SAT, SUN) to a `day_id` (the ID of a `ScheduleDay`).

**Python model**: `quilt_hp.models.schedule.ScheduleWeek`

---

## Location

A Location is the top-level container for a Quilt installation. It stores the timezone and the global schedule execution state. `Location.schedule_paused` is `True` when all schedules are paused via `UpdateLocation`. `SystemSnapshot.primary_location` returns the first (typically only) location.

**Python model**: `quilt_hp.models.system.Location`
