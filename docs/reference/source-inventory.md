# Source inventory

This is a module-by-module map of the codebase — what each file exports, what it does, and where to find it in the documentation. Use it as a navigation aid when reading the code or deciding where to make a change.

## Core package

### `src/quilt_hp/__init__.py`

The public package surface. Exports: `QuiltClient`, `Environment`, `QuiltError`, `QuiltAuthError`, `QuiltConnectionError`, `QuiltNotFoundError`, and `__version__`. Everything a library consumer needs is importable from `quilt_hp` directly.

Documentation: [Public API reference](../reference/client.md)

---

### `src/quilt_hp/client.py`

**`QuiltClient`** — the high-level async façade. This is the primary user-facing class. It owns the gRPC channel lifecycle, authentication state, snapshot TTL cache, and exposes all domain-level methods.

Key methods: `login`, `refresh_token`, `get_snapshot`, `invalidate_snapshot`, `list_systems`, `get_system_id`, `list_spaces`, `set_space`, `set_space_settings`, `list_indoor_units`, `set_indoor_unit`, `set_indoor_unit_settings`, `list_comfort_settings`, `update_comfort_setting`, `create_schedule_day`, `update_schedule_day`, `delete_schedule_day`, `create_schedule_week`, `update_schedule_week`, `delete_schedule_week`, `set_schedule_execution`, `get_energy`, `stream`, `get_current_user`, `update_current_user`, `get_user_attributes`, `patch_user_attributes`.

Documentation: [QuiltClient API reference](../reference/client.md), [Usage patterns](../how-to/control-spaces.md)

---

### `src/quilt_hp/auth.py`

**`authenticate()`** — the three-step Cognito token resolution function. Also defines `OtpCallback` type alias. Internal helpers: `_do_otp_login()`, `_do_refresh()`. The OTP flow uses `boto3` and runs boto3 calls in a thread executor to keep the async loop unblocked.

Documentation: [Transport and auth](../explanation/authentication.md), [Token management](../reference/token-management.md)

---

### `src/quilt_hp/tokens.py`

Token data types and protocols. Contents:

- `CachedTokens` — dataclass holding `id_token`, `refresh_token`, `expires_at` (Unix timestamp). `is_expired` property applies a 300-second (5-minute) safety buffer.
- `TokenStore` — async-first protocol for token persistence.
- `LegacyTokenStore` — synchronous compatibility protocol.
- `TokenStoreLike` — type alias for `TokenStore | LegacyTokenStore`.
- `CurrentTokenProvider` — protocol for objects that can return the current JWT.
- `TokenRefreshReason` — `StrEnum`: `EXPIRED_CACHED_TOKEN`, `TRANSPORT_UNAUTHENTICATED`, `STREAM_UNAUTHENTICATED`.
- `TokenRefreshContext` — frozen dataclass: `reason`, `source`, `attempt`.
- `RefreshFailureAction` — `StrEnum`: `FALLBACK_TO_OTP`, `RAISE`.
- `TokenRefreshHooks` — protocol with `on_refresh_start`, `on_refresh_success`, `on_refresh_failure` hooks.
- `TokenRefreshPolicy` — protocol with `on_refresh_failure` that returns a `RefreshFailureAction`.

Documentation: [Token management reference](../reference/token-management.md)

---

### `src/quilt_hp/transport.py`

gRPC channel creation and auth interceptor. Contents:

- `_AuthInterceptor` — implements all four gRPC `ClientInterceptor` interfaces. Injects `authorization` and `x-quilt-app-version` into every outbound call. For unary RPCs: retries once on `UNAUTHENTICATED` after invoking `refresh_callback`.
- `create_channel()` — creates a `grpc.aio.secure_channel` with TLS and the auth interceptor. Accepts a `token_provider` (callable or `CurrentTokenProvider`) and optional `refresh_callback`.
- `auth_metadata()` — standalone helper that builds the two metadata tuples; used by `NotifierStream` which passes metadata per-call rather than relying on the interceptor.

Documentation: [Transport and auth](../explanation/authentication.md)

---

### `src/quilt_hp/const.py`

Constants and configuration. Contents:

- `Environment` enum: `PROD`, `STAGING`, `DEV`.
- `grpc_host(env)` — returns the `host:port` string for the given environment.
- `COGNITO_REGION = "us-west-2"`, `COGNITO_CLIENT_ID = "6lef74vtc8p7pgu47nmqubd9vn"`.
- `APP_VERSION = "1.0.25"` — sent as `x-quilt-app-version` on every RPC.
- `GRPC_CHANNEL_OPTIONS` — keepalive settings: 30 s ping interval, 10 s ping timeout, ping permitted without calls, unlimited pings without data.

Documentation: [Protocol overview](../explanation/grpc-and-protobuf.md), [Transport and auth](../explanation/authentication.md)

---

