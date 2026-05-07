# Public API reference

This page is generated from `src/quilt_hp` by
`scripts/generate_public_api_reference.py`.

It documents public modules, classes, methods, and functions with
their Python signatures.

## `quilt_hp`

### Exports

- `Environment(*values)` *(class)*
- `QuiltAuthError()` *(class)*
- `QuiltClient(email: 'str', *, home: 'str | None' = None, environment: 'Environment' = <Environment.PROD: 'prod'>, snapshot_ttl_s: 'float' = 0, token_store: 'TokenStoreLike | None' = None, token_refresh_hooks: 'TokenRefreshHooks | None' = None, token_refresh_policy: 'TokenRefreshPolicy | None' = None) -> 'None'` *(class)*
- `QuiltConnectionError()` *(class)*
- `QuiltError()` *(class)*
- `QuiltNotFoundError()` *(class)*
- `__version__`

## `quilt_hp._paths`

### Functions

- `app_config_dir() -> 'Path'`

## `quilt_hp.auth`

### Functions

- `authenticate(email: 'str', otp_callback: 'OtpCallback | None' = None, token_store: 'TokenStoreLike | None' = None, *, refresh_context: 'TokenRefreshContext | None' = None, refresh_hooks: 'TokenRefreshHooks | None' = None, refresh_policy: 'TokenRefreshPolicy | None' = None) -> 'str'`

## `quilt_hp.const`

### Functions

- `grpc_host(env: 'Environment') -> 'str'`

### Classes

#### `Environment`


## `quilt_hp.exceptions`

### Classes

#### `QuiltAuthError`


#### `QuiltConnectionError`


#### `QuiltError`


#### `QuiltNotFoundError`


#### `QuiltStreamError`


## `quilt_hp.models`

## `quilt_hp.models.comfort`

### Classes

#### `ComfortSetting`

- `__init__(self, id: 'str', system_id: 'str', space_id: 'str', name: 'str', type: 'ComfortSettingType', hvac_mode: 'HVACMode', heating_setpoint_c: 'float', cooling_setpoint_c: 'float', fan_speed: 'FanSpeed', louver_mode: 'LouverMode' = <LouverMode.UNSPECIFIED: 0>, louver_fixed_position: 'float' = 0.0) -> None`
- `from_proto(cls, proto: 'object') -> 'ComfortSetting'`

## `quilt_hp.models.controller`

### Classes

#### `Controller`

- `__init__(self, id: 'str', system_id: 'str', space_id: 'str', name: 'str', raw_thermistor_c: 'float', pcb_temperature_a_c: 'float', pcb_temperature_b_c: 'float', calibrated_ambient_c: 'float', wifi_ssid: 'str | None', wifi_ip: 'str | None', wifi_signal_dbm: 'int | None', wifi_freq_mhz: 'int | None' = None, wifi_last_seen: 'datetime | None' = None, ap_wifi: 'WifiInfo | None' = None, p2p_wifi: 'WifiInfo | None' = None, remote_sensor_mode: 'RemoteSensorControlMode' = <RemoteSensorControlMode.UNSPECIFIED: 0>, software_update_info_id: 'str | None' = None, firmware_update_info_id: 'str | None' = None, serial_number: 'str | None' = None, model_sku: 'str | None' = None, firmware_version: 'str | None' = None, state_updated_at: 'datetime | None' = None) -> None`
- `ambient_temperature_c` *(property)*
- `from_proto(cls, proto: 'object', hw_map: 'dict[str, object] | None' = None) -> 'Controller'`
- `is_online` *(property)*
- `wifi_band` *(property)*

## `quilt_hp.models.energy`

### Classes

#### `EnergyBucket`

- `__init__(self, start_time: 'datetime', energy_kwh: 'float', status: 'int') -> None`

#### `SpaceEnergyMetrics`

- `__init__(self, space_id: 'str', buckets: 'list[EnergyBucket]') -> None`
- `total_kwh` *(property)*

## `quilt_hp.models.enums`

### Classes

#### `BoostMode`


#### `ComfortSettingOverride`


#### `ComfortSettingType`


#### `ConditionState`


#### `FallbackControlCommand`


#### `FanSpeed`

- `from_wire(cls, mode: 'int', percent: 'float') -> 'FanSpeed'`
- `to_wire(self) -> 'tuple[int, float]'`

