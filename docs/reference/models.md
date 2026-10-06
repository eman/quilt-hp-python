# Services and models

This page documents the lower-level service classes and all model dataclasses. Most application code interacts with `QuiltClient` directly; this page is the reference for code that needs to work with the raw service objects or inspect model fields in detail.

---

## Service classes

Service classes are instantiated by `QuiltClient` and stored as `self.hds`, `self.system`, `self.user`, and `self.notifier`. You can also construct them directly when writing tests or custom transport code.

### `HomeDatastoreService`

```python
from quilt_hp.services.hds import HomeDatastoreService

service = HomeDatastoreService(channel)
```

`HomeDatastoreService` wraps the `HomeDatastoreService` gRPC stub. All methods are async and raise `QuiltError` subclasses on failure.

| Method | Description |
|--------|-------------|
| `get_snapshot(system_id)` | Fetches a complete `SystemSnapshot` for the given system. |
| `update_space(space_proto)` | Sends an `UpdateSpace` request with the given space proto. Used by `QuiltClient.set_space()`. |
| `list_comfort_settings(system_id)` | Lists a system's comfort settings (server-side filter on `header.system_id`). |
| `update_comfort_setting(cs_proto)` | Updates a comfort setting proto. |
| `create_schedule_day(...)` | Creates a new schedule day program. |
| `update_schedule_day(...)` | Updates an existing schedule day. |
| `delete_schedule_day(schedule_day_id)` | Deletes a schedule day by ID. |
| `create_schedule_week(...)` | Creates a new schedule week. |
| `update_schedule_week(...)` | Updates a schedule week's day assignments. |
| `delete_schedule_week(schedule_week_id)` | Deletes a schedule week by ID. |
| `set_schedule_execution(location_id, paused)` | Pauses or resumes all schedules for a location. |

**Caveat on updates**: The `UpdateSpace` request uses a `Space` proto field mask. All fields in the settings submessage must be populated because the server treats absent fields as "clear to default." `QuiltClient.set_space()` handles this by reading the current snapshot and echoing existing values for any fields you do not explicitly change.

### `SystemInformationService`

```python
from quilt_hp.services.system import SystemInformationService

service = SystemInformationService(channel)
```

| Method | Description |
|--------|-------------|
| `list_systems()` | Lists all `SystemInfo` objects visible to the authenticated user. |
| `get_energy_metrics(system_id, start_ts, end_ts)` | Returns hourly energy data across all spaces for the given time range. |

### `UserService`

```python
from quilt_hp.services.user import UserService

service = UserService(channel)
```

| Method | Description |
|--------|-------------|
| `get_current_user()` | Returns the `User` proto for the authenticated user. |
| `update_current_user(first_name, last_name, phone_number)` | Updates the user profile. |
| `get_user_attributes()` | Returns `UserAttributes` including declared user type. |
| `patch_user_attributes(declared_user_type)` | Updates user attributes. |

### `CommandService`

```python
from quilt_hp.services.command import CommandService

service = CommandService(channel)
```

Wraps the `CommandService` gRPC stub (new in the Quilt app versionCode 255).
Registered in the cloud stub only — there is no local endpoint.

| Method | Description |
|--------|-------------|
| `request_fast_updates(system_id, reason=FastUpdateReason.USER_ACTIVITY)` | Asks the cloud to raise the telemetry cadence for a system. Returns `None`; the effect is a faster stream of updates over `NotifierStream`. |

### `NotifierStream`

```python
from quilt_hp import NotifierStream  # also importable from quilt_hp.services.streaming

# metadata_provider returns gRPC call metadata (e.g. auth headers).
# Obtain a token from your QuiltClient or token store.
def get_metadata() -> list[tuple[str, str]]:
    return [("authorization", f"Bearer {token}")]

stream = NotifierStream.create(
    channel,
    topics,
    metadata_provider=get_metadata,
    authenticate=client.refresh_token,
    max_reconnects=-1,
    reconnect_delay_s=1.0,
)
```

See [Streaming protocol behavior](../explanation/streaming-protocol.md) for the full state machine, event types, and reconnect behavior.

