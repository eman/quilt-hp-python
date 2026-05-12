"""Outdoor unit model — compressor/condenser."""

from __future__ import annotations

from dataclasses import dataclass

from quilt_hp.models._helpers import lookup_hardware


def _has_performance_data(proto: object) -> bool:
    if not hasattr(proto, "performance_data"):
        return False
    has_field = getattr(proto, "HasField", None)
    if callable(has_field):
        try:
            return bool(has_field("performance_data"))
        except ValueError:
            pass
    return True


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
    hvac_state: int
    model_sku: str | None
    serial_number: str | None
    firmware_version: str | None
    firmware_update_info_id: str | None
    performance_data: OutdoorUnitPerformanceData | None

    @classmethod
    def from_proto(cls, proto: object, hw_map: dict[str, object] | None = None) -> OutdoorUnit:
        """Construct from a protobuf OutdoorUnit message."""
        hw_id = proto.relationships.hardware_id  # type: ignore[attr-defined]
        hw = lookup_hardware(hw_map, hw_id) if hw_map else None

        pd = None
        if _has_performance_data(proto):
            p = proto.performance_data  # type: ignore[attr-defined]
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

        return cls(
            id=proto.header.object_id,  # type: ignore[attr-defined]
            system_id=proto.header.system_id,  # type: ignore[attr-defined]
            space_id=proto.relationships.space_id,  # type: ignore[attr-defined]
            hvac_state=proto.state.hvac_state,  # type: ignore[attr-defined]
            model_sku=(hw.attributes.model_sku or None) if hw else None,  # type: ignore[attr-defined]
            serial_number=(hw.attributes.serial_number or None) if hw else None,  # type: ignore[attr-defined]
            firmware_version=(hw.attributes.firmware_version or None) if hw else None,  # type: ignore[attr-defined]
            firmware_update_info_id=(
                proto.relationships.firmware_update_info_id or None  # type: ignore[attr-defined]
            ),
            performance_data=pd,
        )
