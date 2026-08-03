"""CommandService.

Imperative device commands. New in com.quilt.android versionCode 255.

Currently a single method, ``RequestFastUpdates``, which asks the cloud to
raise the telemetry cadence for a system. Registered in the cloud gRPC stub
only — there is no local endpoint.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    import grpc.aio

from quilt_hp._proto import quilt_hds_pb2 as hds
from quilt_hp._proto import quilt_hds_pb2_grpc as hds_grpc
from quilt_hp.models.enums import FastUpdateReason
from quilt_hp.services import grpc_call

logger = logging.getLogger(__name__)


class _CommandServiceStub(Protocol):
    async def RequestFastUpdates(self, request: hds.RequestFastUpdatesRequest) -> object: ...


class CommandService:
    """Async wrapper for CommandService gRPC methods."""

    def __init__(self, channel: grpc.aio.Channel) -> None:
        factory = cast(
            "Callable[[grpc.aio.Channel], _CommandServiceStub]",
            hds_grpc.CommandServiceStub,
        )
        self._stub: _CommandServiceStub = factory(channel)

    async def request_fast_updates(
        self,
        system_id: str,
        reason: FastUpdateReason = FastUpdateReason.USER_ACTIVITY,
    ) -> None:
        """Ask the cloud to raise the telemetry cadence for a system.

        Mirrors what the mobile app does when the user is active or the
        device's local mesh is degraded. The response is empty; the effect
        (a faster stream of state updates) is observed on the NotifierService
        stream, not in the return value.
        """
        logger.debug(
            "RPC RequestFastUpdates system_id=%s reason=%s", system_id, FastUpdateReason(reason)
        )
        async with grpc_call("RequestFastUpdates"):
            await self._stub.RequestFastUpdates(
                hds.RequestFastUpdatesRequest(
                    system_id=system_id,
                    reason=cast("hds.FastUpdateReason.ValueType", reason.value),
                )
            )