### `src/quilt_hp/exceptions.py`

Exception hierarchy:

- `QuiltError` — base class for all library exceptions.
- `QuiltAuthError` — authentication failure (OTP rejected, refresh expired, Cognito error).
- `QuiltConnectionError` — connection failure.
- `QuiltNotFoundError` — requested resource not found (404-equivalent).
- `QuiltStreamError` — fatal stream error after reconnect budget exhausted.

Documentation: [Public API reference](../reference/client.md)

---

### `src/quilt_hp/_paths.py`

`app_config_dir()` — returns the platform-appropriate config directory for the CLI's state files (`~/.config/quilt-hp/` on Linux/macOS).

---

## Services

### `src/quilt_hp/services/hds.py`

**`HomeDatastoreService`** — async CRUD for HDS entities.

- `get_system(system_id)` → `SystemSnapshot` — calls `GetHomeDatastoreSystem`.
- `update_space(snapshot_space, ...)` → `Space` — builds a sparse `UpdateSpaceRequest` diff. Handles STANDBY semantics (clears `comfort_setting_id`) and AUTO enforcement (forces ≥ 2.5°C gap between heating and cooling setpoints).
- `update_space_settings(snapshot_space, ...)` → `Space` — updates auto-away/return timeouts. Echoes all existing settings fields to avoid server-side clearing of absent fields.
- `update_indoor_unit(idu, ...)` → `IndoorUnit` — updates fan speed, louver, LED.
- `update_indoor_unit_settings(idu, ...)` → `IndoorUnit` — updates presence fence geometry and default brightness.
- `update_comfort_setting(setting, ...)` → `ComfortSetting`.
- `create_schedule_day`, `update_schedule_day`, `delete_schedule_day`.
- `create_schedule_week`, `update_schedule_week`, `delete_schedule_week`.
- `update_location_schedule_execution(location_id, system_id, paused)` — pauses or resumes all schedules.

Documentation: [Service and model reference](../reference/models.md), [gRPC services matrix](../reference/grpc-services-matrix.md), [HDS entities](../reference/hds-entities.md)

---

### `src/quilt_hp/services/streaming.py`

**`NotifierStream`** — async manager for the `NotifierService.Subscribe` bidirectional stream.

Key behaviour:
- Sends initial `SubscribeRequest(append=...)` then listens on a queue for additional topic adds/removes.
- Parses the complex nested wire format manually (binary proto field extraction) because Python's `google.protobuf.Any` unpacking does not work cleanly with the nested wrapping.
- Dispatches parsed entities to registered callbacks (sync or async both supported).
- Reconnects with exponential back-off starting at `reconnect_delay_s`, doubling each attempt, capped at 60 s.
- On `UNAUTHENTICATED`: invokes `authenticate` callback to refresh token, then reconnects.
- Can run as background task (`async with stream:`) or blocking (`await stream.run_forever()`).

Callback types: `SpaceCallback`, `IndoorUnitCallback`, `OutdoorUnitCallback`, `ControllerCallback`, `QsmCallback`, `RemoteSensorCallback`, `ControllerRemoteSensorCallback`, `SoftwareUpdateInfoCallback`, `ErrorCallback`.

Documentation: [Streaming protocol](../explanation/streaming-protocol.md), [Usage patterns](../how-to/control-spaces.md)

---

### `src/quilt_hp/services/system.py`

**`SystemInformationService`** — wraps `ListSystems` → `list[SystemInfo]` and `GetEnergyMetrics` → `list[SpaceEnergyMetrics]`.

Documentation: [Service and model reference](../reference/models.md)

---

### `src/quilt_hp/services/user.py`

**`UserService`** — wraps `GetLoggedInUser`, `UpdateLoggedInUser`, `GetUserAttributes`, and `PatchUserAttributes`. Returns `User` and `UserAttributes` domain objects.

Documentation: [Service and model reference](../reference/models.md)

---

## Models

### `src/quilt_hp/models/system.py`

**`SystemSnapshot`** — the complete in-memory system state. Fields: `spaces`, `indoor_units`, `outdoor_units`, `controllers`, `quilt_smart_modules`, `comfort_settings`, `schedule_weeks`, `schedule_days`, `remote_sensors`, `controller_remote_sensors`, `software_update_infos`, `locations`, `timezone`. Methods: `rooms`, `primary_location`, `space_by_name`, `enrich_space`, `apply_space`, `apply_indoor_unit`, `apply_outdoor_unit`, `apply_controller`, `apply_qsm`, `apply_remote_sensor`, `apply_controller_remote_sensor`, `stream_topics`.

**`SystemInfo`** — basic system metadata from `ListSystems`: `id`, `name`, `timezone`.

**`Location`** — location entity: `id`, `name`, `system_id`, `timezone`, `schedule_paused`.

Documentation: [Service and model reference](../reference/models.md), [HDS entities](../reference/hds-entities.md)

