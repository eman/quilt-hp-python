"""SystemService and SystemInformationService — system listing and energy metrics."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import grpc.aio
from google.protobuf.timestamp_pb2 import Timestamp

from quilt_hp._proto import quilt_services_pb2 as svc
from quilt_hp._proto import quilt_services_pb2_grpc as svc_grpc
from quilt_hp.exceptions import QuiltError
from quilt_hp.models.energy import EnergyBucket, SpaceEnergyMetrics
from quilt_hp.models.system import SystemInfo

if TYPE_CHECKING:
    from datetime import datetime as _datetime


class SystemInformationService:
    """Async wrapper for SystemInformationService gRPC methods."""

    def __init__(self, channel: grpc.aio.Channel) -> None:
        self._stub = svc_grpc.SystemInformationServiceStub(channel)

    async def list_systems(self) -> list[SystemInfo]:
        """List all systems the authenticated user has access to."""
        try:
            resp = await self._stub.ListSystems(svc.ListSystemInformationRequest())
        except grpc.aio.AioRpcError as exc:
            raise QuiltError(f"ListSystems failed: {exc.details()}") from exc
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
        start_ts = Timestamp()
        start_ts.FromSeconds(int(start.timestamp()))
        end_ts = Timestamp()
        end_ts.FromSeconds(int(end.timestamp()))

        try:
            result = await self._stub.GetEnergyMetrics(
                svc.GetEnergyMetricsRequest(
                    system_id=system_id,
                    start_time=start_ts,
                    end_time=end_ts,
                    preferred_resolution=svc.TIME_RESOLUTION_HOURLY,
                )
            )
        except grpc.aio.AioRpcError as exc:
            raise QuiltError(f"GetEnergyMetrics failed: {exc.details()}") from exc

        metrics = []
        for sm in result.space_energy_metrics:
            buckets = [
                EnergyBucket(
                    start_time=b.start_time.ToDatetime(tzinfo=datetime.UTC),
                    energy_kwh=b.energy_kwh,
                    status=b.status,
                )
                for b in sm.energy_buckets
            ]
            metrics.append(SpaceEnergyMetrics(space_id=sm.space_id, buckets=buckets))
        return metrics