Callback registration methods (each returns an *unsubscribe* callable —
call it to detach the callback without stopping the stream):

```python
unsub = stream.on_space_update(callback)
stream.on_indoor_unit_update(callback)
stream.on_outdoor_unit_update(callback)
stream.on_controller_update(callback)
stream.on_qsm_update(callback)
stream.on_remote_sensor_update(callback)
stream.on_controller_remote_sensor_update(callback)
stream.on_software_update_info(callback)
stream.on_error(callback)       # fatal stream errors
stream.on_connected(callback)   # fired on every successful (re)connect
unsub()                         # detach the space callback
```

`on_connected` fires on every successful connect and reconnect. Events
published while disconnected are lost — use it to re-fetch a snapshot and
close the gap.

Lifecycle methods:

```python
await stream.start()
await stream.run_forever()
await stream.subscribe(["hds/space/<uuid>"])
await stream.unsubscribe(["hds/space/<uuid>"])
await stream.stop()
stream.error
```

---

## Model dataclasses

All models are `dataclass` instances populated from proto fields by `from_proto()` class methods. They are immutable in practice (no `frozen=True`, but mutation is undefined behavior).

### `SystemSnapshot`

```python
@dataclass
class SystemSnapshot:
    spaces: list[Space]
    indoor_units: list[IndoorUnit]
    outdoor_units: list[OutdoorUnit]
    controllers: list[Controller]
    quilt_smart_modules: list[QuiltSmartModule]
    comfort_settings: list[ComfortSetting]
    schedule_weeks: list[ScheduleWeek]
    schedule_days: list[ScheduleDay]
    remote_sensors: list[RemoteSensor]
    controller_remote_sensors: list[ControllerRemoteSensor]
    software_update_infos: list[SoftwareUpdateInfo]
    locations: list[Location]
    timezone: str | None
    version: int | None  # last configuration write, epoch ns
```

`SystemSnapshot` is the root object returned by `get_snapshot()`. Child collections are stored as lists, not dicts. Look up objects by iterating, with helpers like `space_by_name()`, or by merging stream diffs in place with the `apply_*()` methods.

`version` (and `version_at`, the same instant as a UTC `datetime`) advances whenever controls,
settings or configuration are written, including automatic writes such as auto-away switching a
comfort setting. Telemetry does not advance it. Compare it with `client.get_system_version()` to
tell whether a snapshot's configuration is stale without refetching the whole snapshot.

Useful helper properties and methods:

```python
snapshot.rooms                      # → list[Space]  leaf spaces only
snapshot.primary_location           # → Location | None
snapshot.space_by_name("Bedroom")  # → Space | None
snapshot.comfort_settings_for_space(space)
snapshot.away_comfort_setting(space)
snapshot.stream_topics()            # → list[str]
```

The merge helpers update the matching list entry or append a new object when needed:

```python
snapshot.apply_space(space)
snapshot.apply_indoor_unit(idu)
snapshot.apply_outdoor_unit(odu)
snapshot.apply_controller(controller)
snapshot.apply_qsm(qsm)
snapshot.apply_remote_sensor(sensor)
snapshot.apply_controller_remote_sensor(sensor)
snapshot.apply_software_update_info(info)
```

---

### `Space`

```python
@dataclass
class Space:
    id: str
    system_id: str
    name: str
    parent_space_id: str | None
    settings: SpaceSettings
    controls: SpaceControls
    state: SpaceState
    active_comfort_setting_type: ComfortSettingType | None  # resolved from controls.comfort_setting_id
    occupancy: SpaceOccupancy | None  # room auto-away decision; see SpaceOccupancy
```

A single room or floor zone. `parent_space_id is None` for floor-level spaces; leaf rooms always have a parent.

`space.occupancy_state` is the room's auto-away decision (`OccupancyState.DETECTED` /
`UNDETECTED`), the value its away/return setback acts on, or `None` when the server hasn't
evaluated the space (the home's root space, or a room whose radar isn't reporting).

#### `SpaceOccupancy`