#### `HVACMode`


#### `HVACState`


#### `HvacControllerType`


#### `LedAnimation`


#### `LightPreset`


#### `LightState`


#### `LouverAngle`

- `from_wire(cls, position: 'float') -> 'LouverAngle'`
- `to_wire(self) -> 'float'`

#### `LouverMode`


#### `OccupancyMode`


#### `OccupancyState`


#### `Presence`


#### `RemoteSensorControlMode`


#### `SafetyHeatingMode`


## `quilt_hp.models.indoor_unit`

### Classes

#### `IndoorUnit`

- `__init__(self, id: 'str', system_id: 'str', space_id: 'str', outdoor_unit_id: 'str | None', hardware_id: 'str', qsm_id: 'str | None', settings: 'IndoorUnitSettings', controls: 'IndoorUnitControls', state: 'IndoorUnitState', hvac_inputs: 'IndoorUnitHvacInputs | None', conditions: 'IndoorUnitConditions | None', performance_data: 'IndoorUnitPerformanceData | None', performance_metrics: 'IndoorUnitPerformanceMetrics | None', presence: 'IndoorUnitPresence | None', occupancy: 'IndoorUnitOccupancy | None', firmware_update_info_id: 'str | None' = None, commands: 'IndoorUnitCommands | None' = None) -> None`
- `effective_occupancy_state` *(property)*
- `from_proto(cls, proto: 'object') -> 'IndoorUnit'`
- `is_online` *(property)*
- `led_on` *(property)*

#### `IndoorUnitCommands`

- `__init__(self, fallback_control_command: 'FallbackControlCommand') -> None`

#### `IndoorUnitConditions`

- `__init__(self, mode_conflict: 'int', anti_cold_wind: 'int', abnormal_outdoor_air_temperature: 'int', hvac_mode_switching_delay: 'int', defrost_cycle: 'int', safety_heating: 'int', oil_return: 'int', modbus_communication_error: 'int', coil_preheat: 'int', mode_conflict_avoidance: 'int', outdoor_unit_communication_error: 'int') -> None`
- `any_active` *(property)*

#### `IndoorUnitControls`

- `__init__(self, fan_speed: 'FanSpeed', louver_mode: 'LouverMode', louver_fixed_position: 'float', led_color_code: 'int', led_brightness: 'float', led_animation: 'LedAnimation', led_state: 'LightState' = <LightState.UNSPECIFIED: 0>, fan_speed_mode_raw: 'int' = 0) -> None`
- `light_on` *(property)*

#### `IndoorUnitHvacInputs`

- `__init__(self, external_ambient_temperature_c: 'float', ambient_temperature_source: 'int', temperature_setpoint_c: 'float', hvac_mode: 'HVACMode', hvac_state: 'HVACState', hvac_controller_type: 'HvacControllerType' = <HvacControllerType.UNSPECIFIED: 0>) -> None`

#### `IndoorUnitOccupancy`

- `__init__(self, occupancy_state: 'int') -> None`

#### `IndoorUnitPerformanceData`

- `__init__(self, measurement_interval_s: 'float', energy_measurement_j: 'float', hvac_mode: 'HVACMode', hvac_state: 'HVACState', actual_fan_speed_rpm: 'float', outlet_temperature_c: 'float', inlet_temperature_c: 'float', inlet_humidity_pct: 'float', coil_temperature_c: 'float', gas_pipe_temperature_c: 'float', liquid_pipe_temperature_c: 'float') -> None`
- `energy_kwh` *(property)*

#### `IndoorUnitPerformanceMetrics`

- `__init__(self, capacity_w: 'float', coefficient_of_performance: 'float', hvac_power_w: 'float', led_power_w: 'float', hvac_mode: 'HVACMode', hvac_state: 'HVACState', measurement_duration_s: 'float' = 0.0, energy_total_j: 'float' = 0.0, hvac_energy_j: 'float' = 0.0, led_energy_j: 'float' = 0.0) -> None`

#### `IndoorUnitPresence`

- `__init__(self, sensor0_presence: 'Presence', sensor1_presence: 'Presence') -> None`

#### `IndoorUnitSettings`

- `__init__(self, name: 'str', description: 'str', light_brightness_default_percent: 'float', presence_fence_left_m: 'float', presence_fence_right_m: 'float', presence_fence_forward_m: 'float', radar_sensor_distance_from_floor_m: 'float') -> None`

