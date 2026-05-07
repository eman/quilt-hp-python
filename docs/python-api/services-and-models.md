# Service and model reference

This page documents practical behavior of implemented service wrappers and domain models.

## Service wrappers

### `HomeDatastoreService`

Primary snapshot + mutation service:

- snapshot: `get_system()`
- space: `update_space()`, `update_space_settings()`
- indoor unit: `update_indoor_unit()`, `update_indoor_unit_settings()`
- comfort preset: `update_comfort_setting()`
- schedules: create/update/delete day/week
- location schedule execution: `update_location_schedule_execution()`

Important behavior:

- Space AUTO mode enforces `cool - heat >= 2.5°C`.
- Explicit STANDBY clears comfort association to produce true OFF behavior.
- Sparse update diffs echo required fields to avoid server-side clearing of omitted fields.

Errors:

- wraps gRPC errors as `QuiltError`.
- `get_system()` maps NOT_FOUND to `QuiltNotFoundError`.

### `SystemInformationService`

- `list_systems()` returns `SystemInfo`.
- `get_energy_metrics(system_id, start, end)` returns hourly `SpaceEnergyMetrics`.

### `UserService`

- `get_current_user()` returns `User` dataclass.
- `update_current_user(...)` updates first/last name and optional phone.
- `get_user_attributes()` returns `UserAttributes`.
- `patch_user_attributes(...)` updates `UserAttributes` values.

### `NotifierStream`

Bidirectional streaming manager with:

- callback registration per entity type
- dynamic subscribe/unsubscribe
- reconnect and exponential backoff
- optional auth refresh callback
- `run_forever()` (blocking) and `start()/stop()` (background)

Entity callbacks:

- space, indoor unit, outdoor unit, controller, qsm, remote sensor,
  controller remote sensor, software update info, error.

## Model reference (practical)

### `SystemSnapshot`

Container for full state collections and helpers:

- `rooms`: leaf spaces only
- `primary_location`: first location
- `space_by_name(name)`
- `stream_topics()` topic strings for all known entities
- merge helpers for stream diffs:
  `apply_space`, `apply_indoor_unit`, `apply_outdoor_unit`,
  `apply_controller`, `apply_qsm`, `apply_remote_sensor`,
  `apply_controller_remote_sensor`

Why merge helpers matter:

- stream diffs are sparse proto updates; absent fields otherwise look like defaults.
- helper methods preserve last-known non-default values.

### Space models

- `SpaceSettings`: occupancy/safety/timeout config.
- `SpaceControls`: HVAC mode and setpoints with `display_setpoint_str()`.
- `SpaceState`: ambient + active HVAC state.
- `Space`: room/home entity with derived flags:
  - `is_room`
  - `is_away`
  - `is_off`

### Indoor unit models

`IndoorUnit` includes controls, settings, read-only state, optional performance and occupancy blocks.

Key convenience properties:

- `is_online` (5-minute state-update threshold)
- `led_on` (online-gated)
- `effective_occupancy_state` (online-gated)

### Controller, outdoor unit, QSM

- `Controller`: dial metadata, calibrated temperature, Wi-Fi details, online logic.
- `OutdoorUnit`: compressor-side data + optional hardware identity fields.
- `QuiltSmartModule`: embedded module sensors and three Wi-Fi interfaces (`hosted`, `ap`, `p2p`).

### Sensors

- `RemoteSensor`: standalone BLE sensor linked to IDU.
- `ControllerRemoteSensor`: Dial-hosted sensor entity linked to controller.

### Comfort/schedule/energy/update models

- `ComfortSetting`: named mode/setpoint/fan preset.
- `ScheduleDay`, `ScheduleEvent`, `ScheduleWeek`, `ScheduleWeekDay`.
- `EnergyBucket`, `SpaceEnergyMetrics` (`total_kwh` helper).
- `SoftwareUpdateInfo`: raw update state/status/version/progress fields.

### Enums used in control APIs

Most control methods use typed enums from `quilt_hp.models.enums`, especially:

- `HVACMode`, `FanSpeed`, `LouverMode`
- occupancy and comfort enums (`OccupancyMode`, `ComfortSettingType`, etc.)