```python
@dataclass
class SpaceOccupancy:
    occupancy_state: OccupancyState
    updated_at: datetime | None
```

#### `SpaceControls`

```python
@dataclass
class SpaceControls:
    hvac_mode: HVACMode
    temperature_setpoint_c: float
    cooling_setpoint_c: float
    heating_setpoint_c: float
    comfort_setting_id: str
    comfort_setting_override: ComfortSettingOverride
    boost_mode: BoostMode
```

The writable HVAC control state. `comfort_setting_id` uses an empty-string sentinel when the space is in manual control mode. Setting `hvac_mode=STANDBY` clears the linked comfort setting.

#### `SpaceSettings`

```python
@dataclass
class SpaceSettings:
    name: str
    timezone: str
    occupancy_mode: OccupancyMode
    occupied_timeout_s: float
    unoccupied_timeout_s: float
    safety_heating: SafetyHeatingMode
    hvac_controller_type: HvacControllerType
```

Automation and safety configuration for the space.

#### `SpaceState`

```python
@dataclass
class SpaceState:
    ambient_temperature_c: float | None
    hvac_state: HVACState
    setpoint_c: float | None
    comfort_setting_id: str
```

Read-only live state derived from sensor telemetry and current control state.

---

### `IndoorUnit`

```python
@dataclass
class IndoorUnit:
    id: str
    system_id: str
    space_id: str
    outdoor_unit_id: str | None
    hardware_id: str
    qsm_id: str | None
    settings: IndoorUnitSettings
    controls: IndoorUnitControls
    state: IndoorUnitState
    hvac_inputs: IndoorUnitHvacInputs | None
    conditions: IndoorUnitConditions | None
    performance_data: IndoorUnitPerformanceData | None
    performance_metrics: IndoorUnitPerformanceMetrics | None
    presence: IndoorUnitPresence | None
    occupancy: IndoorUnitOccupancy | None  # this unit's auto-away occupancy; see below
    firmware_update_info_id: str | None
    commands: IndoorUnitCommands | None
    model_sku: str | None
    serial_number: str | None
    firmware_version: str | None
    climate: IndoorUnitClimate | None  # dew point etc.; see IndoorUnitClimate
    test_state: IndoorUnitTestState | None  # health check / commissioning; see IndoorUnitTestState
```

#### `IndoorUnitControls`

```python
@dataclass
class IndoorUnitControls:
    fan_speed: FanSpeed
    louver_mode: LouverMode
    louver_fixed_position: float  # 0.0–1.0 when FIXED
    led_color_code: int  # RGBW packed int32
    led_brightness: float  # 0.0–1.0
    led_animation: LedAnimation
    led_state: LightState
    fan_speed_mode_raw: int
    fan_speed_percent_raw: float
```

#### `IndoorUnitSettings`

```python
@dataclass
class IndoorUnitSettings:
    name: str
    description: str
    light_brightness_default_percent: float
    presence_fence_left_m: float  # 0 = unconfigured / max range
    presence_fence_right_m: float
    presence_fence_forward_m: float
    radar_sensor_distance_from_floor_m: float
```

Radar presence detection calibration. Fence values of `0.0` mean unconfigured (uses hardware maximum range).

#### `IndoorUnitState`

```python
@dataclass
class IndoorUnitState:
    hvac_mode: HVACMode
    hvac_state: HVACState
    ambient_temperature_c: float
    ambient_humidity_percent: float
    fan_speed_rpm: float
    fan_speed_setpoint_rpm: float
    presence_detection_level: float
    temperature_setpoint_c: float
    light_brightness_percent: float
    inlet_temperature_c: float
    outlet_temperature_c: float
    calculated_ambient_temperature_c: float
    louver_angle_up_down_degrees: float
    updated_at: datetime | None
    test_mode: IndoorUnitTestMode  # see IndoorUnit.effective_test_mode
```

`IndoorUnit.is_online` is computed locally from `state.updated_at`
(`datetime.now(UTC) - updated_at < timedelta(minutes=5)`), and `IndoorUnit.led_on` returns `False`
whenever `is_online` is `False`, even if `led_color_code` is non-zero.