#### `IndoorUnitState`

- `__init__(self, hvac_mode: 'HVACMode', hvac_state: 'HVACState', ambient_temperature_c: 'float', ambient_humidity_percent: 'float', fan_speed_rpm: 'float', fan_speed_setpoint_rpm: 'float', presence_detection_level: 'float', temperature_setpoint_c: 'float' = 0.0, light_brightness_percent: 'float' = 0.0, inlet_temperature_c: 'float' = 0.0, outlet_temperature_c: 'float' = 0.0, calculated_ambient_temperature_c: 'float' = 0.0, louver_angle_up_down_degrees: 'float' = 0.0, updated_at: 'datetime | None' = None) -> None`

## `quilt_hp.models.outdoor_unit`

### Classes

#### `OutdoorUnit`

- `__init__(self, id: 'str', system_id: 'str', space_id: 'str', hvac_state: 'int', model_sku: 'str | None', serial_number: 'str | None', firmware_version: 'str | None', firmware_update_info_id: 'str | None', performance_data: 'OutdoorUnitPerformanceData | None') -> None`
- `from_proto(cls, proto: 'object', hw_map: 'dict[str, object] | None' = None) -> 'OutdoorUnit'`

#### `OutdoorUnitPerformanceData`

- `__init__(self, measurement_interval_s: 'float', energy_measurement_j: 'float', compressor_frequency_hz: 'float', ambient_temperature_c: 'float', coil_temperature_c: 'float', exhaust_temperature_c: 'float', high_pressure_kpa: 'float', low_pressure_kpa: 'float') -> None`

## `quilt_hp.models.qsm`

### Classes

#### `QsmSensors`

- `__init__(self, phase_detected_raw: 'float', target_detected_raw: 'float', als_illuminance_raw: 'int', als_ir_raw: 'int', als_both_raw: 'int', accel_x_raw: 'int', accel_y_raw: 'int', accel_z_raw: 'int') -> None`

#### `QuiltSmartModule`

- `__init__(self, id: 'str', system_id: 'str', led_color_code: 'int', sensors: 'QsmSensors | None', hosted_wifi: 'WifiInfo | None', ap_wifi: 'WifiInfo | None', p2p_wifi: 'WifiInfo | None', software_update_info_id: 'str | None' = None, firmware_update_info_id: 'str | None' = None) -> None`
- `from_proto(cls, proto: 'object') -> 'QuiltSmartModule'`

#### `WifiInfo`

- `__init__(self, ssid: 'str | None', ip: 'str | None', signal_dbm: 'int | None') -> None`
- `connected` *(property)*
- `from_proto(cls, proto: 'object') -> 'WifiInfo'`

## `quilt_hp.models.schedule`

### Classes

#### `ScheduleDay`

- `__init__(self, id: 'str', name: 'str', space_id: 'str', events: 'list[ScheduleEvent]') -> None`
- `from_proto(cls, proto: 'object') -> 'ScheduleDay'`

#### `ScheduleEvent`

- `__init__(self, start_s: 'int', comfort_setting_id: 'str', hvac_mode: 'int', heating_setpoint_c: 'float', cooling_setpoint_c: 'float', precondition: 'bool') -> None`
- `start_time` *(property)*

#### `ScheduleWeek`

- `__init__(self, id: 'str', space_id: 'str', days: 'list[ScheduleWeekDay]') -> None`
- `from_proto(cls, proto: 'object') -> 'ScheduleWeek'`

#### `ScheduleWeekDay`

- `__init__(self, weekday: 'int', day_id: 'str') -> None`
- `weekday_name` *(property)*

## `quilt_hp.models.sensor`

### Classes

#### `ControllerRemoteSensor`

- `__init__(self, id: 'str', controller_id: 'str', mac: 'str | None', ambient_temperature_c: 'float | None', humidity_percent: 'float | None', battery_level_percent: 'float | None', signal_level_dbm: 'int | None', control_mode: 'RemoteSensorControlMode') -> None`
- `from_proto(cls, proto: 'object') -> 'ControllerRemoteSensor'`

#### `RemoteSensor`

