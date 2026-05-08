# QuiltClient API reference

Complete reference for all `QuiltClient` methods. For usage examples see [Usage patterns](usage.md) and [Advanced workflows](advanced-workflows.md).

## Constructor

```python
QuiltClient(
    email: str,
    *,
    home: str | None = None,
    environment: Environment = Environment.PROD,
    snapshot_ttl_s: float = 0,
    token_store: TokenStoreLike | None = None,
    token_refresh_hooks: TokenRefreshHooks | None = None,
    token_refresh_policy: TokenRefreshPolicy | None = None,
)
```

See [Public API reference](public-api-reference.md) for full parameter documentation.

## Async context manager

```python
async def __aenter__(self) -> QuiltClient: ...
async def __aexit__(self, *_: object) -> None: ...
```

`__aexit__` closes the gRPC channel. Always use `QuiltClient` as an async context manager unless you are managing the channel lifecycle manually.

---

## Authentication

### `login`

```python
async def login(self, otp_callback: OtpCallback | None = None) -> None
```

Authenticates with the Quilt API using the three-step token resolution (cache → refresh → OTP).

If cached tokens are valid, returns immediately without any network call. If the cached access token is expired but the refresh token is valid, performs a silent `REFRESH_TOKEN_AUTH` without user interaction. Only calls `otp_callback` if no valid cached or refresh token is available.

**Parameters**:
- `otp_callback` — callable `(email: str) -> str | Awaitable[str]`. Receives the account email and must return the OTP code. Can be synchronous or async. Required if no valid cached token exists; `None` is acceptable when you know tokens are cached.

**Raises**: `QuiltAuthError` if authentication fails.

---

### `refresh_token`

```python
async def refresh_token(self, context: TokenRefreshContext | None = None) -> None
```

Refreshes the auth token silently using the refresh token. Does not attempt OTP. Called automatically by the transport interceptor and `NotifierStream` on `UNAUTHENTICATED`; you rarely need to call this directly.

---

## System discovery

### `list_systems`

```python
async def list_systems(self) -> list[SystemInfo]
```

Lists all Quilt systems the authenticated user has access to. Returns a list of `SystemInfo` objects with `id`, `name`, and `timezone`. For most users this returns a single system.

**Raises**: `QuiltError` if the gRPC call fails.

---

### `get_system_id`

```python
async def get_system_id(self, home: str | None = None) -> str
```

Returns the system ID for the current home filter (or the specified `home` override). Caches the result after the first call. Calls `list_systems()` internally.

---

### `system_name`

```python
@property
def system_name(self) -> str | None
```

The name of the resolved system (set after `get_system_id()` is called).

---

### `get_snapshot`

```python
async def get_snapshot(self, system_id: str | None = None) -> SystemSnapshot
```

Fetches the complete system state as a `SystemSnapshot`. This is the primary read operation — it returns all spaces, indoor units, outdoor units, controllers, sensors, comfort settings, and schedules in a single RPC call.

If `snapshot_ttl_s > 0` was configured and the cached snapshot is still fresh, the cached copy is returned without a network call. Passing `system_id` explicitly bypasses the cache and does not populate it.

**Parameters**:
- `system_id` — explicit system ID to query. When `None` (default), uses the primary system from `get_system_id()`.

**Raises**: `QuiltNotFoundError` if the system ID is not found. `QuiltError` for other gRPC failures.

---

### `invalidate_snapshot`

```python
def invalidate_snapshot(self) -> None
```

Discards the cached snapshot so the next `get_snapshot()` call fetches fresh data. Call this after write operations when you need an up-to-date snapshot immediately.

---

## Space control

### `list_spaces`

```python
async def list_spaces(self) -> list[Space]
```

Returns all room-level spaces (leaf spaces with a parent). Equivalent to `snapshot.rooms`. Fetches a snapshot internally.

---

### `set_space`

```python
async def set_space(
    self,
    space: Space | str,
    *,
    mode: HVACMode | None = None,
    heat_setpoint_c: float | None = None,
    cool_setpoint_c: float | None = None,
) -> Space
```