#### `IndoorUnitPerformanceMetrics`

```python
@dataclass
class IndoorUnitPerformanceMetrics:
    capacity_w: float
    coefficient_of_performance: float
    hvac_power_w: float
    led_power_w: float
    hvac_mode: HVACMode
    hvac_state: HVACState
    measurement_duration_s: float
    energy_total_j: float
    hvac_energy_j: float
    led_energy_j: float
    odu_usage_fraction: float  # share of the outdoor unit attributed to this unit, 0.0–1.0
```

`odu_usage_fraction` apportions an outdoor unit across the indoor units it serves; in standby it
is an even split (0.5 / 0.5 for two units, 1.0 for one). `capacity_w` and
`coefficient_of_performance` are 0 unless the unit is actively heating or cooling.

#### `IndoorUnitClimate` and `IndoorUnitTestState`

```python
@dataclass
class IndoorUnitClimate:
    is_valid: bool
    inlet_dew_point_c: float
    calculated_ambient_temperature_c: float
    updated_at: datetime | None

@dataclass
class IndoorUnitTestState:
    test_mode: IndoorUnitTestMode            # INACTIVE in normal operation
    test_coordination: IndoorUnitTestCoordination
    test_phase: IndoorUnitTestPhase
    updated_at: datetime | None
```

`idu.dew_point_c` is the inlet dew point, or `None` when the climate reading is absent or flagged
invalid; the unit updates it every few seconds. `idu.effective_test_mode` is
the mode from whichever of `test_state` and `state` was updated more recently (the server reports
it in both, and a snapshot merged from sparse diffs can hold a stale copy of either); a source
reporting `UNSPECIFIED` is ignored. `idu.is_under_test` is `True` while that mode is anything but `INACTIVE` (health
check, commissioning or another test), during which the unit's behaviour is driven by the test
rather than the room's controls.

#### `IndoorUnitPresence` and `IndoorUnitOccupancy` — realtime vs derived

```python
@dataclass
class IndoorUnitPresence:
    sensor0_presence: Presence  # radar detection channel 0
    sensor1_presence: Presence  # radar detection channel 1

@dataclass
class IndoorUnitOccupancy:
    occupancy_state: int  # OccupancyState proto value
```

Occupancy data comes in three tiers — don't treat them as interchangeable:

| Tier | Accessor | Latency | Meaning |
|---|---|---|---|
| Raw radar channels | `idu.presence.sensor0_presence` / `sensor1_presence` | seconds | The two detection channels of the IDU's single mm-wave radar. Channel semantics are unconfirmed and they move in lockstep in practice — avoid labeling them "motion" vs "presence". |
| Realtime presence | `idu.presence_detected` | seconds | OR of both channels — the value the vendor app uses. `True`/`False`, or `None` when offline or unreported. |
| Room occupancy | `space.occupancy_state` | minutes | The space's own auto-away decision, which its setback acts on. In live data it matches the room's IDU value. |
| Derived occupancy | `idu.effective_occupancy_state` | minutes | The server's auto-away decision: ~3 min of sustained presence to set, ~20 min of absence to clear (configurable via `SpaceSettings.occupied_timeout_s` / `unoccupied_timeout_s`). |

Use `presence_detected` for "is someone in the room right now" and `effective_occupancy_state` for "does Quilt consider the room occupied for away/return setback". Both return `None` for offline IDUs so stale data is never presented as current.

---

### `OutdoorUnit`

```python
@dataclass
class OutdoorUnit:
    id: str
    system_id: str
    space_id: str
    hvac_state: HVACState
    model_sku: str | None
    serial_number: str | None
    firmware_version: str | None
    firmware_update_info_id: str | None
    performance_data: OutdoorUnitPerformanceData | None
```

#### `OutdoorUnitPerformanceData`

```python
@dataclass
class OutdoorUnitPerformanceData:
    measurement_interval_s: float
    energy_measurement_j: float
    compressor_frequency_hz: float
    ambient_temperature_c: float
    coil_temperature_c: float
    exhaust_temperature_c: float
    high_pressure_kpa: float
    low_pressure_kpa: float
```