- `__init__(self, id: 'str', indoor_unit_id: 'str', mac: 'str | None', ambient_temperature_c: 'float | None', humidity_percent: 'float | None', battery_level_percent: 'float | None', signal_level_dbm: 'int | None', control_mode: 'RemoteSensorControlMode') -> None`
- `from_proto(cls, proto: 'object') -> 'RemoteSensor'`

## `quilt_hp.models.software_update`

### Classes

#### `SoftwareUpdateInfo`

- `__init__(self, id: 'str', state: 'int', status: 'int', current_version: 'str', target_version: 'str', current_progress: 'float', total_progress: 'float', progress_unit: 'int') -> None`
- `from_proto(cls, proto: 'object') -> 'SoftwareUpdateInfo'`

#### `SoftwareUpdateState`


#### `SoftwareUpdateStatus`


## `quilt_hp.models.space`

### Classes

#### `Space`

- `__init__(self, id: 'str', system_id: 'str', name: 'str', parent_space_id: 'str | None', settings: 'SpaceSettings', controls: 'SpaceControls', state: 'SpaceState', active_comfort_setting_type: 'ComfortSettingType | None' = None) -> None`
- `ambient_temperature_f` *(property)*
- `from_proto(cls, proto: 'object') -> 'Space'`
- `is_away` *(property)*
- `is_off` *(property)*
- `is_room` *(property)*

#### `SpaceControls`

- `__init__(self, hvac_mode: 'HVACMode', temperature_setpoint_c: 'float', cooling_setpoint_c: 'float', heating_setpoint_c: 'float', comfort_setting_id: 'str', comfort_setting_override: 'ComfortSettingOverride', boost_mode: 'BoostMode' = <BoostMode.UNSPECIFIED: 0>) -> None`
- `display_setpoint` *(property)*
- `display_setpoint_str(self, use_f: 'bool' = False) -> 'str'`

#### `SpaceSettings`

- `__init__(self, name: 'str', timezone: 'str', occupancy_mode: 'OccupancyMode', occupied_timeout_s: 'float', unoccupied_timeout_s: 'float', safety_heating: 'SafetyHeatingMode', hvac_controller_type: 'HvacControllerType' = <HvacControllerType.UNSPECIFIED: 0>) -> None`

#### `SpaceState`

- `__init__(self, ambient_temperature_c: 'float | None', hvac_state: 'HVACState', setpoint_c: 'float | None', comfort_setting_id: 'str') -> None`

## `quilt_hp.models.system`

### Classes

#### `Location`

- `__init__(self, id: 'str', name: 'str', system_id: 'str', timezone: 'str', schedule_paused: 'bool') -> None`
- `from_proto(cls, proto: 'object') -> 'Location'`

#### `SystemInfo`

- `__init__(self, id: 'str', name: 'str', timezone: 'str') -> None`

#### `SystemSnapshot`

- `__init__(self, spaces: 'list[Space]', indoor_units: 'list[IndoorUnit]', outdoor_units: 'list[OutdoorUnit]', controllers: 'list[Controller]', quilt_smart_modules: 'list[QuiltSmartModule]', comfort_settings: 'list[ComfortSetting]', schedule_weeks: 'list[ScheduleWeek]', schedule_days: 'list[ScheduleDay]', remote_sensors: 'list[RemoteSensor]', controller_remote_sensors: 'list[ControllerRemoteSensor]', software_update_infos: 'list[SoftwareUpdateInfo]', locations: 'list[Location]', timezone: 'str | None') -> None`
- `apply_controller(self, ctrl: 'Controller') -> 'Controller'`
- `apply_controller_remote_sensor(self, crs: 'ControllerRemoteSensor') -> 'ControllerRemoteSensor'`
- `apply_indoor_unit(self, idu: 'IndoorUnit') -> 'IndoorUnit'`
- `apply_outdoor_unit(self, odu: 'OutdoorUnit') -> 'OutdoorUnit'`
- `apply_qsm(self, qsm: 'QuiltSmartModule') -> 'QuiltSmartModule'`
- `apply_remote_sensor(self, rs: 'RemoteSensor') -> 'RemoteSensor'`
- `apply_space(self, space: 'Space') -> 'Space'`
- `enrich_space(self, space: 'Space') -> 'Space'`
- `from_proto(cls, proto: 'object') -> 'SystemSnapshot'`
- `primary_location` *(property)*
- `qsm_for_idu(self, idu: 'IndoorUnit') -> 'QuiltSmartModule | None'`
- `rooms` *(property)*
- `space_by_name(self, name: 'str') -> 'Space | None'`
- `stream_topics(self) -> 'list[str]'`

