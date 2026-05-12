"""Energy metrics models."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from quilt_hp.models.enums import MetricBucketStatus

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(slots=True)
class EnergyBucket:
    """One hourly energy measurement slot."""

    start_time: datetime
    energy_kwh: float
    status: MetricBucketStatus

    @property
    def has_missing_energy_value(self) -> bool:
        """True when energy_kwh is missing: either not a float or NaN sentinel."""
        return not isinstance(self.energy_kwh, float) or math.isnan(self.energy_kwh)

    @property
    def is_valid(self) -> bool:
        """True when this bucket carries a usable numeric energy value."""
        return self.energy_kwh_or_none is not None

    @property
    def energy_kwh_or_none(self) -> float | None:
        """Energy value, or None when this bucket is missing or NaN."""
        return None if self.has_missing_energy_value else self.energy_kwh


@dataclass(slots=True)
class SpaceEnergyMetrics:
    """Hourly energy buckets for one space over a time range."""

    space_id: str
    buckets: list[EnergyBucket]

    @property
    def total_kwh(self) -> float:
        """Sum of valid bucket values, ignoring NaN sentinel buckets."""
        return sum(b.energy_kwh for b in self.buckets if not b.has_missing_energy_value)

    @property
    def missing_bucket_count(self) -> int:
        """Number of energy buckets carrying NaN sentinel values."""
        return sum(1 for b in self.buckets if b.has_missing_energy_value)
