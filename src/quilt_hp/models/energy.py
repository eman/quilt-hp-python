"""Energy metrics models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(slots=True)
class EnergyBucket:
    """One hourly energy measurement slot."""

    start_time: datetime
    energy_kwh: float
    status: int  # 0=UNSPECIFIED, 1=COMPLETE, 2=INCOMPLETE


@dataclass(slots=True)
class SpaceEnergyMetrics:
    """Hourly energy buckets for one space over a time range."""

    space_id: str
    buckets: list[EnergyBucket]

    @property
    def total_kwh(self) -> float:
        """Sum of all bucket energy values."""
        return sum(b.energy_kwh for b in self.buckets)
