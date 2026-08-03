"""Derived diagnostics view over a system snapshot.

Assembles the "installer-style" diagnostic picture from data the normal cloud
API already returns. Most of what a Quilt installer inspects lives on the
**indoor unit** objects — the fault/condition matrix (including outdoor-unit and
refrigerant conditions surfaced through the IDU), the refrigerant-circuit
temperatures, and per-unit power.

The outdoor unit's *own* raw sensors (compressor frequency, suction/discharge
pressures, discharge temperature) are withheld from the cloud plane, so
:class:`OutdoorUnitDiagnostics` reports only whether they are present (they are
not, over the cloud) alongside the ODU's coarse ``hvac_state``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quilt_hp.models.enums import ConditionState, HVACState
    from quilt_hp.models.indoor_unit import IndoorUnit
    from quilt_hp.models.outdoor_unit import OutdoorUnit


@dataclass(slots=True)
class IndoorUnitDiagnostics:
    """Per-indoor-unit diagnostic summary derived from a snapshot."""

    indoor_unit_id: str
    name: str
    space_id: str
    space_name: str
    online: bool
    hvac_state: HVACState
    #: Names of conditions currently ``ACTIVE`` (i.e. faults). Empty when healthy.
    active_faults: list[str]
    #: Every condition mapped to its state; empty when the IDU sent no conditions.
    conditions: dict[str, ConditionState]
    # Refrigerant-circuit telemetry (from IndoorUnit.performance_data); None if absent.
    coil_temperature_c: float | None
    gas_pipe_temperature_c: float | None
    liquid_pipe_temperature_c: float | None
    inlet_temperature_c: float | None
    outlet_temperature_c: float | None
    inlet_humidity_pct: float | None
    # Power (from IndoorUnit.performance_metrics); None if absent.
    hvac_power_w: float | None

    @classmethod
    def from_indoor_unit(cls, idu: IndoorUnit, space_name: str = "") -> IndoorUnitDiagnostics:
        """Build a diagnostics summary for a single indoor unit."""
        conditions = idu.conditions
        pd = idu.performance_data
        pm = idu.performance_metrics
        return cls(
            indoor_unit_id=idu.id,
            name=idu.settings.name or space_name,
            space_id=idu.space_id,
            space_name=space_name,
            online=idu.is_online,
            hvac_state=idu.state.hvac_state,
            active_faults=conditions.active if conditions is not None else [],
            conditions=conditions.states() if conditions is not None else {},
            coil_temperature_c=pd.coil_temperature_c if pd is not None else None,
            gas_pipe_temperature_c=pd.gas_pipe_temperature_c if pd is not None else None,
            liquid_pipe_temperature_c=pd.liquid_pipe_temperature_c if pd is not None else None,
            inlet_temperature_c=pd.inlet_temperature_c if pd is not None else None,
            outlet_temperature_c=pd.outlet_temperature_c if pd is not None else None,
            inlet_humidity_pct=pd.inlet_humidity_pct if pd is not None else None,
            hvac_power_w=pm.hvac_power_w if pm is not None else None,
        )


@dataclass(slots=True)
class OutdoorUnitDiagnostics:
    """Per-outdoor-unit diagnostic summary.

    ``raw_sensors_available`` reflects whether the ODU's ``performance_data``
    (compressor Hz, pressures, coil/exhaust temps) is present. Over the cloud
    plane it never is — that telemetry is only reachable on the local/hardware
    track. The refrigerant conditions and pipe temperatures for this ODU's
    circuit are instead surfaced through its indoor units (see
    :class:`IndoorUnitDiagnostics`).
    """

    outdoor_unit_id: str
    hvac_state: HVACState
    raw_sensors_available: bool

    @classmethod
    def from_outdoor_unit(cls, odu: OutdoorUnit) -> OutdoorUnitDiagnostics:
        return cls(
            outdoor_unit_id=odu.id,
            hvac_state=odu.hvac_state,
            raw_sensors_available=odu.performance_data is not None,
        )


@dataclass(slots=True)
class SystemDiagnostics:
    """Whole-system diagnostic view — the installer-style summary.

    Obtain one from :meth:`SystemSnapshot.diagnostics` or
    :meth:`QuiltClient.get_diagnostics`.
    """

    indoor_units: list[IndoorUnitDiagnostics]
    outdoor_units: list[OutdoorUnitDiagnostics]

    @property
    def active_faults(self) -> list[tuple[str, str]]:
        """``(indoor_unit_id, condition_name)`` for every ACTIVE fault, system-wide."""
        return [
            (d.indoor_unit_id, condition)
            for d in self.indoor_units
            for condition in d.active_faults
        ]

    @property
    def has_faults(self) -> bool:
        """True if any indoor unit reports an ACTIVE fault condition."""
        return any(d.active_faults for d in self.indoor_units)
