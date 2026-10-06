"""DiagnosticService: start or cancel an indoor unit's diagnostic self-test.

This is the app's "Run diagnostic test" (Quilt app 1.0.33). The test takes up to 30 minutes,
during which the unit's room can't be heated or cooled; Quilt (and a certified partner, if
the home has one) sees the results. The server returns nothing: follow progress through
``IndoorUnit.is_under_test`` (``test_state.test_mode`` is ``HEALTH_CHECK`` while it runs).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from quilt_hp._proto import quilt_services_pb2 as svc
from quilt_hp._proto import quilt_services_pb2_grpc as svc_grpc
from quilt_hp.services import grpc_call

if TYPE_CHECKING:
    import grpc.aio

    from quilt_hp.models.indoor_unit import IndoorUnit

logger = logging.getLogger(__name__)


def self_test_serial(idu: IndoorUnit) -> str:
    """The serial the app sends to identify a unit's test (``v9e.d`` in app 1.0.33).

    The unit's own serial (``QN1-…``), else its hardware serial, else the last segment of
    its object ID in upper case.
    """
    if idu.unit_serial_number:
        return idu.unit_serial_number
    if idu.serial_number:
        return idu.serial_number
    return idu.id.split("-")[-1].upper()


def build_start(idu: IndoorUnit) -> svc.StartDiagnosticRunRequest:
    # The app leaves diagnostic_type unset; so do we.
    return svc.StartDiagnosticRunRequest(
        system_id=idu.system_id, target_serial_number=self_test_serial(idu)
    )


def build_cancel(idu: IndoorUnit) -> svc.CancelDiagnosticRunRequest:
    return svc.CancelDiagnosticRunRequest(
        system_id=idu.system_id, target_serial_number=self_test_serial(idu)
    )


class SelfTestService:
    """Async wrapper for ``DiagnosticService`` (start / cancel)."""

    def __init__(self, channel: grpc.aio.Channel) -> None:
        factory = cast("Callable[[grpc.aio.Channel], Any]", svc_grpc.DiagnosticServiceStub)
        self._stub = factory(channel)

    async def start(self, idu: IndoorUnit) -> None:
        request = build_start(idu)
        logger.debug("RPC StartDiagnosticRun indoor_unit_id=%s", idu.id)
        async with grpc_call("StartDiagnosticRun"):
            await self._stub.StartDiagnosticRun(request)

    async def cancel(self, idu: IndoorUnit) -> None:
        request = build_cancel(idu)
        logger.debug("RPC CancelDiagnosticRun indoor_unit_id=%s", idu.id)
        async with grpc_call("CancelDiagnosticRun"):
            await self._stub.CancelDiagnosticRun(request)
