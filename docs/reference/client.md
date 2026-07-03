# QuiltClient reference

Complete reference for the `quilt_hp` package, including all public exports, the `QuiltClient` constructor, and every method with full signatures, parameters, return types, and exceptions.

---

## Module exports

Everything a library consumer needs is importable from `quilt_hp` directly:

```python
from quilt_hp import (
    QuiltClient,
    Environment,
    QuiltError,
    QuiltAuthError,
    QuiltConnectionError,
    QuiltNotFoundError,
)
```

### `Environment`

```python
class Environment(Enum):
    PROD = "prod"
    STAGING = "staging"
    DEV = "dev"
```

| Value | gRPC host |
| --- | --- |
| `Environment.PROD` | `api.prod.quilt.cloud:443` |
| `Environment.STAGING` | `api.staging.quilt.cloud:443` |
| `Environment.DEV` | `api.dev.quilt.cloud:443` |

### `QuiltError`

```python
class QuiltError(Exception): ...
```

Base class for all library exceptions.

### `QuiltAuthError`

```python
class QuiltAuthError(QuiltError): ...
```

Raised when authentication fails. Causes: invalid or expired OTP, Cognito API error, malformed token in store, no `otp_callback` provided when OTP is required.

### `QuiltConnectionError`

```python
class QuiltConnectionError(QuiltError): ...
```

Raised when the library cannot connect to the Quilt gRPC API.

### `QuiltNotFoundError`

```python
class QuiltNotFoundError(QuiltError): ...
```

Raised when a requested resource does not exist (gRPC `NOT_FOUND`).

### `__version__`

```python
__version__: str  # e.g. "0.5.4"
```

---

## `QuiltClient`

```python
class QuiltClient:
    def __init__(
        self,
        email: str,
        *,
        home: str | None = None,
        environment: Environment = Environment.PROD,
        snapshot_ttl_s: float = 0,
        token_store: TokenStoreLike | None = None,
        token_refresh_hooks: TokenRefreshHooks | None = None,
        token_refresh_policy: TokenRefreshPolicy | None = None,
    ) -> None: ...
```

The primary user-facing class. Manages authentication, the gRPC channel lifecycle, and exposes all high-level HVAC control methods.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `email` | `str` | required | Quilt account email address. Used as the Cognito username and as the token store key. |
| `home` | `str \| None` | `None` | Home name filter (substring match, case-insensitive) for multi-home accounts. When omitted, the first system returned by `ListSystems` is used. |
| `environment` | `Environment` | `PROD` | Which Quilt API environment to connect to. |
| `snapshot_ttl_s` | `float` | `0` | If > 0, `get_snapshot()` results are cached for this many seconds. `0` disables caching. |
| `token_store` | `TokenStoreLike \| None` | `None` | Token persistence backend. `None` means in-memory only (tokens are lost when the process exits). |
| `token_refresh_hooks` | `TokenRefreshHooks \| None` | `None` | Observer for token refresh lifecycle events. |
| `token_refresh_policy` | `TokenRefreshPolicy \| None` | `None` | Controls behaviour on refresh failure. Default: fall back to OTP. |

**Async context manager:**

```python
async def __aenter__(self) -> QuiltClient: ...
async def __aexit__(self, *_: object) -> None: ...
```

`__aexit__` calls `close()`, which stops any live `NotifierStream`s created via `stream()` and closes the gRPC channel. Prefer the async context manager, or call `await close()` yourself when managing lifecycle manually.

---

## Authentication

### `login`

```python
async def login(self, otp_callback: OtpCallback | None = None) -> None
```

Authenticates using the three-step token resolution: cache → refresh → OTP.

If cached tokens are valid, returns immediately. If the cached access token is expired but the refresh token is valid, performs a silent `REFRESH_TOKEN_AUTH`. Calls `otp_callback` only when no valid cached or refresh token exists.

**Parameters:**
- `otp_callback`: `(email: str) -> str | Awaitable[str]`. Required when no valid cached token exists; pass `None` only when tokens are guaranteed to be cached.

**Raises:** `QuiltAuthError` if authentication fails.

---

### `refresh_token`

```python
async def refresh_token(self, context: TokenRefreshContext | None = None) -> None
```

Silently refreshes the auth token using the refresh token. Does not attempt OTP. Called automatically by the transport interceptor on `UNAUTHENTICATED`; rarely needed directly.

### `get_current_token`

```python
def get_current_token(self) -> str
```

Returns the current JWT access token held by the client.

**Raises:** `QuiltAuthError` if the client is not authenticated yet.

---

## System discovery

### `list_systems`

```python
async def list_systems(self) -> list[SystemInfo]
```

Lists all Quilt systems the authenticated user has access to.

