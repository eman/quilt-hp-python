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
| `list_comfort_settings(location_id)` | Lists comfort setting protos for a location. |
| `update_comfort_setting(cs_proto)` | Updates a comfort setting proto. |
| `create_schedule_day(...)` | Creates a new schedule day program. |
| `update_schedule_day(...)` | Updates an existing schedule day. |
| `delete_schedule_day(schedule_day_id)` | Deletes a schedule day by ID. |
| `create_schedule_week(...)` | Creates a new schedule week. |
| `update_schedule_week(...)` | Updates a schedule week's day assignments. |
| `delete_schedule_week(schedule_week_id)` | Deletes a schedule week by ID. |
| `set_schedule_execution(location_id, paused)` | Pauses or resumes all schedules for a location. |

**Caveat on updates**: The `UpdateSpace` request uses a `Space` proto field mask. All fields in the settings submessage must be populated — the server interprets absent fields as "clear to default". `QuiltClient.set_space()` handles this by reading the current snapshot and echoing existing values for any fields you don't explicitly change.

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

### `NotifierStream`

```python
from quilt_hp.services.streaming import NotifierStream

stream = NotifierStream(
    channel=channel,
    topics=topics,
    token_provider=client,
    max_reconnects=-1,
    reconnect_delay_s=1.0,
)
```

See [Streaming protocol behavior](../explanation/streaming-protocol.md) for the full state machine, event types, and reconnect behavior.

Key event registration methods:

```python
stream.on_space_update(callback)       # Callable[[Space], Awaitable | None]
stream.on_indoor_unit_update(callback) # Callable[[IndoorUnit], Awaitable | None]
stream.on_comfort_setting_update(callback)
stream.on_connected(callback)          # no args
stream.on_disconnected(callback)       # no args
```

---

## Model dataclasses

All models are `dataclass` instances populated from proto fields by `from_proto()` class methods. They are immutable in practice (no `frozen=True`, but mutation is undefined behavior).

### `SystemSnapshot`

```python
@dataclass
class SystemSnapshot:
    system_id: str
    location_id: str
    spaces: dict[str, Space]
    indoor_units: dict[str, IndoorUnit]
    outdoor_units: dict[str, OutdoorUnit]
    controllers: dict[str, Controller]
    sensors: dict[str, RemoteSensor]
    comfort_settings: dict[str, ComfortSetting]
    schedule_days: dict[str, ScheduleDay]
    schedule_weeks: dict[str, ScheduleWeek]
    schedule_paused: bool
    fetched_at: float  # time.time() when snapshot was constructed
```

`SystemSnapshot` is the root object returned by `get_snapshot()`. All child objects are indexed by their string ID for O(1) lookup.

Useful helper properties and methods:

```python
snapshot.rooms         # → list[Space]  leaf spaces only (has parent_space_id)
snapshot.floors        # → list[Space]  parent spaces only
snapshot.stream_topics()  # → list[str]  all topics for use with stream()
```

The `apply_*` methods (`apply_space_update`, `apply_indoor_unit_update`, etc.) are called by `NotifierStream` to merge sparse proto3 diffs into the snapshot in-place. You rarely call these directly.

---

### `Space`

```python
@dataclass
class Space:
    id: str
    name: str
    parent_space_id: str | None
    location_id: str
    controls: SpaceControls
    settings: SpaceSettings
    state: SpaceState
```

A single room or floor zone. `parent_space_id is None` for floor-level spaces; leaf rooms always have a parent.

#### `SpaceControls`

```python
@dataclass
class SpaceControls:
    mode: HVACMode
    heat_setpoint_c: float
    cool_setpoint_c: float
    comfort_setting_id: str | None
```

The writable HVAC setpoint state. `comfort_setting_id` is `None` when the space is in manual control mode. Setting `mode=STANDBY` clears `comfort_setting_id`.

#### `SpaceSettings`

```python
@dataclass
class SpaceSettings:
    unoccupied_timeout_s: float
    occupied_timeout_s: float
    schedules_paused: bool
```

Automation configuration for the space.

#### `SpaceState`

```python
@dataclass
class SpaceState:
    current_temp_c: float | None
    occupancy: OccupancyState  # OCCUPIED, UNOCCUPIED, UNKNOWN
    last_occupied_at: datetime | None
```

Read-only live state derived from sensor telemetry.

---

### `IndoorUnit`

```python
@dataclass
class IndoorUnit:
    id: str
    space_id: str
    system_id: str
    serial_number: str | None
    model_name: str | None
    controls: IndoorUnitControls
    settings: IndoorUnitSettings
    state: IndoorUnitState
```

