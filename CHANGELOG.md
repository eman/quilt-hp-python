# Changelog

## [Unreleased]

### Added
- **Indoor-unit self-test:** `QuiltClient.start_self_test()` and `cancel_self_test()` wrap
  `DiagnosticService`, the app's "Run diagnostic test" (since app 1.0.33). They identify the
  unit as the app does, by its own serial. The test takes up to 30 minutes and its results go
  to Quilt, not the caller; follow progress with `IndoorUnit.is_under_test` / `test_state`.
- **Dial settings:** `QuiltClient.set_controller()` renames a Dial and/or switches the app's
  "Temperature sensor" setting (`uses_dial_temperature`: control the room to the Dial's
  reading, or to the indoor unit's own sensor). Verified against a live system. New
  `Controller.description` and `Controller.uses_dial_temperature`.
- **Actions:** `QuiltClient.apply_mode()`, `apply_temperatures()`, `apply_fan_speed()`,
  `apply_fan_angle()` and `apply_light()`, through the action API the Quilt app uses
  (`HomeActionService/SubmitAction`). One call changes any mix of rooms, indoor units or the
  whole house; lights take presets or a custom `RgbwColor`, and modes include `AWAY`. Each
  returns an `ActionOutcome` and raises the new `QuiltActionError` when the server reports a
  failure. New enums `ClimateMode`, `FanAngle` and `ActionResult`. Verified against a live
  system: fan speed, fan angle and light must address indoor units (rooms are expanded), and
  the wire's brightness field is a 0–1 fraction despite its name (the library takes 0–100).
- **Account (read-only):** `QuiltClient.list_system_users()`, `get_access_role()`,
  `list_pending_invitations()`, `get_partner_details()`, `get_data_sharing()`,
  `list_certified_partners()` and `list_user_tasks()`, with new models in
  `quilt_hp.models.account` (`SystemUsers`, `SystemUser`, `Invitation`, `PartnerDetails`,
  `PartnerProfile`, `SystemDataSharing`, `UserTask`, and the `AccessRole`,
  `DataSharingSetting`, `DataSharingState` and `UserTaskKind` enums). Each was checked
  against a live system; they never change anything.
- **`QuiltPreconditionError`** (a `QuiltError`), raised for gRPC `FAILED_PRECONDITION`, e.g.
  `list_certified_partners()` on a system with no address.
- **Hardware and creation details:** `IndoorUnit.unit_serial_number` (the unit's own
  `QN1-…` serial) and `smart_module_serial_number` (`QS1-…`, which is what `serial_number`
  has always held), `manufactured_at` on indoor units, outdoor units and Dials,
  `OutdoorUnit.port_count`, and `created_at` on rooms, indoor units, outdoor units, Dials and
  Smart Modules. They are kept when stream updates are merged.
- **Wi-Fi link details:** `WifiInfo.connection_state` (new `WifiConnectionState` enum),
  `noise_dbm`, `snr_db`, `rx_invalid_fragments`, `tx_excessive_retries` and `ipv6`, and
  `Controller.hosted_wifi` with the Dial's home-network link in full.
  `WifiInfo.connected` now follows the connection phase (`COMPLETED`), using the network
  name only when no phase is reported, and a Wi-Fi record is kept whenever the interface
  reports anything, so a disconnected or scanning Dial or Smart Module is no longer `None`.
- `QuiltSmartModule`, `WifiInfo` and `QsmSensors` are exported from `quilt_hp.models`.
- The TUI's Devices screen shows the indoor unit's own serial alongside its Smart Module's,
  manufacture dates, outdoor-unit port use and Wi-Fi signal-to-noise; `quilt info --output
  json` includes the serials, manufacture dates and port count.
- **TUI Energy screen** (`e` from Home): the whole house today by hour and over the last week,
  and each room's use today, yesterday, over 7 and 30 days, with its share of the house.
- **TUI help** (`?` anywhere): every key for every screen, generated from the screens' key
  bindings so it stays accurate.
- **[Use the terminal UI](docs/how-to/use-the-tui.md)**, a tour of every screen and key.
  Its screenshots are the render-test snapshots, kept in sync by
  `scripts/update_tui_screenshots.py` and checked by a test.
- **TUI Room screen, redesigned.** Five tabs, switched with `1`–`5`; `[` and `]` move to the
  previous or next room on the same tab.
  - *Overview*: the room's temperature and what it's doing, humidity, power, Dial state,
    occupancy with its auto-away timing, the active comfort setting and how it was set, and a
    **controls list** (mode, cool and heat setpoints, fan, louver, light): `↑`/`↓` choose,
    `←`/`→` change, `enter` types a setpoint. Today's hourly energy below.
  - *Climate*: air temperatures from each sensor, refrigerant pipes, humidity and dew point;
    the indoor unit's state, fan, power, capacity, COP, outdoor-unit share and only the
    conditions that are active; presence from each radar. `r` adds raw telemetry.
  - *Schedule*: the week as a grid (view only).
  - *Energy*: today, yesterday, 7 and 30 days, today by hour, and the last 14 days.
  - *Devices*: the room's indoor unit, Dial and outdoor unit with their details.
  - **Room settings** (`s`): auto-away timing, the Away temperatures, the presence sensor's
    detection range and mounting height, and the light's default brightness, as typed fields
    with an explicit Save. These replace the hidden `[ ] { }`, `ctrl`+arrow and `alt` keys.
- **TUI Home screen** (replaces the dashboard). A rooms table (temperature, humidity, target,
  what the room is doing, occupancy, today's energy, alerts), a summary of the selected room
  (dew point, fan, power, COP, outdoor-unit share, Dial display and radar), and a **Needs
  attention** panel listing offline devices, faults, tests in progress, firmware updates and
  paused schedules. `m` cycles the selected room's mode and `+`/`−` adjust the setpoint the
  mode uses (in Auto, the one nearer the room temperature) without opening the room.
- **TUI Devices screen** (replaces the System screen, `d` from Home). Every indoor unit, Dial,
  remote sensor and outdoor unit grouped by room, with online status (offline devices show how
  long ago they last reported, and no stale link data), Wi-Fi signal and mesh health,
  firmware and update progress. The selected device's details are shown below; `r` adds its
  raw telemetry (radar channels, light and accelerometer readings, board temperatures).
- **Typed enums for raw integers.** `IndoorUnitHvacInputs.ambient_temperature_source` is now
  an `AmbientTemperatureSource` (`DEFAULT` = the indoor unit's own sensor, `CONTROL` = the
  Dial). `SoftwareUpdateInfo.state`, `.status` and `.progress_unit` are now
  `SoftwareUpdateState` (`IDLE`, `DOWNLOADING`, `TRANSFERRING`, `INSTALLING`, `REBOOTING`),
  `SoftwareUpdateStatus` (`OK`, `UNKNOWN_ERROR`) and `SoftwareUpdateProgressUnit` (`PERCENT`,
  `BYTES`, `SECONDS`), with the values confirmed against the app. All are `IntEnum`s, so
  comparisons with integers keep working; values this release doesn't know become
  `UNSPECIFIED`. `SoftwareUpdateState.UNKNOWN` and `SoftwareUpdateStatus.UNKNOWN` remain as
  aliases of `UNSPECIFIED`.
- **TUI render tests.** Every screen is snapshot-tested at 100×30 and 160×45, rendered offline
  from a scrubbed capture of a real system (`tests/fixtures/system_snapshot.bin`).
- **Diagnostics view.** `QuiltClient.get_diagnostics()` and
  `SystemSnapshot.diagnostics()` return a new `SystemDiagnostics` — the
  installer-style diagnostic picture assembled from data the cloud API already
  returns on the indoor units: the per-IDU fault/condition matrix (including the
  outdoor-unit / refrigerant conditions surfaced through each IDU, e.g.
  `outdoor_unit_communication_error`, `defrost_cycle`, `oil_return`),
  refrigerant-circuit temperatures (coil / gas-pipe / liquid-pipe / inlet /
  outlet) and humidity, and per-unit power. New models `IndoorUnitDiagnostics`,
  `OutdoorUnitDiagnostics`, `SystemDiagnostics`, plus `IndoorUnitConditions.active`
  / `.states()` helpers. New CLI command `quilt diagnostics` (with `--faults-only`
  and `--output json`). The outdoor unit's own raw sensors (compressor Hz,
  pressures, discharge temp) remain withheld from the cloud plane and are flagged
  as such rather than reported.
- `QuiltClient.request_fast_updates(reason=..., system_id=...)` and the
  underlying `CommandService.request_fast_updates()` wrapper — calls the new
  `core.protos.home_datastore.CommandService/RequestFastUpdates` RPC to ask the
  cloud to raise a system's telemetry cadence. This is the same lever the Quilt
  mobile app pulls (new in app versionCode 255) when the user is active or a
  device's local mesh is degraded; the effect is a faster stream of updates over
  `NotifierStream`. New `FastUpdateReason` enum (`UNSPECIFIED`,
  `LOCAL_COMMS_UNHEALTHY`, `USER_ACTIVITY`) in `quilt_hp.models.enums`.
- **Dial display, radar and light telemetry on `Controller`**: `view_state`
  (`ControllerViewState`: SLEEP / GLANCE / ACTIVE / INTERACTING), `screen_brightness`,
  `radar_target_detected` / `radar_phase_detected` (the Dial's own mmWave radar, separate
  from the indoor unit's), `ambient_light_lux`, `orientation` (`ControllerOrientation`),
  `humidity_percent`, `power_w`, board temperatures and `accelerometer_raw`, plus the
  `display_on` and `presence_detected` properties. The server has always sent these; the old
  protos dropped them. Shown by `quilt values` and in `quilt info --output json`.
- The vendored protos (`quilt_hp._proto`) were audited against the Quilt app 1.0.33 and
  validated against the live server: every server response decodes with no unknown fields.
  New: `quilt_actions.proto` (`HomeActionService/SubmitAction`), `quilt_device_config.proto`
  (`DeviceConfigurationService`), IDU test/commissioning and climate state, demand-response,
  ducted-zone, air-handler and automation entities, and the notifier payload
  (`Notification` / `HomeDatastoreObjectDiff`). `HomeDatastoreService` now declares the full
  Get/Create/Update/Delete/List set the server implements for every entity (105 methods; the
  app uses 32); `core.protos.system.SystemService` likewise. `List*` requests take an
  AIP-160 filter such as `header.system_id="<uuid>"`.
  `scripts/sync_protos_from_parent.py` documents how the protos are refreshed.

- **Room occupancy:** `Space.occupancy` (`SpaceOccupancy`) and the `Space.occupancy_state`
  property: the room's own auto-away decision, the value its away/return setback acts on.
- **Outdoor-unit share:** `IndoorUnitPerformanceMetrics.odu_usage_fraction`, the share of the
  outdoor unit attributed to each indoor unit, for apportioning energy per room.
- **Indoor-unit climate:** `IndoorUnit.climate` (`IndoorUnitClimate`: inlet dew point, validity,
  calculated ambient) and the `IndoorUnit.dew_point_c` property.
- **Indoor-unit test state:** `IndoorUnit.test_state` (`IndoorUnitTestState` with the new
  `IndoorUnitTestMode` / `IndoorUnitTestCoordination` / `IndoorUnitTestPhase` enums),
  `IndoorUnitState.test_mode`, and the `IndoorUnit.effective_test_mode` / `is_under_test`
  properties (health check, commissioning), which use whichever of `test_state` and
  `state.test_mode` was updated more recently. `quilt diagnostics` shows dew point, outdoor-unit share and any active test;
  `quilt info --output json` includes all four.
- **Single-object fetches:** `QuiltClient.get_space` / `get_indoor_unit` / `get_outdoor_unit` /
  `get_controller` / `get_quilt_smart_module` / `get_comfort_setting` / `get_remote_sensor` /
  `get_controller_remote_sensor` / `get_schedule_day` / `get_schedule_week` /
  `get_software_update_info`, and per-system `list_*` on `HomeDatastoreService` (filtered
  server-side).
  They use Get/List RPCs the Quilt app never calls but the server implements; results lack
  hardware attributes, so merge them into a snapshot with `apply_*`.
- **Configuration version:** `SystemSnapshot.version` / `version_at` and
  `QuiltClient.get_system_version()` (a metadata-only fetch, ~14 bytes). The version advances on
  writes to controls, settings or configuration (including auto-away switching a comfort
  setting), not on telemetry, so it cheaply detects a snapshot whose configuration is stale.
- `NotifierStream.on_delete(callback)` and `SystemSnapshot.remove(kind, entity_id)`; `StreamEvent`
  gains `notification_type` (new `NotificationType` enum) and `system_version` (the server
  currently sends 0, so it is None in practice).

- **TUI shows the new telemetry.** Room detail: the Dial panel adds display state and brightness,
  radar presence, ambient light, humidity, power draw and main/power-board temperatures (the
  "PCB A / B" row is now labelled "Encoder / SoC"); the sensors panel adds dew point and an
  indoor-unit test indicator; Energy / Efficiency adds the outdoor-unit share. The System screen's
  Dials table adds Display, Radar and Light columns, and its header shows when the configuration
  last changed.
- **CLI.** `quilt info --output json` adds `version` / `version_at`, and per Dial `display_on`,
  `presence_detected` and the encoder, SoC, main-board and power-board temperatures; the `info`
  summary shows the configuration change time and each Dial's display state and offline status.
  `quilt values` adds `display_on`, `presence_detected` and `power_w`.

### Changed
- **TUI Room keys:** no more upper/lower-case pairs. `+`/`−` change the setpoint the mode uses
  (as on Home), `f` fan, `v` louver (was `l`), `l` light (was `L`), `s` settings. Control
  changes from Home and Room share one queue per room.
- **TUI keys:** `d` opens Devices (it toggled the theme; change the theme from the command
  palette, `ctrl+p`). The chosen theme is now remembered by name, so palette themes such as
  Nord survive a restart; older settings that only recorded light or dark still apply.
  Pausing schedules for the whole house moved from `p` on the Room and System screens to `P`
  on Home, and now asks for confirmation; `p` on the Room screen does nothing.
- **TUI controls:** quick repeated presses build on each other (two `+` presses from 24 °C
  reach 25 °C): presses for a room are applied one at a time, each from the result of the
  last. `+`/`−` do nothing in Dry, which has no setpoint the server accepts.
- The TUI moved from `quilt_hp/cli/tui.py` into a `quilt_hp/cli/tui/` package (one module per
  screen, plus formatting and view helpers) and is now type-checked and included in test
  coverage. `from quilt_hp.cli.tui import QuiltApp` is unchanged. `QuiltApp` accepts optional
  `client` and `settings_store` arguments for tests and embedding.

### Fixed
- `Controller.is_online` reported an offline Dial as online: the server sends an offline Dial
  with no state at all, and the library assumed "no timestamp" meant online. It now matches
  the app — no state report in the last 5 minutes means offline.
- The TUI's Devices screen labelled the Dial's temperature-sensor setting "Zone sensor"; it
  now says "Temperature sensor" and whether the Dial controls the room.
- The TUI's Devices screen and the models reference showed an indoor unit's Smart Module
  serial as the unit's serial. `docs/reference/models.md` also still showed
  `SoftwareUpdateInfo.state`, `status` and `progress_unit` as integers, and had no section
  for `QuiltSmartModule` or `WifiInfo`.
- **TUI:** an offline Dial's last display, radar and light readings were shown as current on
  the System screen and the room's Dial panel; they now read "⚠ offline 8 h".
- **TUI:** the hourly energy chart put today's usage under the wrong hour (leading idle hours
  rendered as spaces and were dropped) and its axis didn't match the bars. Bars and axis now
  share one grid, two columns per hour.
- **TUI:** rows without data showed internal widget ids as labels (`p-odu-freq`, `Wifi Ip`).
- **TUI:** values were parsed as Rich markup, so a room, device or Wi-Fi name containing
  `[…]` was mis-rendered; long values wrapped onto the next row instead of truncating.
- **TUI:** raw values reached the screen: "Ambient Source: 2" (now "Dial"), "Active (ACTIVE)"
  for comfort presets, "Safety Heating: Unspecified" (the device treats it as on; now
  "On (default)"). Standby and Fan schedule events showed the system's setpoint limits
  (8 °C / 40 °C) as if they were settings; events now show only the setpoints their mode uses.
- **TUI:** the dashboard's 60-second refresh method was named `_auto_refresh`, overriding a
  Textual internal of the same name.
- `quilt info --output json` reports software-update `state`, `status` and `progress_unit` as
  names instead of integers.
- Two tests used real device serial numbers; they now use test values.
- A comment on `WifiState.ssid` in `quilt_hds.proto` (and the generated stub docstring) named
  a real Wi-Fi network; it now just says "network name".
- `quilt info --output json` reported indoor-unit `occupancy_state` as a raw integer; it is now the
  enum name (`DETECTED`, `UNDETECTED`), matching spaces.
- `quilt info` / `quilt values` summaries printed unrounded floats (e.g. `25.73853302001953°C`);
  temperatures, humidity, power, light and brightness are now formatted.
- `docs/how-to/cli-scripting.md` documented commands and options that don't exist (`quilt
  snapshot`, `set-space`, `set-all-spaces`, `logout`, `energy --days`, JSON energy output) and
  JSON keys the CLI never emitted, and its Prometheus example piped JSON into a heredoc that
  replaced stdin. It is rewritten against the real CLI, and every example was run against a live
  system.
- `docs/reference/models.md` documented several dataclasses with fields that don't exist
  (`IndoorUnit.model_name`, `IndoorUnitState.target_temp_c`, `RemoteSensorState`, renamed
  `IndoorUnitSettings`/`IndoorUnitControls` fields) and omitted many real ones; every documented
  dataclass now matches the code.
- Deleted objects are no longer delivered as updates: `NotifierStream` ignored the notification
  type, so a DELETED event reached `on_*_update` callbacks and `snapshot.apply_*` re-added the
  object. Deletions (DELETED, and CHILD_DELETED, which carries the removed child on its parent's
  topic) now go only to `on_delete`, and cancel any pending debounced update for the object.
  `SystemSnapshot.remove` also ignores later `apply_*` calls for the removed object, so an update
  callback already in flight cannot re-add it. The TUI drops deleted objects from its snapshot.
- `Controller.is_online` now works: it read `ControllerState.updated_ts` from field 1, which the
  server never sends, so it always returned True. The timestamp is field 15. A Dial that has
  stopped reporting for 5 minutes now reads offline.
- `UserService.get_user_attributes()` always returned `DeclaredUserType.UNSPECIFIED`: the RPC
  wraps the attributes (`GetUserAttributesResponse{user_attributes}`), which the old proto
  did not model.
- `NotifierStream` now decodes events with the generated messages
  (`SubscribeResponse.event` → `NotifierEvent{topic, payload: Any}` → `Notification`; the Any
  type URL is `type.googleapis.com/core.protos.home_datastore.Notification`) instead of
  hand-parsing bytes against a schema that was one nesting level off. Callbacks and
  `StreamEvent` are unchanged; events for entity types without a model (e.g. automations)
  still arrive with `raw_bytes`, now the `Notification` bytes.

### Migration (raw `quilt_hp._proto` users only — the `quilt_hp.models` API is unchanged)
Field and enum-value names in the vendored protos now use the app's names. Wire format is
unchanged except where noted.

| Where | Old | New |
|---|---|---|
| `UpdateSpaceRequest` / `UpdateIndoorUnitRequest` | `diff` | `space` / `indoor_unit` |
| `Get*`/`Delete*` request ids | `id`, `remote_sensor_id`, `schedule_day_id`, `schedule_week_id`, ... | `object_id` |
| `SpaceState` | `setpoint_temperature_c` | `temperature_setpoint_c` |
| `IndoorUnitPresenceState` | `sensor0_presence` / `sensor1_presence` | `sensor_0_presence` / `sensor_1_presence` |
| `ControllerState` | `ambient_temperature_c`, `temperature_f3`/`f4`/`f5` | `sht4x_temperature_c`, `encoder_temperature_c`, `soc_temperature_c`, `calculated_ambient_temperature_c` |
| `ControllerState.updated_ts` | field 1 (never sent) | field 15 (**wire**) |
| `Controller` / `QuiltSmartModule` | `local_comms_status` | `local_comms_health` |
| `PartnerDetails` | `organization_id` / `organization_name` | `partner_organization_id` / `partner_organization_name` (+ `partner_tier`) |
| `OccupancyState` values | `OCCUPANCY_STATE_*` | `OCCUPANCY_*` |
| `LightState` / `LightAnimation` values | `LIGHT_STATE_*` / `LIGHT_ANIMATION_*` | `LED_STATE_*` / `INDOOR_UNIT_LED_ANIMATION_*` |
| `ConditionState` | one shared proto enum | one enum per condition field (e.g. `DefrostCycleState`), same 0/1/2 values; `quilt_hp.models.ConditionState` is unchanged |
| `SubscribeResponse` | `notifier_events`/`control_events`/`system_events` on the response | on `response.event`; `NotifierEvent.topic` is a string, `.payload` an `Any` (**wire layout clarified**) |
| `GetUserAttributes` | returned `UserAttributes` | returns `GetUserAttributesResponse` (**wire**) |
| `JoinPartnerOrganization` / `LeavePartnerOrganization` | `*Response` wrappers | `PartnerDetails` / `Empty` (**wire**) |
| `LedScheduleEvent` | fields 3–5 color/brightness/animation | `schedule_execution=3, led_state=4, led_brightness_percent=5, led_color_code=6, led_animation=7` (**wire**) |
| `Get{IndoorUnitHardware,ControllerHardware,QuiltSmartModule}Request.field_mask` | `google.protobuf.FieldMask` | per-entity `include_*` mask messages (**wire**) |
| `List*Request` | `filter = 1` | `filter = 2` (field 1 is ignored by the server) (**wire**) |
| `system.System` | `{ id = 1; created_ts = 2 }` | `{ EntityMetadata header = 1; ... }` (**wire**) |
| `DeviceType` (pairing) | CONTROLLER=5, ... | `DEVICE_TYPE_CONTROLLER=6`, renumbered from 4 up (**wire**) |
| `WifiScan`/`WifiConfiguration.security_type`; `DeviceConfigurationRequest.request_timestamp`/`device_configuration` | | `key_mgmt`; `request_ts` / `device_config` |
| `Address` | `address_line_1` / `address_line_2`, `region_code` | `address_line1` / `address_line2`, `state_province_region` |
| `Address` | `latitude`/`longitude` double; `geocode_source = 10`, `geocode_override = 11` | `float` (**wire**); `geocode_override = 10`, `raw_geocoded_response = 11`, `geocode_source = 12` (**wire**) |
| `GeocodeSource` enum | `GeocodeSource`, `GEOCODE_SOURCE_*` | `GeocodeService`, `GEOCODE_SERVICE_*` |
| `SetAddressResponse` | `bool success = 1` | empty message (success is a non-error status) |
| `SystemEvent` (notifier) | `type` | `system_event_type` |
| `core.protos.app.SystemService` | declared | removed: the server answers UNIMPLEMENTED (use `core.protos.system.SystemService`) |

## [0.5.7] - 2026-07-20

### Added
- `IndoorUnit.presence_detected` — realtime room presence as a single bool: True
  if either radar channel reports DETECTED (mirrors the vendor app's
  `combinedSensorPresence`), False if neither channel is DETECTED and at least one
  is UNDETECTED, None when the IDU is offline or the radar hasn't reported. This
  is the fast (seconds-latency) counterpart to the debounced
  `effective_occupancy_state` (auto-away decision, ~3 min to set / ~20 min to
  clear by default). ([#21])

### Changed
- Clarified presence/occupancy semantics throughout ([#21]):
  `IndoorUnitPresence.sensor0_presence`/`sensor1_presence` are the two detection
  channels of the IDU's single mm-wave radar (they move in lockstep in practice;
  channel semantics unconfirmed) — not two physical sensors. TUI labels renamed
  accordingly: "Radar L"/"Radar R" → "Radar ch 0"/"Radar ch 1", and "Occupancy" →
  "Occupancy (auto-away)". Docs: removed the phantom
  `IndoorUnitState.presence_detected` field from the model reference, documented
  the three-tier presence model (raw channels / realtime presence / derived
  occupancy), and fixed the Home Assistant guide, which previously mapped the
  *derived* occupancy state to an entity named "Presence".

[#21]: https://github.com/eman/quilt-hp-python/issues/21

## [0.5.6] - 2026-07-04

### Fixed
- **`LocalCommsStatus` fields were mislabeled** (previously guessed from limited
  captures). Corrected to the verified field semantics: field 2 `health` →
  `status`, field 3 `link_state` → `visible_devices_count`, field 4 `version` →
  `expected_devices_count`, field 5 `health_changed_ts` →
  `last_session_change_ts`, field 6 `connection_state` (int32) → `reason`
  (`LocalCommsHealthReason` enum). Decoding still worked by field number, but the
  model exposed wrong names/semantics and discarded the reason diagnostics.
  `QuiltSmartModule`/`Controller` now expose `local_comms_visible_devices`,
  `local_comms_expected_devices`, `local_comms_reason`, and
  `local_comms_last_session_change` (replacing `local_comms_link_state`,
  `local_comms_connection_state`, and `local_comms_version`).

### Added
- `IndoorUnit` now exposes `model_sku`, `serial_number`, and `firmware_version`,
  resolved from `HomeDatastoreSystem.indoor_unit_hardware` (previously discarded).
  This mirrors `OutdoorUnit` and `Controller` and lets downstream consumers (e.g.
  the Home Assistant integration) populate IDU device serial/firmware.
- CLI `set` command gained a `--fan` option (`AUTO`, `QUIET`, `LOW`, `MEDIUM`,
  `HIGH`, `BLAST`) that applies the chosen fan speed to every indoor unit in the
  target space.
- `SystemSnapshot.indoor_units_for_space()` returns all indoor units linked to a
  space (accepts a `Space` or space-ID string).
- `LocalCommsHealthReason` enum (12 values). `ZENOH_SESSION_DOWN`
  identifies the local mesh transport as **Eclipse Zenoh**, not NATS (port 7447
  is Zenoh's default).
- `IndoorUnitConditions.compressor_minimum_run_time` (proto field 13).
- Marked `SpaceSettings.safety_heating=9` confirmed (was "unconfirmed").

### CI
- Docs deploy workflow upgraded to the current Node 24 GitHub Pages actions
  (`configure-pages@v6`, `upload-pages-artifact@v4`, `deploy-pages@v5`),
  removing the deprecated Node 20 runtime path.
- Docs deploy now retries `deploy-pages` once on transient GitHub Pages backend
  failures, failing the job only if both attempts fail.

## [0.5.5] - 2026-07-03

## [0.5.4] - 2026-07-03

Fixes all findings from a full architecture/code/performance/bug-hunt evaluation.

### Critical

- **Proto3 absence detection never fired on real protos.** Truthiness and
  getattr-with-default checks always pass on generated messages (unset
  sub-messages return truthy default instances), so sparse stream diffs zeroed
  room state, IDU controls, sensor readings, and controller temperatures on
  merge. All model parsing now uses `HasField`-based helpers, and
  `SystemSnapshot.apply_*` preserves identity/relationship fields, controller
  temperatures, ODU telemetry, and QSM LED state. New test suite
  (`tests/test_models_real_proto_merge.py`) reproduces the notifier stream's
  serialize/parse path with real generated protos.
- **Transport UNAUTHENTICATED retry was dead code.** In `grpc.aio`, awaiting the
  interceptor continuation returns the call object; `AioRpcError` only surfaces
  when the call is awaited — so token refresh/retry never executed and clients
  broke permanently ~1h after token expiry. The interceptor now awaits the call
  and retries once. Tests updated to model real `grpc.aio` semantics.

### High

- Stream reconnect backoff/budget reset after a healthy connection (routine LB
  stream recycling no longer escalates to permanent 60s delays or kills the
  stream after N lifetime disconnects); non-gRPC failures reconnect and surface
  via `on_error` instead of dying silently; malformed events are skipped;
  jitter added; prompt reconnect after successful token refresh.
- `authenticate()` no longer returns a locally-unexpired token the server just
  rejected; rotated Cognito refresh tokens are persisted; expiry measured from
  token receipt.
- `grpc_call` passes `CancelledError` through untranslated (asyncio.timeout/
  cancellation semantics restored).
- TUI: fatal stream death now shows a disconnect indicator and auto-recovers;
  first-time users get an OTP modal; boot failures show an error screen
  instead of a stuck spinner.

### Medium / Low

- Unified error translation: all hds/user RPCs route through `grpc_call`;
  `UNAVAILABLE`/`DEADLINE_EXCEEDED` → `QuiltConnectionError` and `NOT_FOUND` →
  `QuiltNotFoundError` everywhere.
- Single-flight guards on token refresh and cold snapshot fetch;
  `get_system_id(home=...)` no longer poisons the default-system cache;
  `close()` stops tracked streams; duplicate authorization metadata
  eliminated.
- Stream API: `on_connected` callback, unsubscribe handles from all `on_*`
  registrations, `apply_software_update_info`, descriptor-derived wire-scan
  field numbers.
- CLI/TUI: app-owned snapshot (stacked screens no longer go stale), cursor
  preservation, setpoint bounds, energy period validation, app-level °C/°F,
  LED brightness restoration, 0.0 readings rendered correctly, token store
  corruption recovery + fsync + flock, config dir 0700, dead code removal.
- Docs: README no longer demonstrates raw-stream usage; stream/token types
  re-exported at package top level; stale OutdoorUnit/Controller reference
  listings corrected; contradictory proto comments fixed.

Intentionally unchanged: Python >= 3.14 floor and boto3 dependency (HA 2026.3+
runs Python 3.14).

## [0.5.3] - 2026-06-30

## [0.5.2] - 2026-06-30

### Fixed
- `_make_cognito_client()` now creates the boto3 client with EC2 instance
  metadata (IMDS) credential discovery disabled and explicit connect/read
  timeouts. On non-EC2 hosts (e.g., Home Assistant Yellow) the IMDS endpoint
  at 169.254.169.254 may accept TCP connections but never respond, causing the
  calling thread to block for the full OS-level TCP timeout — well beyond the
  20-second setup window — and triggering a spurious `ConfigEntryNotReady`.

## [0.5.1] - 2026-06-30

### Fixed
- `SpaceControls.display_setpoint_str()` — removed dead unreachable code in the
  fallback branch; `temperature_setpoint_c` is typed `float` so the `None`-guard
  lines were never executed (confirmed by coverage)
- `SystemSnapshot.apply_outdoor_unit()` — refactored to collect field patches into
  an `updates` dict and call `dataclasses.replace()` once, consistent with all other
  `apply_*` methods; previously called `replace()` twice in sequence, creating an
  unnecessary intermediate object
- `QuiltClient.close()` now sets `self._token = None`; previously left a stale token
  accessible via `get_current_token()` after the channel was closed

### Changed
- `invoke_refresh_callback` (formerly `_invoke_refresh_callback`) extracted from
  `transport.py` and `services/streaming.py` into a single shared implementation in
  `tokens.py`; the streaming copy lacked the `WeakKeyDictionary` signature cache,
  causing `inspect.signature()` to be called on every token-refresh event
- `FanSpeed.to_wire()` and `LouverAngle.to_wire()` now reference module-level
  constant dicts (`_FAN_SPEED_WIRE_MAP`, `_LOUVER_ANGLE_WIRE_MAP`) instead of
  re-allocating the mapping on every call
- `_id_variants()` moved from `models/system.py` into `models/_helpers.py` and
  reused by `lookup_hardware()`; eliminates duplicated ID-normalisation logic
- `QuiltClient.invalidate_snapshot()` log level changed from `WARNING` to `DEBUG`

## [0.5.0] - 2026-06-04

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
