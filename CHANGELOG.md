# Changelog

## [Unreleased]

### Added protocol support
- `HVACMode.DRY = 8` — dehumidification mode; gate: `mobile_dry_mode_selection_enabled`. Fan non-interactive (QSM forces ~600 RPM). No user-configurable temperature setpoint; built-in temperature floor is server-side.
- `HVACState.DRY = 11`, `DRY_DEFERRED = 12`, `DRY_PREPARING = 13`
- `LocalCommsHealthStatus` enum (`UNSPECIFIED=0`, `HEALTHY=1`, `DEGRADED=2`, `OFFLINE=3`, `STARTING_UP=4`) — gate: `mobile_local_control_health_enabled`
- `QuiltSmartModule.local_comms_health` — extracted from new `LocalCommsStatus` nested message (proto field 8, subfield 2)
- `Controller.local_comms_health` — extracted from new `LocalCommsStatus` nested message (proto field 9, subfield 2)
- `LocalCommsStatus` proto message with `updated_ts`, `health`, `link_state`, `version`, `health_changed_ts`, `connection_state` subfields (fields 1–6; wire-confirmed)

### Changed
- `APP_VERSION` bumped to `1.0.26`
- `LocalCommsStatus` is a **nested message** (not a simple enum) on both QSM and Controller — the earlier inferred field type was incorrect; wire-confirmed via 2026-06-04 mitmproxy capture

## [0.4.0] - 2026-05-16

## [0.3.2] - 2026-05-19

### Added
- `LouverAngle.label` property and `__str__` with human-readable position names:
  `ANGLE1` → `"Horizontal"`, `ANGLE2` → `"Slightly Down"`, `ANGLE3` → `"Down"`,
  `ANGLE4` → `"Mostly Down"`, `ANGLE5` → `"Straight Down"`

## [0.3.1] - 2026-05-14

### Fixed
- `RST_STREAM with error code 0` (HTTP/2 `NO_ERROR`, a normal server-side graceful reset) is now logged at `DEBUG` instead of `WARNING` to reduce log noise
- `CANCELLED` (server closed the stream normally, e.g. keepalive timeout or server rotation) is now logged at `INFO` instead of `WARNING`
- `UNAUTHENTICATED` reconnects handled by the automatic token refresh are now logged at `INFO` instead of `WARNING`

## [0.3.0] - 2026-05-12

### Added
- `NotifierStream` health properties: `is_connected`, `last_event_at`, `stream_state`
- `NotifierStream` `debounce_s` parameter to coalesce rapid update bursts
- `MetricBucketStatus` enum exposed on `EnergyBucket.status` (was untyped `int`)
- `grpc_call()` context manager in `services` for consistent gRPC error translation and optional retry
- Structured `logging.getLogger(__name__)` across all modules (auth, client, transport, services, CLI)
- `QuiltStreamError` re-exported from the top-level `quilt_hp` package
- Shared model helpers (`_helpers.py`) for WiFi signal parsing and hardware lookup

### Changed
- `ScheduleEvent.hvac_mode` is now typed as `HVACMode` (was `int`)
- Token temp file created with `os.open(..., 0o600)` so permissions are secure from creation (no transient world-readable window)
- Signature cache in transport layer uses `weakref.WeakKeyDictionary` instead of `dict[int, bool]` — prevents unbounded growth and id-reuse bugs after GC
- `login()` clears the token cache so a re-login always fetches fresh credentials
- `_GrpcCallContext` avoids self-chaining when re-raising a `QuiltError` unchanged

### Fixed
- `EnergyBucket.has_missing_energy_value` now treats `None` (absent proto field) as missing, not just `NaN`; prevents `TypeError` in `SpaceEnergyMetrics.total_kwh`
- `MetricBucketStatus()` conversion in `get_energy_metrics` catches `ValueError` for unknown server values and falls back to `UNSPECIFIED` instead of raising
- `WeakKeyDictionary.get()` for the refresh-callback signature cache is now guarded against `TypeError` for non-weakrefable callables
- AUTO mode setpoint deadband clamp now runs before setpoint selection, ensuring the correct (clamped) value is sent to the device
- CLI settings `bool` coercion uses `isinstance(v, bool)` to avoid `bool("false") == True`
- Zero-value proto3 fields (0 °C temperature, 0 dBm WiFi signal, 0% humidity) are now preserved instead of being dropped as falsy
- `NotifierStream` reconnect subscription is now protected by an `asyncio.Lock` to prevent concurrent subscribe/reconnect races
- CLI enum lookups raise a clear error showing valid options on invalid input
- `auth.py` narrows broad `except Exception` to `except (QuiltAuthError, ClientError)` to avoid swallowing unexpected errors

## [0.2.2] - 2026-05-11

### Fixed
- Corrected mapping of outdoor units to indoor units in SystemSnapshot
- Fixed TUI interaction issues with button handling and bindings

## [0.2.1] - 2026-05-10

### Fixed
- Restored CI/release quality-gate stability by applying required `ruff format`
  updates in model files.

## [0.2.0] - 2026-05-10

## [0.1.4] - 2026-05-08

### Fixed
- `boto3.client()` was called synchronously inside async functions, causing a
  blocking HTTP request to the EC2 instance metadata service (IMDS) at
  `169.254.169.254` during credential resolution. This manifested as an
  `HTTPClientError` in Home Assistant's async event loop. The client is now
  created via `loop.run_in_executor()` like the subsequent API calls.

## [0.1.3] - 2026-05-08

### Fixed
- Regenerated gRPC stubs with `grpcio-tools==1.78.0` so the library works
  inside Home Assistant, which hard-pins `grpcio==1.78.0` in its package
  constraints. Previously the stubs were generated with 1.80.0 and raised
  `RuntimeError` at import time on older grpcio versions.

## [0.1.2] - 2026-05-08

## [0.1.1] - 2026-05-08

## [0.1.0]

### Added
- GitHub Actions release automation for SemVer tags (`vX.Y.Z`) that enforces quality gates, creates a GitHub Release, and publishes distribution artifacts to PyPI via trusted publishing
- Initial async client for Quilt cloud gRPC API
- Cognito OTP authentication with token caching
- HomeDatastoreService: spaces, indoor units, comfort settings, schedules
- SystemInformationService: system listing, energy metrics
- NotifierService: real-time streaming subscriptions
- CLI for interactive use (`quilt` command)