---

### `Controller`

```python
@dataclass
class Controller:
    id: str
    system_id: str
    space_id: str
    name: str
    raw_thermistor_c: float | None  # None when no state reading available
    pcb_temperature_a_c: float | None
    pcb_temperature_b_c: float | None
    calibrated_ambient_c: float | None  # exposed as ambient_temperature_c
    wifi_ssid: str | None
    wifi_ip: str | None
    wifi_signal_dbm: int | None
    wifi_freq_mhz: int | None
    wifi_bssid: str | None
    wifi_last_seen: datetime | None
    ap_wifi: WifiInfo | None
    p2p_wifi: WifiInfo | None
    remote_sensor_mode: RemoteSensorControlMode
    software_update_info_id: str | None
    firmware_update_info_id: str | None
    serial_number: str | None
    model_sku: str | None
    firmware_version: str | None
    state_updated_at: datetime | None
    local_comms_health: LocalCommsHealthStatus
    local_comms_visible_devices: int | None
    local_comms_expected_devices: int | None
    local_comms_reason: LocalCommsHealthReason
    local_comms_last_session_change: datetime | None
    view_state: ControllerViewState  # SLEEP, GLANCE, ACTIVE, INTERACTING
    screen_brightness: float | None  # 0.0–1.0
    radar_target_detected: bool | None  # the Dial's own mmWave radar
    radar_phase_detected: bool | None
    ambient_light_lux: float | None
    orientation: ControllerOrientation  # VERTICAL (wall) or HORIZONTAL (flat)
    humidity_percent: float | None  # SHT4x; None on Dials that don't report it
    power_w: float | None
    main_board_temperature_c: float | None
    power_board_temperature_c: float | None
    accelerometer_raw: tuple[int, int, int] | None
    # display, radar and light telemetry (None / UNSPECIFIED when no state reading)
```