---

### `src/quilt_hp/models/space.py`

**`Space`** — room-level HVAC zone with `SpaceSettings`, `SpaceControls`, `SpaceState`. Convenience properties: `is_room`, `is_off`, `is_away`, `ambient_temperature_f`.

Documentation: [HDS entities](../reference/hds-entities.md)

---

### `src/quilt_hp/models/indoor_unit.py`

**`IndoorUnit`** — wall-mounted mini-split head with `IndoorUnitControls`, `IndoorUnitSettings`, `IndoorUnitState`, and optional sub-messages: `IndoorUnitHvacInputs`, `IndoorUnitConditions`, `IndoorUnitPerformanceData`, `IndoorUnitPerformanceMetrics`, `IndoorUnitPresence`, `IndoorUnitOccupancy`, `IndoorUnitCommands`. Convenience properties: `is_online`, `led_on`, `effective_occupancy_state`.

Documentation: [HDS entities](../reference/hds-entities.md)

---

### `src/quilt_hp/models/outdoor_unit.py`

**`OutdoorUnit`** — outdoor compressor unit model.

---

### `src/quilt_hp/models/controller.py`

**`Controller`** — the Quilt Dial thermostat/controller device model.

---

### `src/quilt_hp/models/comfort.py`

**`ComfortSetting`** — named comfort preset: `id`, `system_id`, `space_id`, `name`, `type`, `hvac_mode`, `heating_setpoint_c`, `cooling_setpoint_c`, `fan_speed`, `louver_mode`, `louver_fixed_position`.

Documentation: [HDS entities](../reference/hds-entities.md)

---

### `src/quilt_hp/models/schedule.py`

**`ScheduleDay`**, **`ScheduleEvent`**, **`ScheduleWeek`**, **`ScheduleWeekDay`** — schedule program models.

Documentation: [HDS entities](../reference/hds-entities.md)

---

### `src/quilt_hp/models/sensor.py`

**`RemoteSensor`**, **`ControllerRemoteSensor`** — wireless temperature/humidity sensor models.

---

### `src/quilt_hp/models/qsm.py`

**`QuiltSmartModule`** — the embedded module inside each indoor unit that handles connectivity.

---

### `src/quilt_hp/models/energy.py`

**`SpaceEnergyMetrics`** — per-space energy consumption: `space_id` and a list of `EnergyBucket` (each with `start_time`, `energy_kwh`, `status`).

---

### `src/quilt_hp/models/enums.py`

All Python enum types: `HVACMode`, `HVACState`, `FanSpeed`, `LouverMode`, `LouverAngle`, `LightPreset`, `LedAnimation`, `ComfortSettingType`, `OccupancyMode`, `SafetyHeatingMode`, `OccupancyState`, `Presence`, `LightState`, `ConditionState`, `HvacControllerType`, `BoostMode`, `ComfortSettingOverride`, `FallbackControlCommand`, `RemoteSensorControlMode`.

Documentation: [Service and model reference](../reference/models.md)

---

## CLI

### `src/quilt_hp/cli/main.py`

Typer CLI application. Commands: `login`, `info`, `devices`, `values`, `energy`, `set`, `stream`, `tui`. Uses `FileStore` and `SettingsStore` for persistent state.

Documentation: [CLI automation playbook](../how-to/cli-scripting.md)

---

### `src/quilt_hp/cli/store.py`

**`FileStore`** — filesystem-backed `TokenStore` implementation. Stores tokens in `~/.config/quilt-hp/tokens.json` at `chmod 0o600`. Methods: `load`, `save`, `clear_tokens`, `list_emails`.

Documentation: [Token management reference](../reference/token-management.md)

---

### `src/quilt_hp/cli/settings.py`

**`SettingsStore`** — persists CLI preferences (email, home) so they don't need to be specified on every invocation.

---

### `src/quilt_hp/cli/tui.py`

Textual terminal UI. Implements a full-screen dashboard using a `QuiltClient` + `NotifierStream` for live updates.

Documentation: [TUI and event-driven app playbook](../how-to/tui-app.md)

---

## Protocol artifacts

### `proto/cleaned/*.proto`

Hand-cleaned protobuf definitions reconstructed from the Quilt mobile apps. Five files: `quilt_hds.proto`, `quilt_services.proto`, `quilt_notifier.proto`, `quilt_system.proto`, `quilt_device_pairing.proto`.

Documentation: [Protobuf artifacts and regeneration](../how-to/regenerate-protos.md), [gRPC protocol concepts](../explanation/grpc-and-protobuf.md)

---

### `src/quilt_hp/_proto/`

Generated Python stubs (vendored). Do not edit these by hand — regenerate with `./scripts/regen_protos.sh`.

Documentation: [Protobuf artifacts and regeneration](../how-to/regenerate-protos.md)
