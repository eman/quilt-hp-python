"""SystemService and SystemInformationService.

Provides system listing and energy metrics.
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol, cast

from google.protobuf.timestamp_pb2 import Timestamp

if TYPE_CHECKING:
    import grpc.aio

from quilt_hp._proto import quilt_services_pb2 as svc
from quilt_hp._proto import quilt_services_pb2_grpc as svc_grpc
from quilt_hp.models.energy import EnergyBucket, SpaceEnergyMetrics
from quilt_hp.models.enums import MetricBucketStatus
from quilt_hp.models.system import SystemInfo
from quilt_hp.services import grpc_call

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from datetime import datetime as _datetime


class _SystemInformationServiceStub(Protocol):
    async def ListSystems(
        self, request: svc.ListSystemInformationRequest
    ) -> svc.ListSystemInformationResponse: ...

    async def GetEnergyMetrics(
        self, request: svc.GetEnergyMetricsRequest
    ) -> svc.GetEnergyMetricsResponse: ...


class SystemInformationService:
    """Async wrapper for SystemInformationService gRPC methods."""

    def __init__(self, channel: grpc.aio.Channel) -> None:
        factory = cast(
            "Callable[[grpc.aio.Channel], _SystemInformationServiceStub]",
            svc_grpc.SystemInformationServiceStub,
        )
        self._stub: _SystemInformationServiceStub = factory(channel)

    async def list_systems(self) -> list[SystemInfo]:
        """List all systems the authenticated user has access to."""
        logger.debug("Listing systems")
        async with grpc_call("ListSystems"):
            resp = await self._stub.ListSystems(svc.ListSystemInformationRequest())
        return [
            SystemInfo(
                id=s.id,
                name=s.name,
                timezone=s.tz_identifier,
            )
            for s in resp.systems
        ]

    async def get_energy_metrics(
        self,
        system_id: str,
        start: _datetime,
        end: _datetime,
    ) -> list[SpaceEnergyMetrics]:
        """Fetch hourly energy metrics for all spaces in a time range."""
        logger.debug("Fetching energy metrics for system %s", system_id)
        start_ts = Timestamp()
        start_ts.FromSeconds(int(start.timestamp()))
        end_ts = Timestamp()
        end_ts.FromSeconds(int(end.timestamp()))

        async with grpc_call("GetEnergyMetrics"):
            result = await self._stub.GetEnergyMetrics(
                svc.GetEnergyMetricsRequest(
                    system_id=system_id,
                    start_time=start_ts,
                    end_time=end_ts,
                    preferred_resolution=svc.TIME_RESOLUTION_HOURLY,
                )
            )

        metrics = []
        for sm in result.space_energy_metrics:
            buckets = [
                EnergyBucket(
                    start_time=b.start_time.ToDatetime(tzinfo=datetime.UTC),
                    energy_kwh=b.energy_kwh,
                    status=MetricBucketStatus(b.status),
                )
                for b in sm.energy_buckets
            ]
            metrics.append(SpaceEnergyMetrics(space_id=sm.space_id, buckets=buckets))
        return metrics