Useful properties: `ambient_temperature_c` (→ `calibrated_ambient_c`, `None`
when no state reading is available), `wifi_band`, `is_online` (state reported within
the last 5 minutes; online Dials report about every 10 s), `display_on` (`False` while
asleep, `None` when unknown) and `presence_detected` (the Dial radar sees someone; this
is independent of the indoor unit's radar).

---

### `RemoteSensor`

```python
@dataclass
class RemoteSensor:
    id: str
    indoor_unit_id: str
    mac: str | None
    ambient_temperature_c: float | None
    humidity_percent: float | None
    battery_level_percent: float | None
    signal_level_dbm: int | None
    control_mode: RemoteSensorControlMode
```

---

### `ComfortSetting`

```python
@dataclass
class ComfortSetting:
    id: str
    system_id: str
    space_id: str
    name: str
    type: ComfortSettingType
    hvac_mode: HVACMode
    heating_setpoint_c: float
    cooling_setpoint_c: float
    fan_speed: FanSpeed
    louver_mode: LouverMode
    louver_fixed_position: float
    fan_speed_mode_raw: int
    fan_speed_percent_raw: float
```

A named HVAC preset. Spaces reference comfort settings by `controls.comfort_setting_id`.

---

### `ScheduleDay`

```python
@dataclass
class ScheduleDay:
    id: str
    name: str
    space_id: str
    events: list[ScheduleEvent]
```

#### `ScheduleEvent`

```python
@dataclass
class ScheduleEvent:
    start_s: int  # seconds from midnight
    comfort_setting_id: str
    hvac_mode: HVACMode
    heating_setpoint_c: float
    cooling_setpoint_c: float
    precondition: bool
```

---

### `ScheduleWeek`

```python
@dataclass
class ScheduleWeek:
    id: str
    space_id: str
    days: list[ScheduleWeekDay]
```

#### `ScheduleWeekDay`

```python
@dataclass
class ScheduleWeekDay:
    weekday: int  # 1 = Monday, 7 = Sunday
    day_id: str
```

---

### `SystemInfo`

```python
@dataclass
class SystemInfo:
    id: str
    name: str
    timezone: str
```

Returned by `list_systems()`.

---

### `Location`

```python
@dataclass
class Location:
    id: str
    name: str
    system_id: str
    timezone: str
    schedule_paused: bool
```

Location metadata embedded in `SystemSnapshot`.

---

### `ControllerRemoteSensor`

```python
@dataclass
class ControllerRemoteSensor:
    id: str
    controller_id: str
    mac: str | None
    ambient_temperature_c: float | None
    humidity_percent: float | None
    battery_level_percent: float | None
    signal_level_dbm: int | None
    control_mode: RemoteSensorControlMode
```

Temperature, humidity, battery, and signal data exposed by a controller when its remote-sensor mode is enabled.

---

### `EnergyBucket`

```python
@dataclass
class EnergyBucket:
    start_time: datetime
    energy_kwh: float
    status: MetricBucketStatus
```

One hourly energy measurement bucket. Use `has_missing_energy_value` or `energy_kwh_or_none` to handle NaN sentinel values safely (a `None` or non-float `energy_kwh` is also treated as missing).

---

### `SpaceEnergyMetrics`

```python
@dataclass
class SpaceEnergyMetrics:
    space_id: str
    buckets: list[EnergyBucket]
```

Hourly energy history for one space. Convenience properties include `total_kwh` and `missing_bucket_count`.

---

### `SoftwareUpdateInfo`

```python
@dataclass
class SoftwareUpdateInfo:
    id: str
    state: int
    status: int
    current_version: str
    target_version: str
    current_progress: float
    total_progress: float
    progress_unit: int
```

Firmware/software update record associated with an indoor unit, outdoor unit, controller, or QSM.

---

### SystemDiagnostics

```python
@dataclass(slots=True)
class SystemDiagnostics:
    indoor_units: list[IndoorUnitDiagnostics]
    outdoor_units: list[OutdoorUnitDiagnostics]

    @property
    def active_faults(self) -> list[tuple[str, str]]: ...   # (indoor_unit_id, condition_name)
    @property
    def has_faults(self) -> bool: ...
```

The installer-style diagnostic view, assembled from data the cloud API already
returns. Obtain one from `SystemSnapshot.diagnostics()` or
`QuiltClient.get_diagnostics()`.

#### IndoorUnitDiagnostics

```python
@dataclass(slots=True)
class IndoorUnitDiagnostics:
    indoor_unit_id: str
    name: str
    space_id: str
    space_name: str
    online: bool
    hvac_state: HVACState
    active_faults: list[str]  # condition names currently ACTIVE
    conditions: dict[str, ConditionState]  # every condition → state (empty if none reported)
    coil_temperature_c: float | None
    gas_pipe_temperature_c: float | None
    liquid_pipe_temperature_c: float | None
    inlet_temperature_c: float | None
    outlet_temperature_c: float | None
    inlet_humidity_pct: float | None
    hvac_power_w: float | None
    inlet_dew_point_c: float | None
    odu_usage_fraction: float | None
    under_test: bool
    test: dict[str, str]
```

Per-indoor-unit diagnostics. The condition matrix includes the outdoor-unit and
refrigerant conditions surfaced through the IDU (`outdoor_unit_communication_error`,
`abnormal_outdoor_air_temperature`, `defrost_cycle`, `oil_return`, `coil_preheat`,
`modbus_communication_error`, `compressor_minimum_run_time`, …). Refrigerant temps
and power come from `IndoorUnit.performance_data` / `performance_metrics` and are
`None` when the unit reported none.

The underlying `IndoorUnitConditions` model exposes `active` (list of ACTIVE
condition names) and `states()` (dict of every condition → `ConditionState`).

#### OutdoorUnitDiagnostics

```python
@dataclass(slots=True)
class OutdoorUnitDiagnostics:
    outdoor_unit_id: str
    hvac_state: HVACState
    raw_sensors_available: bool
```

Per-outdoor-unit diagnostics. `raw_sensors_available` is `False` over the cloud
plane — the ODU's own `performance_data` (compressor Hz, suction/discharge
pressures, coil/discharge temps) is withheld from the mobile API; that telemetry
is only reachable on the local/hardware track. The refrigerant conditions and
pipe temperatures for this ODU's circuit are surfaced through its indoor units.

