"""Space model — room-level HVAC zone."""

from __future__ import annotations

from dataclasses import dataclass, field

from quilt_hp.models.enums import (
    BoostMode,
    ComfortSettingOverride,
    ComfortSettingType,
    HvacControllerType,
    HVACMode,
    HVACState,
    OccupancyMode,
    SafetyHeatingMode,
)


@dataclass(slots=True)
class SpaceSettings:
    """Per-space automation and safety settings."""

    name: str  # space display name (needed to round-trip UpdateSpace settings)
    timezone: str  # IANA timezone string (e.g. "America/Los_Angeles")
    occupancy_mode: OccupancyMode
    occupied_timeout_s: float  # seconds of presence before "returned"; default 180s
    unoccupied_timeout_s: float  # seconds of no-presence before "away"; default 1200s
    safety_heating: SafetyHeatingMode
    hvac_controller_type: HvacControllerType = HvacControllerType.UNSPECIFIED


@dataclass(slots=True)
class SpaceControls:
    """Current HVAC control settings for a space."""

    hvac_mode: HVACMode
    temperature_setpoint_c: float
    cooling_setpoint_c: float
    heating_setpoint_c: float
    comfort_setting_id: str
    comfort_setting_override: ComfortSettingOverride
    boost_mode: BoostMode = BoostMode.UNSPECIFIED

    def display_setpoint_str(self, use_f: bool = False) -> str:
        """Human-readable setpoint string respecting °C/°F preference."""

        def fmt(val_c: float) -> str:
            if use_f:
                return f"{val_c * 9 / 5 + 32:.1f}°F"
            return f"{val_c:.1f}°C"

        mode = self.hvac_mode
        if mode in (HVACMode.STANDBY, HVACMode.UNSPECIFIED, HVACMode.FAN):
            return "--"
        if mode == HVACMode.COOL and self.cooling_setpoint_c:
            return fmt(self.cooling_setpoint_c)
        if mode == HVACMode.HEAT and self.heating_setpoint_c:
            return fmt(self.heating_setpoint_c)
        if mode == HVACMode.AUTO and self.cooling_setpoint_c and self.heating_setpoint_c:
            return f"{fmt(self.heating_setpoint_c)}–{fmt(self.cooling_setpoint_c)}"
        best = self.temperature_setpoint_c or self.cooling_setpoint_c or self.heating_setpoint_c
        return fmt(best) if best else "--"

    @property
    def display_setpoint(self) -> str:
        """Human-readable setpoint string in °C. Use display_setpoint_str(use_f) for unit-aware formatting."""
        return self.display_setpoint_str(use_f=False)


@dataclass(slots=True)
class SpaceState:
    """Read-only state for a space."""

    ambient_temperature_c: float | None
    hvac_state: HVACState
    setpoint_c: float | None
    comfort_setting_id: str


@dataclass(slots=True)
class Space:
    """A Quilt space (room / zone)."""

    id: str
    system_id: str
    name: str
    parent_space_id: str | None
    settings: SpaceSettings
    controls: SpaceControls
    state: SpaceState
    # Resolved from controls.comfort_setting_id at snapshot build time.
    # None if the space was received via a stream update without enrichment.
    active_comfort_setting_type: ComfortSettingType | None = field(default=None)

    @property
    def is_room(self) -> bool:
        """True if this is a leaf space (room), not the root home space."""
        return self.parent_space_id is not None and self.parent_space_id != ""

    @property
    def is_off(self) -> bool:
        """True when the user has explicitly set this space to STANDBY.

        The room will stay off regardless of occupancy or schedule.
        """
        return self.controls.hvac_mode == HVACMode.STANDBY and not self.is_away

    @property
    def is_away(self) -> bool:
        """True when occupancy automation has temporarily suppressed an active mode.

        Determined by the active comfort setting type being AWAY.  The room
        will re-activate automatically when someone enters.

        Falls back to comparing controls vs state hvac values when no comfort
        setting type is available (e.g. raw stream updates).
        """
        if self.active_comfort_setting_type is not None:
            return self.active_comfort_setting_type == ComfortSettingType.AWAY
        # Fallback: occupancy override shows STANDBY state while controls
        # hold an active mode.
        return self.state.hvac_state == HVACState.STANDBY and self.controls.hvac_mode not in (
            HVACMode.STANDBY,
            HVACMode.UNSPECIFIED,
        )

    @property
    def ambient_temperature_f(self) -> float | None:
        """Ambient temperature in °F, or None if unavailable."""
        if self.state.ambient_temperature_c is None:
            return None
        return self.state.ambient_temperature_c * 9 / 5 + 32

    @classmethod
    def from_proto(cls, proto: object) -> Space:
        """Construct a Space from a protobuf Space message."""
        return _space_from_proto(proto)


def _space_from_proto(proto: object) -> Space:
    """Internal: convert a proto Space to our model."""
    sg = proto.settings  # type: ignore[attr-defined]
    return Space(
        id=proto.header.object_id,  # type: ignore[attr-defined]
        system_id=proto.header.system_id,  # type: ignore[attr-defined]
        name=sg.name,  # type: ignore[attr-defined]
        parent_space_id=proto.relationships.parent_space_id or None,  # type: ignore[attr-defined]
        settings=SpaceSettings(
            name=sg.name,  # type: ignore[attr-defined]
            timezone=sg.timezone,  # type: ignore[attr-defined]
            occupancy_mode=OccupancyMode(sg.occupancy),  # type: ignore[attr-defined]
            occupied_timeout_s=sg.occupied_timeout_s,  # type: ignore[attr-defined]
            unoccupied_timeout_s=sg.unoccupied_timeout_s,  # type: ignore[attr-defined]
            safety_heating=SafetyHeatingMode(sg.safety_heating),  # type: ignore[attr-defined]
            hvac_controller_type=HvacControllerType(sg.hvac_controller_type),  # type: ignore[attr-defined]
        ),
        controls=SpaceControls(
            hvac_mode=HVACMode(proto.controls.hvac_mode),  # type: ignore[attr-defined]
            temperature_setpoint_c=proto.controls.temperature_setpoint_c,  # type: ignore[attr-defined]
            cooling_setpoint_c=proto.controls.cooling_temperature_setpoint_c,  # type: ignore[attr-defined]
            heating_setpoint_c=proto.controls.heating_temperature_setpoint_c,  # type: ignore[attr-defined]
            comfort_setting_id=proto.controls.comfort_setting_id_string,  # type: ignore[attr-defined]
            comfort_setting_override=ComfortSettingOverride(
                proto.controls.comfort_setting_override
            ),  # type: ignore[attr-defined]
            boost_mode=BoostMode(proto.controls.boost_mode),  # type: ignore[attr-defined]
        ),
        state=SpaceState(
            ambient_temperature_c=proto.state.ambient_temperature_c
            if proto.state.updated_ts
            else None,  # type: ignore[attr-defined]
            hvac_state=HVACState(proto.state.hvac_state),  # type: ignore[attr-defined]
            setpoint_c=proto.state.setpoint_temperature_c if proto.state.updated_ts else None,  # type: ignore[attr-defined]
            comfort_setting_id=proto.state.comfort_setting_id,  # type: ignore[attr-defined]
        ),
    )
