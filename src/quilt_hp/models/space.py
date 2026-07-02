"""Space model — room-level HVAC zone."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, cast

from quilt_hp.const import (
    EMPTY_COMFORT_SETTING_ID_SENTINEL,
    STANDBY_COOL_SENTINEL_C,
    STANDBY_HEAT_SENTINEL_C,
)
from quilt_hp.models._helpers import present_submsg
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
    """Current HVAC control settings for a space.

    ``heating_setpoint_c`` and ``cooling_setpoint_c`` always reflect the
    *active* comfort preset's setpoints — which change when the system
    switches between presets (Active → Away → Sleep, etc.).  When a room is
    in away mode (``space.is_away is True``), these fields hold the Away
    preset's setpoints, not the normal occupancy setpoints.  Use
    ``SystemSnapshot.away_comfort_setting(space)`` to read or modify the Away
    preset's setpoints without the room needing to be in away mode.

    When ``hvac_mode`` is ``STANDBY``, the server fills the setpoint fields
    with sentinel values (``STANDBY_HEAT_SENTINEL_C = 8.0 °C``,
    ``STANDBY_COOL_SENTINEL_C = 40.0 °C``) rather than omitting them.
    These are **not** real temperature targets.  Check
    ``has_standby_sentinel_setpoints`` before displaying setpoint values.

    ``comfort_setting_id`` uses an empty-string sentinel for "no active comfort
    preset bound to this space" (manual control / direct override mode).
    Use ``has_linked_comfort_setting`` and ``comfort_setting_id_or_none`` for
    UI-safe handling.
    """

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
        if mode in (HVACMode.STANDBY, HVACMode.UNSPECIFIED, HVACMode.FAN, HVACMode.DRY):
            # DRY has no user-configurable setpoint; temperature_setpoint_c may
            # hold a stale mirror value in that mode.
            return "--"
        if mode == HVACMode.COOL:
            return fmt(self.cooling_setpoint_c)
        if mode == HVACMode.HEAT:
            return fmt(self.heating_setpoint_c)
        if mode == HVACMode.AUTO:
            return f"{fmt(self.heating_setpoint_c)}–{fmt(self.cooling_setpoint_c)}"
        return fmt(self.temperature_setpoint_c)

    @property
    def has_standby_sentinel_setpoints(self) -> bool:
        """True when setpoints carry STANDBY sentinel values (8 °C / 40 °C).

        The server stores ``STANDBY_HEAT_SENTINEL_C`` (8.0 °C) and
        ``STANDBY_COOL_SENTINEL_C`` (40.0 °C) in the setpoint fields whenever
        the active comfort preset is of type STANDBY.  These are placeholder
        values, not real temperature targets.  UIs should suppress numeric
        setpoint display when this returns True.
        """
        return (
            self.heating_setpoint_c == STANDBY_HEAT_SENTINEL_C
            and self.cooling_setpoint_c == STANDBY_COOL_SENTINEL_C
        )

    @property
    def has_linked_comfort_setting(self) -> bool:
        """True when ``comfort_setting_id`` points to a real comfort setting."""
        return self.comfort_setting_id != EMPTY_COMFORT_SETTING_ID_SENTINEL

    @property
    def comfort_setting_id_or_none(self) -> str | None:
        """Comfort-setting ID, or None when the empty-string sentinel is present."""
        return self.comfort_setting_id if self.has_linked_comfort_setting else None

    @property
    def display_setpoint(self) -> str:
        """Human-readable setpoint string in °C.

        Use display_setpoint_str(use_f) for unit-aware formatting.
        """
        return self.display_setpoint_str(use_f=False)


@dataclass(slots=True)
class SpaceState:
    """Read-only state for a space."""

    ambient_temperature_c: float | None
    hvac_state: HVACState
    setpoint_c: float | None
    comfort_setting_id: str

    @property
    def has_missing_ambient_temperature(self) -> bool:
        """True when ambient temperature is missing (None or NaN sentinel)."""
        return self.ambient_temperature_c is None or math.isnan(self.ambient_temperature_c)

    @property
    def has_missing_setpoint(self) -> bool:
        """True when setpoint is missing (None or NaN sentinel)."""
        return self.setpoint_c is None or math.isnan(self.setpoint_c)


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

        Determined by active comfort setting type AWAY. The room
        will re-activate automatically when someone enters.

        When ``is_away`` is True, ``controls.heating_setpoint_c`` and
        ``controls.cooling_setpoint_c`` reflect the Away comfort preset's
        setpoints — not the user's normal occupancy setpoints.  To read or
        update the Away preset setpoints (regardless of current occupancy
        state), use ``SystemSnapshot.away_comfort_setting(space)``.

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
    """Internal: convert a proto Space to our model.

    Sub-messages absent from a sparse stream diff parse to sentinel values
    (``settings.name == ""``, ``controls.hvac_mode == UNSPECIFIED``,
    ``state.ambient_temperature_c is None``) that
    ``SystemSnapshot.apply_space`` uses to preserve existing snapshot data.
    """
    p = cast("Any", proto)

    sg = cast("Any", present_submsg(p, "settings"))
    if sg is not None:
        settings = SpaceSettings(
            name=sg.name,
            timezone=sg.timezone,
            occupancy_mode=OccupancyMode(sg.occupancy),
            occupied_timeout_s=sg.occupied_timeout_s,
            unoccupied_timeout_s=sg.unoccupied_timeout_s,
            safety_heating=SafetyHeatingMode(sg.safety_heating),
            hvac_controller_type=HvacControllerType(sg.hvac_controller_type),
        )
    else:
        settings = SpaceSettings(
            name="",
            timezone="",
            occupancy_mode=OccupancyMode.UNSPECIFIED,
            occupied_timeout_s=0.0,
            unoccupied_timeout_s=0.0,
            safety_heating=SafetyHeatingMode.UNSPECIFIED,
        )

    c = cast("Any", present_submsg(p, "controls"))
    if c is not None:
        controls = SpaceControls(
            hvac_mode=HVACMode(c.hvac_mode),
            temperature_setpoint_c=c.temperature_setpoint_c,
            cooling_setpoint_c=c.cooling_temperature_setpoint_c,
            heating_setpoint_c=c.heating_temperature_setpoint_c,
            comfort_setting_id=c.comfort_setting_id_string,
            comfort_setting_override=ComfortSettingOverride(c.comfort_setting_override),
            boost_mode=BoostMode(c.boost_mode),
        )
    else:
        controls = SpaceControls(
            hvac_mode=HVACMode.UNSPECIFIED,
            temperature_setpoint_c=0.0,
            cooling_setpoint_c=0.0,
            heating_setpoint_c=0.0,
            comfort_setting_id="",
            comfort_setting_override=ComfortSettingOverride.UNSPECIFIED,
        )

    st = cast("Any", present_submsg(p, "state"))
    if st is not None:
        state = SpaceState(
            ambient_temperature_c=st.ambient_temperature_c,
            hvac_state=HVACState(st.hvac_state),
            setpoint_c=st.setpoint_temperature_c,
            comfort_setting_id=st.comfort_setting_id,
        )
    else:
        state = SpaceState(
            ambient_temperature_c=None,
            hvac_state=HVACState.UNSPECIFIED,
            setpoint_c=None,
            comfort_setting_id="",
        )

    rel = cast("Any", present_submsg(p, "relationships"))
    return Space(
        id=p.header.object_id,
        system_id=p.header.system_id,
        name=settings.name,
        parent_space_id=(rel.parent_space_id or None) if rel is not None else None,
        settings=settings,
        controls=controls,
        state=state,
    )