Updates a space's HVAC mode and/or temperature setpoints.

**Parameters**:
- `space` — a `Space` object (no snapshot lookup) or a space ID string (snapshot is fetched to resolve).
- `mode` — HVAC mode to set: `HVACMode.STANDBY`, `COOL`, `HEAT`, `AUTO`, `FAN`. Defaults to the current mode.
- `heat_setpoint_c` — heating setpoint in °C. Defaults to the current heating setpoint.
- `cool_setpoint_c` — cooling setpoint in °C. Defaults to the current cooling setpoint.

**Behavioural notes**:
- Setting `mode=HVACMode.STANDBY` clears the comfort setting association (the room stays off regardless of occupancy).
- Setting `mode=HVACMode.AUTO` with a gap less than 2.5°C between heating and cooling setpoints: the cooling setpoint is raised to `heat + 2.5` automatically.

**Returns**: Updated `Space` from the server response.

**Raises**: `QuiltError` if the space is not found or the RPC fails.

---

### `set_space_settings`

```python
async def set_space_settings(
    self,
    space: Space | str,
    *,
    unoccupied_timeout_s: float | None = None,
    occupied_timeout_s: float | None = None,
) -> Space
```

Updates a space's occupancy automation timeouts. All existing settings fields are echoed back to avoid server-side clearing.

**Parameters**:
- `space` — `Space` object or space ID string.
- `unoccupied_timeout_s` — seconds of no-presence before auto-away.
- `occupied_timeout_s` — seconds of presence before auto-return.

**Returns**: Updated `Space`.

---

## Indoor unit control

### `list_indoor_units`

```python
async def list_indoor_units(self) -> list[IndoorUnit]
```

Returns all indoor units. Fetches a snapshot internally.

---

### `set_indoor_unit`

```python
async def set_indoor_unit(
    self,
    idu: IndoorUnit | str,
    *,
    fan_speed: FanSpeed | None = None,
    louver_mode: LouverMode | None = None,
    louver_position: float | None = None,
    led_color_code: int | None = None,
    led_brightness: float | None = None,
    led_animation: int | None = None,
) -> IndoorUnit
```

Updates indoor unit controls.

**Parameters**:
- `idu` — `IndoorUnit` object or IDU ID string.
- `fan_speed` — `FanSpeed.AUTO`, `QUIET`, `LOW`, `MEDIUM`, `HIGH`, `BLAST`.
- `louver_mode` — `LouverMode.CLOSED`, `SWEEP`, `FIXED`, `AUTO`.
- `louver_position` — position 0.0–1.0 when `louver_mode=FIXED`.
- `led_color_code` — RGBW packed int32 (use `LightPreset` constants or compute manually).
- `led_brightness` — brightness 0.0–1.0.
- `led_animation` — animation ID (use `LedAnimation` enum values).

**Returns**: Updated `IndoorUnit`.

---

### `set_indoor_unit_settings`

```python
async def set_indoor_unit_settings(
    self,
    idu: IndoorUnit | str,
    *,
    fence_left_m: float | None = None,
    fence_right_m: float | None = None,
    fence_forward_m: float | None = None,
    radar_height_m: float | None = None,
    light_brightness_default: float | None = None,
) -> IndoorUnit
```

Updates indoor unit calibration settings. All omitted fields keep their current values.

**Parameters**:
- `fence_left_m` — left boundary of presence detection zone in metres (0 = unconfigured/max range).
- `fence_right_m` — right boundary.
- `fence_forward_m` — forward (depth) boundary.
- `radar_height_m` — radar sensor mounting height from floor in metres.
- `light_brightness_default` — default LED brightness 0.0–1.0.

---

## Comfort settings

### `list_comfort_settings`

```python
async def list_comfort_settings(self) -> list[ComfortSetting]
```

Returns all comfort presets. Fetches a snapshot internally.

---

### `update_comfort_setting`

```python
async def update_comfort_setting(
    self,
    setting: ComfortSetting | str,
    *,
    name: str | None = None,
    hvac_mode: HVACMode | None = None,
    heat_setpoint_c: float | None = None,
    cool_setpoint_c: float | None = None,
    fan_speed: FanSpeed | None = None,
) -> ComfortSetting
```