**Returns:** List of `SystemInfo` objects with `id`, `name`, and `timezone`.

**Raises:** `QuiltError` if the gRPC call fails.

---

### `get_system_id`

```python
async def get_system_id(self, home: str | None = None) -> str
```

Returns the system ID for the current home filter. Caches the result after the first call.

---

### `system_name`

```python
@property
def system_name(self) -> str | None
```

Name of the resolved system (populated after `get_system_id()` is called).

---

### `get_snapshot`

```python
async def get_snapshot(self, system_id: str | None = None) -> SystemSnapshot
```

Fetches the complete system state as a `SystemSnapshot`.

**Parameters:**
- `system_id`: explicit system ID to query. When `None` (default), uses `get_system_id()`. Passing `system_id` bypasses the cache.

**Raises:** `QuiltNotFoundError` if the system ID is not found. `QuiltError` for other gRPC failures.

---

### `invalidate_snapshot`

```python
def invalidate_snapshot(self) -> None
```

Discards the cached snapshot. The next `get_snapshot()` call fetches fresh data from the server.

### `close`

```python
async def close(self) -> None
```

Closes the underlying gRPC channel and clears the client's open channel reference. Safe to call multiple times.

---

## Space control

### `list_spaces`

```python
async def list_spaces(self) -> list[Space]
```

Returns all room-level spaces. Equivalent to `snapshot.rooms`. Fetches a snapshot internally.

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

**Parameters:**
- `space`: `Space` object (no snapshot lookup) or space ID string (snapshot fetched internally).
- `mode`: `HVACMode.STANDBY`, `COOL`, `HEAT`, `AUTO`, or `FAN`. Defaults to current mode.
- `heat_setpoint_c`: heating setpoint in °C. Defaults to current.
- `cool_setpoint_c`: cooling setpoint in °C. Defaults to current.

**Behavioural notes:**
- `mode=STANDBY` clears `comfort_setting_id`; the room stays off regardless of occupancy.
- `mode=AUTO` with a gap of less than 2.5°C: cooling setpoint is raised to `heat + 2.5` automatically.

**Returns:** Updated `Space` from the server response.

**Raises:** `QuiltError` if the space is not found or the RPC fails.

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

Updates occupancy automation timeouts.

**Parameters:**
- `space`: `Space` object or space ID string.
- `unoccupied_timeout_s`: seconds of no-presence before auto-away.
- `occupied_timeout_s`: seconds of presence before auto-return.

**Returns:** Updated `Space`.

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

**Parameters:**
- `idu`: `IndoorUnit` object or IDU ID string.
- `fan_speed`: `FanSpeed.AUTO`, `QUIET`, `LOW`, `MEDIUM`, `HIGH`, or `BLAST`.
- `louver_mode`: `LouverMode.CLOSED`, `SWEEP`, `FIXED`, or `AUTO`.
- `louver_position`: position 0.0–1.0 when `louver_mode=FIXED`.
- `led_color_code`: RGBW packed int32. Use `LightPreset` constants or compute manually.
- `led_brightness`: brightness 0.0–1.0.
- `led_animation`: animation ID (`LedAnimation` enum values).

**Returns:** Updated `IndoorUnit`.

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

Updates indoor unit calibration settings.

**Parameters:**
- `fence_left_m`: left boundary of presence detection zone in metres (0 = unconfigured/max range).
- `fence_right_m`: right boundary.
- `fence_forward_m`: forward (depth) boundary.
- `radar_height_m`: radar sensor mounting height from floor in metres.
- `light_brightness_default`: default LED brightness 0.0–1.0.

**Returns:** Updated `IndoorUnit`.

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

**Returns:** Updated `ComfortSetting`.

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

Returns hourly energy consumption for all spaces.

**Parameters:**
- `start`, `end`: Timezone-aware `datetime` objects.
- `system_id`: explicit system ID; defaults to the primary system.

**Returns:** List of `SpaceEnergyMetrics`, each with `space_id` and a list of `EnergyBucket` objects (each with `start_time`, `energy_kwh`, `status`).

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

Creates a `NotifierStream`. It does not start the stream; call `start()`, `run_forever()`, or use it as an async context manager.

**Parameters:**
- `topics`: topic strings. Use `snapshot.stream_topics()` to get all topics for a system.
- `max_reconnects`: maximum *consecutive* reconnect attempts — the counter resets after a connection stays healthy, so this bounds retries per disconnect event. `-1` = unlimited (default). `0` = no retries.
- `reconnect_delay_s`: initial back-off in seconds. Doubles on each attempt, capped at 60 s.

**Returns:** `NotifierStream` instance.

See [The streaming protocol](../explanation/streaming-protocol.md) for the full reconnect state machine.

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
