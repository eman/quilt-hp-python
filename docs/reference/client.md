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
    QuiltPreconditionError,
    QuiltActionError,
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

### `QuiltActionError`

```python
class QuiltActionError(QuiltError):
    outcome: ActionOutcome
```

Raised by the `apply_*` action methods when the server reports the action failed; `outcome`
holds its `failure_reason`.

### `QuiltPreconditionError`

```python
class QuiltPreconditionError(QuiltError): ...
```

Raised when the server refuses because the system isn't set up for the request yet (gRPC
`FAILED_PRECONDITION`), for example `list_certified_partners()` on a system with no address.
The message is the server's explanation.

### `__version__`

```python
__version__: str  # e.g. "0.5.5"
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

---

### `get_system_version`

```python
async def get_system_version(self, system_id: str | None = None) -> int | None
```

Fetches only the system's configuration version (a ~14-byte response, about 70 ms against
~550 ms for a full snapshot). The version is an epoch-nanosecond timestamp that advances whenever
controls, settings or configuration are written, including automatic writes such as auto-away
switching a comfort setting; telemetry does not advance it.

```python
if await client.get_system_version() != snapshot.version:
    client.invalidate_snapshot()
    snapshot = await client.get_snapshot()
```

---

### Single-object fetches

```python
async def get_space(self, space_id: str) -> Space
async def get_indoor_unit(self, indoor_unit_id: str) -> IndoorUnit
async def get_outdoor_unit(self, outdoor_unit_id: str) -> OutdoorUnit
async def get_controller(self, controller_id: str) -> Controller
async def get_quilt_smart_module(self, qsm_id: str) -> QuiltSmartModule
async def get_comfort_setting(self, comfort_setting_id: str) -> ComfortSetting
async def get_remote_sensor(self, sensor_id: str) -> RemoteSensor
async def get_controller_remote_sensor(self, sensor_id: str) -> ControllerRemoteSensor
async def get_schedule_day(self, schedule_day_id: str) -> ScheduleDay
async def get_schedule_week(self, schedule_week_id: str) -> ScheduleWeek
async def get_software_update_info(self, info_id: str) -> SoftwareUpdateInfo
```

Fetch one object straight from the server instead of a full snapshot. The result lacks hardware
attributes (`model_sku`, `serial_number`, `firmware_version`) and, for spaces, comfort-setting
enrichment (`active_comfort_setting_type`). Merge it into a snapshot to keep those:

```python
idu = snapshot.apply_indoor_unit(await client.get_indoor_unit(idu_id))
```

The client's `list_spaces`, `list_indoor_units` and `list_comfort_settings` read from the cached
snapshot (see `get_snapshot`), which is usually what you want.

**Raises:** `QuiltNotFoundError` if the object does not exist or is not visible to you (the server
answers both with `PERMISSION_DENIED`). `QuiltError` for other gRPC failures.

---

### `get_diagnostics`

```python
async def get_diagnostics(self, system_id: str | None = None) -> SystemDiagnostics
```

Fetches the installer-style diagnostic view — a convenience wrapper over
`get_snapshot().diagnostics()`. Returns a [`SystemDiagnostics`](models.md#systemdiagnostics)
with, per indoor unit: the fault/condition matrix (including the outdoor-unit and
refrigerant conditions surfaced through each IDU), refrigerant-circuit temperatures
(coil / gas-pipe / liquid-pipe / inlet / outlet) and humidity, and per-unit power.

The outdoor unit's own raw sensors (compressor Hz, pressures, discharge temp) are
withheld from the cloud plane and are **not** included; `OutdoorUnitDiagnostics`
reports `raw_sensors_available=False`.

**Parameters:**
- `system_id`: explicit system ID; defaults to the client's resolved system.

**Raises:** `QuiltError` if the RPC fails.

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

## Dial settings

### `set_controller`

```python
async def set_controller(
    self,
    controller: Controller | str,
    *,
    name: str | None = None,
    uses_dial_temperature: bool | None = None,
) -> Controller
```

Rename a Dial, and/or choose which sensor its room is controlled to. Only the settings you
pass are sent.

| Parameter | Meaning |
|---|---|
| `controller` | A `Controller` object or controller ID string |
| `name` | The Dial's new name |
| `uses_dial_temperature` | `True` to control the room to the Dial's temperature (the app's "Temperature sensor" switch); `False` to use the indoor unit's built-in sensor |

```python
dial = next(d for d in snapshot.controllers if d.space_id == den.id)
await client.set_controller(dial, uses_dial_temperature=True)
await client.set_controller(dial, name="Den Dial")
```

After switching the sensor, the room's temperature moves to the new source over about a
minute rather than jumping.

**Returns:** The updated `Controller` as the server reports it (hardware fields are `None`).
The cached snapshot is invalidated.

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

## Indoor-unit self-test

### `start_self_test` / `cancel_self_test`

```python
async def start_self_test(self, idu: IndoorUnit | str) -> None
async def cancel_self_test(self, idu: IndoorUnit | str) -> None
```

Start or cancel an indoor unit's diagnostic self-test: the Quilt app's "Run diagnostic
test" (`DiagnosticService`). In the app's words, the test "takes up to 30 minutes. During
this time, [the room] won't be available for heating or cooling." Quilt, and the home's
certified partner if it has one, see the results; the server returns nothing to the caller.

Follow progress on the indoor unit:

```python
await client.start_self_test(unit)
snapshot = await client.get_snapshot()
unit = next(u for u in snapshot.indoor_units if u.id == unit.id)
print(unit.is_under_test, unit.effective_test_mode, unit.state.hvac_state)
```

What a run looked like on a live system (2026-10-06), for a unit alone on its outdoor unit:

| Time | `test_state` (mode / coordination / phase) | `state.hvac_state` |
|---|---|---|
| 0 s | `INACTIVE` / `NONE` / `NONE` | `STANDBY` |
| 15 s | `HEALTH_CHECK` / `EXCLUSIVE` / `NONE` | `STANDBY`, then `COOL` |
| ~19 min | `HEALTH_CHECK` / `EXCLUSIVE` / `NONE` | `HEAT` (pipes 52–56 °C) |
| ~20.5 min | `INACTIVE` / `NONE` / `NONE` | `STANDBY` |

`test_phase` stayed `NONE` throughout, so use `is_under_test` and `hvac_state` rather than
the phase. `test_state` cleared about 15 s before `state.test_mode`; `is_under_test` uses the
newer of the two, as does `effective_test_mode` (`test_state` itself can be `None`). Units sharing an outdoor unit presumably take turns
(`test_state.test_coordination`); this run didn't exercise that. The room's own mode and
setpoints were unchanged afterwards. The cached snapshot is invalidated after each call.

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

## Telemetry cadence

### `request_fast_updates`

```python
async def request_fast_updates(
    self,
    *,
    reason: FastUpdateReason = FastUpdateReason.USER_ACTIVITY,
    system_id: str | None = None,
) -> None
```

Asks the cloud to raise the telemetry cadence for a system by calling
`CommandService/RequestFastUpdates` — the same lever the mobile app pulls when
the user is active or a device's local mesh is degraded. New in the Quilt app
versionCode 255.

The RPC response is empty; the effect is a faster stream of state updates over
a `NotifierStream`, so pair this with `stream()`. There is no local endpoint —
the request flows through the cloud API like every other call.

**Parameters:**
- `reason`: `FastUpdateReason.USER_ACTIVITY` (default), `LOCAL_COMMS_UNHEALTHY`, or `UNSPECIFIED`. Imported from `quilt_hp.models.enums`.
- `system_id`: explicit system ID; defaults to the client's resolved system.

**Raises:** `QuiltError` if the client is not connected or the RPC fails.

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

---

## Actions

```python
async def apply_mode(self, mode: ClimateMode | HVACMode, *, rooms=(), indoor_units=(), whole_house=False) -> ActionOutcome
async def apply_temperatures(self, *, heat_c=None, cool_c=None, rooms=(), indoor_units=(), whole_house=False) -> ActionOutcome
async def apply_fan_speed(self, speed: FanSpeed, *, rooms=(), indoor_units=(), whole_house=False) -> ActionOutcome
async def apply_fan_angle(self, angle: FanAngle, *, rooms=(), indoor_units=(), whole_house=False) -> ActionOutcome
async def apply_light(self, *, on=None, brightness_percent=None, color=None, animation=None,
                      rooms=(), indoor_units=(), whole_house=False) -> ActionOutcome
