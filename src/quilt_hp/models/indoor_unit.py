"""Indoor unit model — wall-mounted mini-split head."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from quilt_hp.const import (
    ABSENT_FAN_SPEED_MODE_SENTINEL,
    LOUVER_FIXED_POSITION_SENTINEL,
)
from quilt_hp.models._helpers import lookup_hardware, present_submsg, timestamp_or_none
from quilt_hp.models.enums import (
    FallbackControlCommand,
    FanSpeed,
    HvacControllerType,
    HVACMode,
    HVACState,
    LedAnimation,
    LightState,
    LouverMode,
    Presence,
)

_ONLINE_THRESHOLD_MINUTES = 5


@dataclass(slots=True)
class IndoorUnitControls:
    """Controllable settings for an indoor unit."""

    fan_speed: FanSpeed
    louver_mode: LouverMode
    louver_fixed_position: float
    led_color_code: int
    led_brightness: float  # stored brightness 0.0-1.0; preserved when led_state=OFF
    led_animation: LedAnimation
    led_state: LightState = LightState.UNSPECIFIED  # explicit ON/OFF (proto field 13)
    # Raw wire FAN_SPEED_MODE value (0=absent/proto3-default, 1=AUTO,
    # 2=SETPOINT). Needed because FanSpeed.from_wire(0, 0.0) and
    # from_wire(1, 0.0) both return FanSpeed.AUTO.
    fan_speed_mode_raw: int = 0
    fan_speed_percent_raw: float = 0.0

    @property
    def light_on(self) -> bool:
        """True when the LED intent is ON.

        When ``led_state`` is explicit (mobile_led_scheduling_enabled gate on):
        - ON  → True
        - OFF → False (brightness is preserved server-side, so > 0 does not
          mean on)
        Fallback when UNSPECIFIED: uses brightness-based detection —
        isOn = led_color_code != 0 and brightness > 0.
        """
        if self.led_state == LightState.ON:
            return True
        if self.led_state == LightState.OFF:
            return False
        # UNSPECIFIED: legacy brightness-based detection
        return self.led_color_code != 0 and self.led_brightness > 0.0

    @property
    def fan_speed_is_placeholder(self) -> bool:
        """True when fan speed fields are absent (proto3 default sentinel mode=0)."""
        return self.fan_speed_mode_raw == ABSENT_FAN_SPEED_MODE_SENTINEL

    @property
    def louver_position_is_placeholder(self) -> bool:
        """True when fixed position is a non-applicable 0.0 placeholder."""
        return (
            self.louver_mode != LouverMode.FIXED
            and self.louver_fixed_position == LOUVER_FIXED_POSITION_SENTINEL
        )


@dataclass(slots=True)
class IndoorUnitSettings:
    """Configuration/calibration settings for an indoor unit."""

    name: str
    description: str
    light_brightness_default_percent: float
    presence_fence_left_m: float  # detection zone left boundary (0 = unconfigured/max range)
    presence_fence_right_m: float  # detection zone right boundary
    presence_fence_forward_m: float  # detection zone forward boundary (depth)
    radar_sensor_distance_from_floor_m: float  # mounting height calibration


@dataclass(slots=True)
class IndoorUnitState:
    """Read-only state for an indoor unit."""

    hvac_mode: HVACMode
    hvac_state: HVACState
    ambient_temperature_c: float
    ambient_humidity_percent: float
    fan_speed_rpm: float
    fan_speed_setpoint_rpm: float
    presence_detection_level: float
    # Additional state fields (proto fields 2, 7, 9, 10, 13, 14)
    temperature_setpoint_c: float = 0.0
    light_brightness_percent: float = 0.0  # device-reported actual LED brightness (field 7)
    inlet_temperature_c: float = 0.0
    outlet_temperature_c: float = 0.0
    calculated_ambient_temperature_c: float = 0.0
    louver_angle_up_down_degrees: float = 0.0
    # proto field 1: timestamp of last state update (used for online detection)
    updated_at: datetime | None = None


@dataclass(slots=True)
class IndoorUnitPerformanceData:
    """Raw IDU sensor measurements (updated every ~5 seconds)."""

    measurement_interval_s: float
    energy_measurement_j: float
    hvac_mode: HVACMode
    hvac_state: HVACState
    actual_fan_speed_rpm: float
    outlet_temperature_c: float
    inlet_temperature_c: float
    inlet_humidity_pct: float
    coil_temperature_c: float
    gas_pipe_temperature_c: float
    liquid_pipe_temperature_c: float

    @property
    def energy_kwh(self) -> float:
        """Energy for this interval in kWh."""
        return self.energy_measurement_j / 3_600_000


@dataclass(slots=True)
class IndoorUnitPerformanceMetrics:
    """Computed efficiency metrics (only populated when unit is running)."""

    capacity_w: float
    coefficient_of_performance: float
    hvac_power_w: float
    led_power_w: float
    hvac_mode: HVACMode
    hvac_state: HVACState
    measurement_duration_s: float = 0.0
    energy_total_j: float = 0.0
    hvac_energy_j: float = 0.0
    led_energy_j: float = 0.0


@dataclass(slots=True)
class IndoorUnitHvacInputs:
    """HVAC controller inputs — what the controller sends to the IDU."""

    external_ambient_temperature_c: float
    ambient_temperature_source: int
    temperature_setpoint_c: float
    hvac_mode: HVACMode
    hvac_state: HVACState
    hvac_controller_type: HvacControllerType = HvacControllerType.UNSPECIFIED


@dataclass(slots=True)
class IndoorUnitCommands:
    """IDU fallback control command (sent during cloud connectivity loss)."""

    fallback_control_command: FallbackControlCommand


@dataclass(slots=True)
class IndoorUnitConditions:
    """IDU diagnostic conditions (ODU-linked conditions included)."""

    mode_conflict: int
    anti_cold_wind: int
    abnormal_outdoor_air_temperature: int
    hvac_mode_switching_delay: int
    defrost_cycle: int
    safety_heating: int
    oil_return: int
    modbus_communication_error: int
    coil_preheat: int
    mode_conflict_avoidance: int
    outdoor_unit_communication_error: int
    compressor_minimum_run_time: int = 0

    @property
    def any_active(self) -> bool:
        """True if any condition is ACTIVE (value 2)."""
        return any(
            getattr(self, f) == 2
            for f in (
                "mode_conflict",
                "anti_cold_wind",
                "abnormal_outdoor_air_temperature",
                "hvac_mode_switching_delay",
                "defrost_cycle",
                "safety_heating",
                "oil_return",
                "modbus_communication_error",
                "coil_preheat",
                "mode_conflict_avoidance",
                "outdoor_unit_communication_error",
                "compressor_minimum_run_time",
            )
        )


@dataclass(slots=True)
class IndoorUnitPresence:
    """Radar presence sensor data — binary DETECTED / UNDETECTED per sensor."""

    sensor0_presence: Presence
    sensor1_presence: Presence


@dataclass(slots=True)
class IndoorUnitOccupancy:
    """Computed room occupancy state."""

    occupancy_state: int


@dataclass(slots=True)
class IndoorUnit:
    """A Quilt indoor unit (wall-mounted mini-split head)."""

    id: str
    system_id: str
    space_id: str
    outdoor_unit_id: str | None  # linked outdoor unit, if any
    hardware_id: str
    qsm_id: str | None  # QuiltSmartModule embedded in this unit
    settings: IndoorUnitSettings
    controls: IndoorUnitControls
    state: IndoorUnitState
    hvac_inputs: IndoorUnitHvacInputs | None
    conditions: IndoorUnitConditions | None
    performance_data: IndoorUnitPerformanceData | None
    performance_metrics: IndoorUnitPerformanceMetrics | None
    presence: IndoorUnitPresence | None
    occupancy: IndoorUnitOccupancy | None
    firmware_update_info_id: str | None = None
    commands: IndoorUnitCommands | None = None
    model_sku: str | None = None  # IndoorUnitHardware.attributes.model_sku
    serial_number: str | None = None  # IndoorUnitHardware.attributes.serial_number
    firmware_version: str | None = None  # IndoorUnitHardware.attributes.firmware_version

    @classmethod
    def from_proto(cls, proto: object, hw_map: dict[str, object] | None = None) -> IndoorUnit:
        """Construct from a protobuf IndoorUnit message.

        ``hw_map`` maps hardware_id → IndoorUnitHardware proto, built once from
        ``HomeDatastoreSystem.indoor_unit_hardware`` and passed in at snapshot
        load time.  Stream diffs won't have it; hardware fields default to None.
        """
        return _idu_from_proto(proto, hw_map)

    @property
    def is_online(self) -> bool:
        """True if the IDU has sent a state update within the last 5 minutes.
        An offline IDU may have stale controls data — treat LED as off.
        """
        ts = self.state.updated_at
        if ts is None:
            return False
        now = datetime.now(tz=UTC)
        delta_minutes = (now - ts).total_seconds() / 60
        return delta_minutes < _ONLINE_THRESHOLD_MINUTES

    @property
    def led_on(self) -> bool:
        """True if the LED is currently illuminated.

        Applies the online gate: offline IDUs have stale controls data and
        must not be used for LED state.
        """
        return self.is_online and self.controls.light_on

    @property
    def effective_occupancy_state(self) -> int | None:
        """Occupancy state proto value, or None if the IDU is offline.

        An offline IDU's last-known ``occupancy_state`` is stale and must not
        be displayed as current. Returns None when offline or no occupancy data.
        """
        if not self.is_online or self.occupancy is None:
            return None
        return self.occupancy.occupancy_state


def _idu_from_proto(proto: object, hw_map: dict[str, object] | None = None) -> IndoorUnit:
    """Internal: convert a proto IndoorUnit to our model.

    Sub-messages absent from a sparse stream diff parse to ``None`` (for
    optional model fields) or sentinel defaults (for ``controls``/``state``/
    ``settings``) that ``SystemSnapshot.apply_indoor_unit`` uses to preserve
    existing snapshot data.  Presence is detected with ``HasField`` — proto3
    truthiness cannot detect absent sub-messages.
    """
    from quilt_hp.models.enums import HVACMode, HVACState

    pd = present_submsg(proto, "performance_data")
    perf_data = None
    if pd is not None:
        pd = cast("Any", pd)
        perf_data = IndoorUnitPerformanceData(
            measurement_interval_s=pd.measurement_interval_s,
            energy_measurement_j=pd.energy_measurement_j,
            hvac_mode=HVACMode(pd.hvac_mode),
            hvac_state=HVACState(pd.hvac_state),
            actual_fan_speed_rpm=pd.actual_fan_speed_rpm,
            outlet_temperature_c=pd.outlet_temperature_c,
            inlet_temperature_c=pd.inlet_temperature_c,
            inlet_humidity_pct=pd.inlet_humidity_pct,
            coil_temperature_c=pd.coil_temperature_c,
            gas_pipe_temperature_c=pd.gas_pipe_temperature_c,
            liquid_pipe_temperature_c=pd.liquid_pipe_temperature_c,
        )

    pm = present_submsg(proto, "performance_metrics")
    perf_metrics = None
    if pm is not None:
        pm = cast("Any", pm)
        perf_metrics = IndoorUnitPerformanceMetrics(
            capacity_w=pm.capacity_w,
            coefficient_of_performance=pm.coefficient_of_performance,
            hvac_power_w=pm.hvac_power_w,
            led_power_w=pm.led_power_w,
            hvac_mode=HVACMode(pm.hvac_mode),
            hvac_state=HVACState(pm.hvac_state),
            measurement_duration_s=pm.measurement_duration_s,
            energy_total_j=pm.energy_total_j,
            hvac_energy_j=pm.hvac_energy_j,
            led_energy_j=pm.led_energy_j,
        )

    hvac_inputs = None
    hi = present_submsg(proto, "hvac_inputs")
    if hi is not None:
        hi = cast("Any", hi)
        hvac_inputs = IndoorUnitHvacInputs(
            external_ambient_temperature_c=hi.external_ambient_temperature_c,
            ambient_temperature_source=hi.ambient_temperature_source,
            temperature_setpoint_c=hi.temperature_setpoint_c,
            hvac_mode=HVACMode(hi.hvac_mode),
            hvac_state=HVACState(hi.hvac_state),
            hvac_controller_type=HvacControllerType(hi.hvac_controller_type),
        )

    commands = None
    cmd = present_submsg(proto, "commands")
    if cmd is not None:
        cmd = cast("Any", cmd)
        commands = IndoorUnitCommands(
            fallback_control_command=FallbackControlCommand(cmd.fallback_control_command),
        )

    conditions = None
    co = present_submsg(proto, "conditions")
    if co is not None:
        co = cast("Any", co)
        conditions = IndoorUnitConditions(
            mode_conflict=co.mode_conflict,
            anti_cold_wind=co.anti_cold_wind,
            abnormal_outdoor_air_temperature=co.abnormal_outdoor_air_temperature,
            hvac_mode_switching_delay=co.hvac_mode_switching_delay,
            defrost_cycle=co.defrost_cycle,
            safety_heating=co.safety_heating,
            oil_return=co.oil_return,
            modbus_communication_error=co.modbus_communication_error,
            coil_preheat=co.coil_preheat,
            mode_conflict_avoidance=co.mode_conflict_avoidance,
            outdoor_unit_communication_error=co.outdoor_unit_communication_error,
            compressor_minimum_run_time=co.compressor_minimum_run_time,
        )

    presence_state = None
    pres = present_submsg(proto, "presence")
    if pres is not None:
        pres = cast("Any", pres)
        presence_state = IndoorUnitPresence(
            sensor0_presence=Presence(pres.sensor0_presence),
            sensor1_presence=Presence(pres.sensor1_presence),
        )

    occupancy_state = None
    occ = present_submsg(proto, "occupancy")
    if occ is not None:
        occ = cast("Any", occ)
        occupancy_state = IndoorUnitOccupancy(
            occupancy_state=occ.occupancy_state,
        )

    st = present_submsg(proto, "settings")
    if st is not None:
        st = cast("Any", st)
        settings = IndoorUnitSettings(
            name=st.name,
            description=st.description,
            light_brightness_default_percent=st.light_brightness_default_percent,
            presence_fence_left_m=st.presence_fence_left_m,
            presence_fence_right_m=st.presence_fence_right_m,
            presence_fence_forward_m=st.presence_fence_forward_m,
            radar_sensor_distance_from_floor_m=st.radar_sensor_distance_from_floor_m,
        )
    else:
        settings = IndoorUnitSettings(
            name="",
            description="",
            light_brightness_default_percent=0.0,
            presence_fence_left_m=0.0,
            presence_fence_right_m=0.0,
            presence_fence_forward_m=0.0,
            radar_sensor_distance_from_floor_m=0.0,
        )

    c = present_submsg(proto, "controls")
    if c is not None:
        c = cast("Any", c)
        controls = IndoorUnitControls(
            fan_speed=FanSpeed.from_wire(c.fan_speed_mode, c.fan_speed_percent),
            fan_speed_mode_raw=c.fan_speed_mode,
            fan_speed_percent_raw=c.fan_speed_percent,
            louver_mode=(
                LouverMode(c.louver_mode) if c.louver_mode is not None else LouverMode.UNSPECIFIED
            ),
            louver_fixed_position=c.louver_fixed_position,
            led_color_code=c.led_color_code,
            led_brightness=c.led_color_brightness_percent,
            led_animation=LedAnimation(c.led_animation),
            led_state=LightState(c.led_state),
        )
    else:
        # All-sentinel controls: apply_indoor_unit detects and preserves.
        controls = IndoorUnitControls(
            fan_speed=FanSpeed.from_wire(0, 0.0),
            louver_mode=LouverMode.UNSPECIFIED,
            louver_fixed_position=LOUVER_FIXED_POSITION_SENTINEL,
            led_color_code=0,
            led_brightness=0.0,
            led_animation=LedAnimation.UNSPECIFIED,
        )

    s = present_submsg(proto, "state")
    if s is not None:
        s = cast("Any", s)
        state = IndoorUnitState(
            hvac_mode=HVACMode(s.hvac_mode),
            hvac_state=HVACState(s.hvac_state),
            ambient_temperature_c=s.ambient_temperature_c,
            ambient_humidity_percent=s.ambient_humidity_percent,
            fan_speed_rpm=s.fan_speed_rpm,
            fan_speed_setpoint_rpm=s.fan_speed_setpoint_rpm,
            presence_detection_level=s.presence_detection_level,
            temperature_setpoint_c=s.temperature_setpoint_c,
            light_brightness_percent=s.light_brightness_percent,
            inlet_temperature_c=s.inlet_temperature_c,
            outlet_temperature_c=s.outlet_temperature_c,
            calculated_ambient_temperature_c=s.calculated_ambient_temperature_c,
            louver_angle_up_down_degrees=s.louver_angle_up_down_degrees,
            updated_at=timestamp_or_none(getattr(s, "updated_ts", None)),
        )
    else:
        state = IndoorUnitState(
            hvac_mode=HVACMode.UNSPECIFIED,
            hvac_state=HVACState.UNSPECIFIED,
            ambient_temperature_c=0.0,
            ambient_humidity_percent=0.0,
            fan_speed_rpm=0.0,
            fan_speed_setpoint_rpm=0.0,
            presence_detection_level=0.0,
        )

    rel = cast("Any", present_submsg(proto, "relationships"))
    p = cast("Any", proto)

    model_sku: str | None = None
    serial_number: str | None = None
    firmware_version: str | None = None
    if hw_map and rel is not None:
        hw = lookup_hardware(hw_map, rel.hardware_id)
        if hw is not None:
            a = cast("Any", hw).attributes
            model_sku = a.model_sku or None
            serial_number = a.serial_number or None
            firmware_version = a.firmware_version or None

    return IndoorUnit(
        id=p.header.object_id,
        system_id=p.header.system_id,
        space_id=rel.space_id if rel is not None else "",
        outdoor_unit_id=(rel.outdoor_unit_id or None) if rel is not None else None,
        hardware_id=rel.hardware_id if rel is not None else "",
        qsm_id=(rel.quilt_smart_module_id or None) if rel is not None else None,
        settings=settings,
        controls=controls,
        state=state,
        hvac_inputs=hvac_inputs,
        conditions=conditions,
        performance_data=perf_data,
        performance_metrics=perf_metrics,
        presence=presence_state,
        occupancy=occupancy_state,
        firmware_update_info_id=(
            (rel.firmware_update_info_id or None) if rel is not None else None
        ),
        commands=commands,
        model_sku=model_sku,
        serial_number=serial_number,
        firmware_version=firmware_version,
    )