## `quilt_hp.services`

## `quilt_hp.services.hds`

### Classes

#### `HomeDatastoreService`

- `__init__(self, channel: 'grpc.aio.Channel') -> 'None'`
- `create_schedule_day(self, system_id: 'str', space_id: 'str', name: 'str', events: 'Sequence[ScheduleEvent | hds.ScheduleEvent]') -> 'ScheduleDay'`
- `create_schedule_week(self, system_id: 'str', space_id: 'str', days: 'Sequence[ScheduleWeekDay | hds.ScheduleWeekDay] | None' = None) -> 'ScheduleWeek'`
- `delete_schedule_day(self, schedule_day_id: 'str') -> 'None'`
- `delete_schedule_week(self, schedule_week_id: 'str') -> 'None'`
- `get_system(self, system_id: 'str') -> 'SystemSnapshot'`
- `update_comfort_setting(self, setting: 'ComfortSetting', *, name: 'str | None' = None, hvac_mode: 'HVACMode | None' = None, heat_setpoint_c: 'float | None' = None, cool_setpoint_c: 'float | None' = None, fan_speed: 'FanSpeed | None' = None) -> 'ComfortSetting'`
- `update_indoor_unit(self, idu: 'IndoorUnit', *, fan_speed: 'FanSpeed | None' = None, louver_mode: 'LouverMode | None' = None, louver_position: 'float | None' = None, led_color_code: 'int | None' = None, led_brightness: 'float | None' = None, led_animation: 'int | None' = None) -> 'IndoorUnit'`
- `update_indoor_unit_settings(self, idu: 'IndoorUnit', *, fence_left_m: 'float | None' = None, fence_right_m: 'float | None' = None, fence_forward_m: 'float | None' = None, radar_height_m: 'float | None' = None, light_brightness_default: 'float | None' = None) -> 'IndoorUnit'`
- `update_location_schedule_execution(self, location_id: 'str', system_id: 'str', paused: 'bool') -> 'None'`
- `update_schedule_day(self, schedule_day_id: 'str', system_id: 'str', space_id: 'str', name: 'str | None' = None, events: 'Sequence[ScheduleEvent | hds.ScheduleEvent] | None' = None) -> 'ScheduleDay'`
- `update_schedule_week(self, schedule_week_id: 'str', system_id: 'str', space_id: 'str', days: 'Sequence[ScheduleWeekDay | hds.ScheduleWeekDay]') -> 'ScheduleWeek'`
- `update_space(self, snapshot_space: 'Space', *, mode: 'HVACMode | None' = None, heat_setpoint_c: 'float | None' = None, cool_setpoint_c: 'float | None' = None) -> 'Space'`
- `update_space_settings(self, snapshot_space: 'Space', *, unoccupied_timeout_s: 'float | None' = None, occupied_timeout_s: 'float | None' = None) -> 'Space'`

## `quilt_hp.services.streaming`

### Classes

#### `NotifierStream`

- `__init__(self, _channel: 'grpc.aio.Channel', _topics: 'list[str]', _metadata_provider: 'Callable[[], Sequence[tuple[str, str]]] | None' = None, _authenticate: 'RefreshCallback | None' = None, _max_reconnects: 'int' = -1, _reconnect_delay_s: 'float' = 1.0) -> None`
- `create(cls, channel: 'grpc.aio.Channel', topics: 'list[str]', *, metadata_provider: 'Callable[[], Sequence[tuple[str, str]]] | None' = None, authenticate: 'RefreshCallback | None' = None, max_reconnects: 'int' = -1, reconnect_delay_s: 'float' = 1.0) -> 'NotifierStream'`
- `error` *(property)*
- `on_controller_remote_sensor_update(self, callback: 'ControllerRemoteSensorCallback') -> 'None'`
- `on_controller_update(self, callback: 'ControllerCallback') -> 'None'`
- `on_error(self, callback: 'ErrorCallback') -> 'None'`
- `on_indoor_unit_update(self, callback: 'IndoorUnitCallback') -> 'None'`
- `on_outdoor_unit_update(self, callback: 'OutdoorUnitCallback') -> 'None'`
- `on_qsm_update(self, callback: 'QsmCallback') -> 'None'`
- `on_remote_sensor_update(self, callback: 'RemoteSensorCallback') -> 'None'`
- `on_software_update_info(self, callback: 'SoftwareUpdateInfoCallback') -> 'None'`
- `on_space_update(self, callback: 'SpaceCallback') -> 'None'`
- `run_forever(self) -> 'None'`
- `start(self) -> 'None'`
- `stop(self) -> 'None'`
- `subscribe(self, topics: 'list[str]') -> 'None'`
- `unsubscribe(self, topics: 'list[str]') -> 'None'`