```

One call changes any mix of rooms (`Space` objects or IDs), indoor units, or the whole house,
through the same action API the Quilt app uses (`HomeActionService/SubmitAction`). Each also
takes `system_id`.

```python
from quilt_hp.models import ClimateMode, FanAngle, LightPreset, RgbwColor

await client.apply_mode(ClimateMode.OFF, whole_house=True)          # everything off
await client.apply_temperatures(cool_c=23.5, rooms=["Office id", den])
await client.apply_fan_angle(FanAngle.FLOOR, rooms=[den])
await client.apply_light(on=True, brightness_percent=40, color=RgbwColor(255, 120, 0), rooms=[den])
```

- **Mode** accepts `ClimateMode` (`OFF`, `HEAT`, `COOL`, `AUTO`, `FAN`, `DRY`, `AWAY`) or the
  familiar `HVACMode` (`STANDBY` means off). Its numbering differs from `HVACMode` on the wire;
  the library converts.
- **Fan speed, fan angle and light** apply to indoor units: a room is expanded to its indoor
  units, as the app does (the server rejects a room target for these).
- **Whole house** expands to every room (mode, temperatures) or every indoor unit (fan, louver,
  light).
- **Light**: `brightness_percent` is 0–100; `color` is a `LightPreset` or a custom
  `RgbwColor(red, green, blue, white)` (each 0–255). Settings you leave out are unchanged.

Each call returns an `ActionOutcome` (`result`, `action_id`, `failure_reason`; `ok` is True only
for `SUCCESS`, so a `PARTIAL_FAILURE` returns with `ok` False) and raises `QuiltActionError`
when the server reports the action failed. The cached snapshot is invalidated afterwards.

---

## Account (read-only)

These read who can use a system and how it relates to installer partners. They never change
anything. Methods that take `system_id` default to the client's system. The models are
described in [Models → Account models](models.md#account-models).

```python
async def list_system_users(self, system_id: str | None = None) -> SystemUsers
async def get_access_role(self, system_id: str | None = None) -> AccessRole
async def list_pending_invitations(self) -> list[Invitation]
async def get_partner_details(self) -> PartnerDetails | None
async def get_data_sharing(self, system_id: str | None = None) -> SystemDataSharing
async def list_certified_partners(self, system_id: str | None = None) -> list[PartnerProfile]
async def list_user_tasks(self, system_id: str | None = None) -> list[UserTask]
```

- `list_system_users` — the system's administrators and members, and the invitations sent
  from it that haven't been accepted.
- `get_access_role` — whether you are an `ADMIN` or a `MEMBER` of the system.
- `list_pending_invitations` — invitations *you* have received and not yet answered.
- `get_partner_details` — the installer partner organisation you belong to; `None` for
  homeowners.
- `get_data_sharing` — whether the system shares data with an installer partner
  (`NO_PARTNER` when it has none).
- `list_certified_partners` — certified installers for the system's location. Raises
  `QuiltPreconditionError` when the system has no address.
- `list_user_tasks` — prompts the app would show, such as a data-sharing consent banner.

```python
role = await client.get_access_role()
users = await client.list_system_users()
print(role.name, [u.full_name for u in users.administrators])
```
