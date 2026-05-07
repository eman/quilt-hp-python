"""Indoor unit model — wall-mounted mini-split head."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

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

    @property
    def light_on(self) -> bool:
        """True when the LED intent is ON.

        When ``led_state`` is explicit (mobile_led_scheduling_enabled gate on):
        - ON  → True
        - OFF → False (brightness is preserved server-side, so > 0 does not
          mean on)
        Fallback when UNSPECIFIED: matches KMP ``Light.isOn`` logic:
        isBlack = led_color_code == 0; isOn = !isBlack && brightness > 0.
        """
        if self.led_state == LightState.ON:
            return True
        if self.led_state == LightState.OFF:
            return False
        # UNSPECIFIED: legacy brightness-based detection
        return self.led_color_code != 0 and self.led_brightness > 0.0


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
    outdoor_unit_id: str | None  # APK: IndoorUnitRelationships.outdoor_unit_id field 3
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

    @classmethod
    def from_proto(cls, proto: object) -> IndoorUnit:
        """Construct from a protobuf IndoorUnit message."""
        return _idu_from_proto(proto)

    @property
    def is_online(self) -> bool:
        """True if the IDU has sent a state update within the last 5 minutes.

        Matches KMP SpaceViewNode.isOnlineByUpdatedTimestamp.
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

        Applies the online gate: KMP's ``getLight()`` calls ``filterOnline()``
        and returns ``Light.OFF`` for offline IDUs.  An offline IDU's controls
        data is stale and must not be used for LED state.
        """
        return self.is_online and self.controls.light_on

    @property
    def effective_occupancy_state(self) -> int | None:
        """Occupancy state proto value, or None if the IDU is offline.

        KMP reads presence/occupancy only from online IDUs (``filterOnline()``).
        An offline IDU's last-known ``occupancy_state`` is stale and must not
        be displayed as current. Returns None when offline or no occupancy data.
        """
        if not self.is_online or self.occupancy is None:
            return None
        return self.occupancy.occupancy_state


def _idu_from_proto(proto: object) -> IndoorUnit:
    """Internal: convert a proto IndoorUnit to our model."""
    from quilt_hp.models.enums import HVACMode, HVACState

    c = proto.controls  # type: ignore[attr-defined]
    s = proto.state  # type: ignore[attr-defined]
    st = proto.settings  # type: ignore[attr-defined]
    pd = proto.performance_data  # type: ignore[attr-defined]
    pm = proto.performance_metrics  # type: ignore[attr-defined]

    perf_data = None
    if pd.updated_ts:
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

    perf_metrics = None
    if pm.updated_ts:
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
    hi = proto.hvac_inputs  # type: ignore[attr-defined]
    if hi.updated_ts:
        hvac_inputs = IndoorUnitHvacInputs(
            external_ambient_temperature_c=hi.external_ambient_temperature_c,
            ambient_temperature_source=hi.ambient_temperature_source,
            temperature_setpoint_c=hi.temperature_setpoint_c,
            hvac_mode=HVACMode(hi.hvac_mode),
            hvac_state=HVACState(hi.hvac_state),
            hvac_controller_type=HvacControllerType(hi.hvac_controller_type),
        )

    commands = None
    cmd = proto.commands  # type: ignore[attr-defined]
    if cmd.updated_ts:
        commands = IndoorUnitCommands(
            fallback_control_command=FallbackControlCommand(cmd.fallback_control_command),
        )

    conditions = None
    co = proto.conditions  # type: ignore[attr-defined]
    if co.updated_ts:
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
        )

    presence_state = None
    if hasattr(proto, "presence") and proto.presence.updated_ts:
        presence_state = IndoorUnitPresence(
            sensor0_presence=Presence(proto.presence.sensor0_presence),
            sensor1_presence=Presence(proto.presence.sensor1_presence),
        )

    occupancy_state = None
    if hasattr(proto, "occupancy") and proto.occupancy.updated_ts:
        occupancy_state = IndoorUnitOccupancy(
            occupancy_state=proto.occupancy.occupancy_state,
        )

    return IndoorUnit(
        id=proto.header.object_id,  # type: ignore[attr-defined]
        system_id=proto.header.system_id,  # type: ignore[attr-defined]
        space_id=proto.relationships.space_id,  # type: ignore[attr-defined]
        outdoor_unit_id=proto.relationships.outdoor_unit_id or None,  # type: ignore[attr-defined]
        hardware_id=proto.relationships.hardware_id,  # type: ignore[attr-defined]
        qsm_id=proto.relationships.quilt_smart_module_id or None,  # type: ignore[attr-defined]
        settings=IndoorUnitSettings(
            name=st.name,
            description=st.description,
            light_brightness_default_percent=st.light_brightness_default_percent,
            presence_fence_left_m=st.presence_fence_left_m,
            presence_fence_right_m=st.presence_fence_right_m,
            presence_fence_forward_m=st.presence_fence_forward_m,
            radar_sensor_distance_from_floor_m=st.radar_sensor_distance_from_floor_m,
        ),
        controls=IndoorUnitControls(
            fan_speed=FanSpeed.from_wire(c.fan_speed_mode, c.fan_speed_percent),
            fan_speed_mode_raw=c.fan_speed_mode,
            louver_mode=LouverMode(c.louver_mode) if c.louver_mode else LouverMode.UNSPECIFIED,
            louver_fixed_position=c.louver_fixed_position,
            led_color_code=c.led_color_code,
            led_brightness=c.led_color_brightness_percent,
            led_animation=LedAnimation(c.led_animation),
            led_state=LightState(c.led_state),
        ),
        state=IndoorUnitState(
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
            updated_at=(
                datetime.fromtimestamp(s.updated_ts.seconds, tz=UTC)
                if s.updated_ts and s.updated_ts.seconds
                else None
            ),
        ),
        hvac_inputs=hvac_inputs,
        conditions=conditions,
        performance_data=perf_data,
        performance_metrics=perf_metrics,
        presence=presence_state,
        occupancy=occupancy_state,
        firmware_update_info_id=(
            proto.relationships.firmware_update_info_id or None  # type: ignore[attr-defined]
        ),
        commands=commands,
    )
