# Changelog

## [Unreleased]

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