#### `IndoorUnitControls`

```python
@dataclass
class IndoorUnitControls:
    fan_speed: FanSpeed
    louver_mode: LouverMode
    louver_position: float  # 0.0–1.0 when FIXED
    led_color_code: int     # RGBW packed int32
    led_brightness: float   # 0.0–1.0
    led_animation: int
```

#### `IndoorUnitSettings`

```python
@dataclass
class IndoorUnitSettings:
    fence_left_m: float   # 0 = unconfigured / max range
    fence_right_m: float
    fence_forward_m: float
    radar_height_m: float
    light_brightness_default: float
```

Radar presence detection calibration. Fence values of `0.0` mean unconfigured (uses hardware maximum range).

#### `IndoorUnitState`

```python
@dataclass
class IndoorUnitState:
    updated_at: datetime | None
    target_temp_c: float | None
    actual_temp_c: float | None
    is_online: bool         # updated_at within last 5 minutes
    presence_detected: bool
    led_on: bool            # True only when is_online
```

`is_online` is computed locally from `updated_at`: `datetime.now(UTC) - updated_at < timedelta(minutes=5)`. `led_on` returns `False` whenever `is_online` is `False`, even if `led_color_code` is non-zero.

---

### `OutdoorUnit`

```python
@dataclass
class OutdoorUnit:
    id: str
    system_id: str
    serial_number: str | None
    model_name: str | None
    state: OutdoorUnitState
```

#### `OutdoorUnitState`

```python
@dataclass
class OutdoorUnitState:
    updated_at: datetime | None
    outdoor_temp_c: float | None
    is_online: bool
```

---

### `Controller`

```python
@dataclass
class Controller:
    id: str
    system_id: str
    serial_number: str | None
    firmware_version: str | None
    state: ControllerState
```

#### `ControllerState`

```python
@dataclass
class ControllerState:
    updated_at: datetime | None
    is_online: bool
```

---

### `RemoteSensor`

```python
@dataclass
class RemoteSensor:
    id: str
    space_id: str
    system_id: str
    name: str | None
    state: RemoteSensorState
```

#### `RemoteSensorState`

```python
@dataclass
class RemoteSensorState:
    updated_at: datetime | None
    temp_c: float | None
    humidity_pct: float | None
    is_online: bool
```

---

### `ComfortSetting`

```python
@dataclass
class ComfortSetting:
    id: str
    location_id: str
    name: str
    hvac_mode: HVACMode
    heat_setpoint_c: float
    cool_setpoint_c: float
    fan_speed: FanSpeed
```

A named HVAC preset. Spaces reference comfort settings by `controls.comfort_setting_id`.

---

### `ScheduleDay`

```python
@dataclass
class ScheduleDay:
    id: str
    space_id: str
    name: str
    events: list[ScheduleEvent]
```

#### `ScheduleEvent`

```python
@dataclass
class ScheduleEvent:
    time_of_day_s: int          # seconds from midnight
    comfort_setting_id: str
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
    day_of_week: int            # 0 = Monday, 6 = Sunday
    schedule_day_id: str | None
```

---

### `SystemInfo`

```python
@dataclass
class SystemInfo:
    id: str
    name: str
    timezone: str
    location_id: str
```

Returned by `list_systems()`.

---

### `Location`

```python
@dataclass
class Location:
    id: str
    name: str
    timezone: str
    schedule_paused: bool
```

Location metadata embedded in `SystemSnapshot`.

---

## Enum types

All enums live in `quilt_hp.models.enums`. They are `StrEnum` values (except `LouverMode`, `LedAnimation`, and `LightPreset` which may be `IntEnum`).

| Enum | Values |
|------|--------|
| `HVACMode` | `STANDBY`, `COOL`, `HEAT`, `AUTO`, `FAN` |
| `FanSpeed` | `AUTO`, `QUIET`, `LOW`, `MEDIUM`, `HIGH`, `BLAST` |
| `LouverMode` | `CLOSED`, `SWEEP`, `FIXED`, `AUTO` |
| `OccupancyState` | `OCCUPIED`, `UNOCCUPIED`, `UNKNOWN` |
| `DeclaredUserType` | `HOMEOWNER`, `PARTNER` |

`FanSpeed.to_wire()` maps to `(fan_speed_mode, fan_speed_percent)` pairs consumed by the HDS proto. This mapping is handled inside `HomeDatastoreService`; client code works with `FanSpeed` values only.