---

## Enum types

All enums live in `quilt_hp.models.enums` and subclass `IntEnum`, mirroring Quilt's wire values.

| Enum | Purpose | Representative values |
|------|---------|-----------------------|
| `HVACMode` | Requested operating mode | `STANDBY`, `COOL`, `HEAT`, `AUTO`, `FAN`, `FALLBACK_AUTO`, `FALLBACK_OFF` |
| `HVACState` | Actual running state | `STANDBY`, `COOL`, `HEAT`, `DRIFT`, `FAN` |
| `FanSpeed` | Indoor-unit fan speed preset | `AUTO`, `QUIET`, `LOW`, `MEDIUM`, `HIGH`, `BLAST` |
| `LouverMode` | Indoor-unit louver behavior | `CLOSED`, `SWEEP`, `FIXED`, `AUTO` |
| `LouverAngle` | Fixed louver angle preset | `ANGLE1`–`ANGLE5` |
| `LightPreset` | Built-in LED color presets | `DAYLIGHT`, `WARM`, `SUNSET`, `SKY` |
| `LedAnimation` | Indoor-unit LED animation mode | `NONE`, `SPARKLE_FADE`, `TWINKLE_FADE`, `DANCE`, `CHASE` |
| `ComfortSettingType` | Named preset kind | `ACTIVE`, `SLEEP`, `AWAY`, `STANDBY`, `CUSTOM` |
| `ComfortSettingOverride` | Why the active preset differs from schedule | `NONE`, `UNTIL_NEXT_SCHEDULE`, `INDEFINITE`, `UNOCCUPIED`, `OCCUPIED` |
| `BoostMode` | Space turbo override | `OFF`, `ON` |
| `OccupancyMode` | Space auto-away/return setting | `DISABLED`, `ENABLED` |
| `OccupancyState` | Presence/occupancy detection result | `UNDETECTED`, `DETECTED` |
| `SafetyHeatingMode` | Freeze-protection setting | `DISABLED`, `ENABLED` |
| `ConditionState` | Diagnostic condition status | `INACTIVE`, `ACTIVE` |
| `HvacControllerType` | Controller algorithm variant | `PASS_THROUGH_TEMPERATURE`, `INTEGRAL_TEMPERATURE_V1`, `INTEGRAL_TEMPERATURE_V2` |
| `ControllerViewState` | Dial display state | `SLEEP`, `GLANCE`, `ACTIVE`, `INTERACTING` |
| `ControllerOrientation` | Dial mounting | `INDETERMINATE`, `VERTICAL`, `HORIZONTAL` |
| `IndoorUnitTestMode` | IDU test mode | `INACTIVE`, `HEALTH_CHECK`, `REQUEST_TEST`, `STANDBY`, `COMMISSIONING` |
| `IndoorUnitTestCoordination` | How IDUs on one ODU sequence tests | `NONE`, `REQUESTING`, `STANDBY`, `PARALLEL`, `WAITING`, `EXCLUSIVE`, `DONE` |
| `IndoorUnitTestPhase` | IDU test phase | `NONE`, `SELF_TEST`, `HEATING`, `COOLING` |
| `NotificationType` | Stream event kind | `UPDATED`, `DELETED`, `CREATED`, `CHILD_CREATED`, `CHILD_DELETED` |
| `FallbackControlCommand` | Offline fallback command sent to an IDU | `COMPLETE`, `EXIT` |
| `RemoteSensorControlMode` | Whether a remote sensor participates in control | `DISABLED`, `ENABLED` |
| `FastUpdateReason` | Why `request_fast_updates()` is asking the cloud to raise the telemetry cadence | `UNSPECIFIED`, `LOCAL_COMMS_UNHEALTHY`, `USER_ACTIVITY` |

`FanSpeed.to_wire()` and `FanSpeed.from_wire()` handle the Quilt protocol's `(fan_speed_mode, fan_speed_percent)` encoding. `LouverAngle.to_wire()` and `LouverAngle.from_wire()` do the same for fixed louver positions.
