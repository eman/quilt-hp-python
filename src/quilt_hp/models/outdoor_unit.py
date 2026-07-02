"""Outdoor unit model — compressor/condenser."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from quilt_hp.models._helpers import lookup_hardware, present_submsg
from quilt_hp.models.enums import HVACState


@dataclass(slots=True)
class OutdoorUnitPerformanceData:
    """Raw ODU compressor telemetry."""

    measurement_interval_s: float
    energy_measurement_j: float
    compressor_frequency_hz: float
    ambient_temperature_c: float
    coil_temperature_c: float
    exhaust_temperature_c: float
    high_pressure_kpa: float
    low_pressure_kpa: float


@dataclass(slots=True)
class OutdoorUnit:
    """A Quilt outdoor unit (compressor)."""

    id: str
    system_id: str
    space_id: str
    hvac_state: HVACState
    model_sku: str | None
    serial_number: str | None
    firmware_version: str | None
    firmware_update_info_id: str | None
    performance_data: OutdoorUnitPerformanceData | None

    @classmethod
    def from_proto(cls, proto: object, hw_map: dict[str, object] | None = None) -> OutdoorUnit:
        """Construct from a protobuf OutdoorUnit message."""
        rel = cast("Any", present_submsg(proto, "relationships"))
        hw_id = rel.hardware_id if rel is not None else None
        hw = lookup_hardware(hw_map, hw_id) if hw_map and hw_id else None

        pd = None
        p = cast("Any", present_submsg(proto, "performance_data"))
        if p is not None:
            pd = OutdoorUnitPerformanceData(
                measurement_interval_s=p.measurement_interval_s,
                energy_measurement_j=p.energy_measurement_j,
                compressor_frequency_hz=p.compressor_frequency_hz,
                ambient_temperature_c=p.ambient_temperature_c,
                coil_temperature_c=p.coil_temperature_c,
                exhaust_temperature_c=p.exhaust_temperature_c,
                high_pressure_kpa=p.high_pressure_kpa,
                low_pressure_kpa=p.low_pressure_kpa,
            )

        st = cast("Any", present_submsg(proto, "state"))
        try:
            hvac_state = HVACState(st.hvac_state) if st is not None else HVACState.UNSPECIFIED
        except ValueError:
            hvac_state = HVACState.UNSPECIFIED

        return cls(
            id=cast("Any", proto).header.object_id,
            system_id=cast("Any", proto).header.system_id,
            space_id=rel.space_id if rel is not None else "",
            hvac_state=hvac_state,
            model_sku=(cast("Any", hw).attributes.model_sku or None) if hw else None,
            serial_number=(cast("Any", hw).attributes.serial_number or None) if hw else None,
            firmware_version=(cast("Any", hw).attributes.firmware_version or None) if hw else None,
            firmware_update_info_id=(
                (rel.firmware_update_info_id or None) if rel is not None else None
            ),
            performance_data=pd,
        )