Updates a comfort preset. Omitted fields keep their current values.

**Parameters**:
- `setting` — `ComfortSetting` object or comfort setting ID string.

**Returns**: Updated `ComfortSetting`.

---

## Schedules

### `create_schedule_day`

```python
async def create_schedule_day(
    self,
    space_id: str,
    name: str,
    events: list[ScheduleEvent],
) -> ScheduleDay
```

Creates a new schedule day program for a space.

---

### `update_schedule_day`

```python
async def update_schedule_day(
    self,
    schedule_day_id: str,
    space_id: str,
    name: str | None = None,
    events: list[ScheduleEvent] | None = None,
) -> ScheduleDay
```

Updates an existing schedule day's name and/or events.

---

### `delete_schedule_day`

```python
async def delete_schedule_day(self, schedule_day_id: str) -> None
```

Deletes a schedule day program.

---

### `create_schedule_week`

```python
async def create_schedule_week(
    self,
    space_id: str,
    days: list[ScheduleWeekDay] | None = None,
) -> ScheduleWeek
```

Creates a new schedule week, optionally mapping weekdays to day programs.

---

### `update_schedule_week`

```python
async def update_schedule_week(
    self,
    schedule_week_id: str,
    space_id: str,
    days: list[ScheduleWeekDay],
) -> ScheduleWeek
```

Updates a schedule week's day assignments.

---

### `delete_schedule_week`

```python
async def delete_schedule_week(self, schedule_week_id: str) -> None
```

Deletes a schedule week.

---

### `set_schedule_execution`

```python
async def set_schedule_execution(self, paused: bool) -> None
```

Globally pauses or resumes all schedules for the primary location. `True` pauses; `False` resumes.

---

## Energy

### `get_energy`

```python
async def get_energy(
    self,
    start: datetime,
    end: datetime,
    system_id: str | None = None,
) -> list[SpaceEnergyMetrics]
```

Returns hourly energy consumption for all spaces in the given time range.

**Parameters**:
- `start`, `end` — timezone-aware `datetime` objects defining the query range.
- `system_id` — explicit system ID; defaults to the primary system.

**Returns**: List of `SpaceEnergyMetrics`, each with a `space_id` and a list of `EnergyBucket` objects (each with `start_time`, `energy_kwh`, `status`).

---

## Streaming

### `stream`

```python
def stream(
    self,
    topics: list[str],
    *,
    max_reconnects: int = -1,
    reconnect_delay_s: float = 1.0,
) -> NotifierStream
```

Creates a `NotifierStream` for real-time updates. Does not start the stream — call `start()`, `run_forever()`, or use as an async context manager.

**Parameters**:
- `topics` — list of topic strings. Use `snapshot.stream_topics()` to get all topics for a system.
- `max_reconnects` — maximum automatic reconnect attempts per disconnect. `-1` = unlimited (default).
- `reconnect_delay_s` — initial back-off in seconds before reconnecting. Doubles on each attempt, capped at 60 s.

**Returns**: `NotifierStream` instance.

See [Streaming protocol behavior](../protocol/streaming-protocol.md) for full stream documentation.

---

## User

### `get_current_user`

```python
async def get_current_user(self) -> User
```

Returns the authenticated user's profile: `quilt_user_id`, `first_name`, `last_name`, `email`, `phone_number`.

---

### `update_current_user`

```python
async def update_current_user(
    self,
    *,
    first_name: str,
    last_name: str,
    phone_number: str | None = None,
) -> User
```

Updates the authenticated user's name and optional phone number.

---

### `get_user_attributes`

```python
async def get_user_attributes(self) -> UserAttributes
```

Returns user attributes including `declared_user_type` (`HOMEOWNER` or `PARTNER`).

---

### `patch_user_attributes`

```python
async def patch_user_attributes(
    self,
    *,
    declared_user_type: DeclaredUserType,
) -> UserAttributes
```

Updates user attributes.