#### `StreamEvent`

- `__init__(self, topic: 'str', space: 'Space | None' = None, indoor_unit: 'IndoorUnit | None' = None, outdoor_unit: 'OutdoorUnit | None' = None, controller: 'Controller | None' = None, qsm: 'QuiltSmartModule | None' = None, remote_sensor: 'RemoteSensor | None' = None, controller_remote_sensor: 'ControllerRemoteSensor | None' = None, software_update_info: 'SoftwareUpdateInfo | None' = None, raw_bytes: 'bytes | None' = None) -> None`

## `quilt_hp.services.system`

### Classes

#### `SystemInformationService`

- `__init__(self, channel: 'grpc.aio.Channel') -> 'None'`
- `get_energy_metrics(self, system_id: 'str', start: '_datetime', end: '_datetime') -> 'list[SpaceEnergyMetrics]'`
- `list_systems(self) -> 'list[SystemInfo]'`

## `quilt_hp.services.user`

### Classes

#### `DeclaredUserType`


#### `User`

- `__init__(self, id: 'str', first_name: 'str', last_name: 'str', email: 'str', phone_number: 'str') -> None`

#### `UserAttributes`

- `__init__(self, declared_user_type: 'DeclaredUserType') -> None`

#### `UserService`

- `__init__(self, channel: 'grpc.aio.Channel') -> 'None'`
- `get_current_user(self) -> 'User'`
- `get_user_attributes(self) -> 'UserAttributes'`
- `patch_user_attributes(self, *, declared_user_type: 'DeclaredUserType') -> 'UserAttributes'`
- `update_current_user(self, *, first_name: 'str', last_name: 'str', phone_number: 'str | None' = None) -> 'User'`

## `quilt_hp.tokens`

### Classes

#### `CachedTokens`

- `__init__(self, id_token: 'str', refresh_token: 'str', expires_at: 'float') -> None`
- `is_expired` *(property)*

#### `CurrentTokenProvider`

- `__init__(self, *args, **kwargs)`
- `get_current_token(self) -> 'str'`

#### `LegacyTokenStore`

- `__init__(self, *args, **kwargs)`
- `load(self, email: 'str') -> 'CachedTokens | None'`
- `save(self, email: 'str', tokens: 'CachedTokens') -> 'None'`

#### `RefreshFailureAction`


#### `TokenRefreshContext`

- `__init__(self, reason: 'TokenRefreshReason', source: 'str', attempt: 'int' = 1) -> None`

#### `TokenRefreshHooks`

- `__init__(self, *args, **kwargs)`
- `on_refresh_failure(self, context: 'TokenRefreshContext', error: 'Exception') -> 'None'`
- `on_refresh_start(self, context: 'TokenRefreshContext') -> 'None'`
- `on_refresh_success(self, context: 'TokenRefreshContext', tokens: 'CachedTokens') -> 'None'`

#### `TokenRefreshPolicy`

- `__init__(self, *args, **kwargs)`
- `on_refresh_failure(self, context: 'TokenRefreshContext', error: 'Exception') -> 'RefreshFailureAction'`

#### `TokenRefreshReason`


#### `TokenStore`

- `__init__(self, *args, **kwargs)`
- `load(self, email: 'str') -> 'CachedTokens | None'`
- `save(self, email: 'str', tokens: 'CachedTokens') -> 'None'`

## `quilt_hp.transport`

### Functions

- `auth_metadata(token_provider: 'TokenProviderLike') -> 'list[tuple[str, str]]'`
- `create_channel(token_provider: 'TokenProviderLike', environment: 'Environment' = <Environment.PROD: 'prod'>, refresh_callback: 'RefreshCallback | None' = None) -> 'grpc.aio.Channel'`
