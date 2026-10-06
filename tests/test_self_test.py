"""Indoor-unit self-test (DiagnosticService): request building and client methods."""

from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock

from quilt_hp.client import QuiltClient
from quilt_hp.services import self_test
from tests.tui_harness import load_snapshot


def test_serial_follows_the_app() -> None:
    """The unit's own serial, else the hardware serial, else the ID's last segment."""
    idu = load_snapshot().indoor_units[0]
    own = dataclasses.replace(idu, unit_serial_number="QN1-TEST", serial_number="QS1-TEST")
    assert self_test.self_test_serial(own) == "QN1-TEST"
    hw = dataclasses.replace(idu, unit_serial_number=None, serial_number="QS1-TEST")
    assert self_test.self_test_serial(hw) == "QS1-TEST"
    bare = dataclasses.replace(
        idu, id="idu-abc-def123", unit_serial_number=None, serial_number=None
    )
    assert self_test.self_test_serial(bare) == "DEF123"


def test_requests_carry_system_and_serial_but_no_type() -> None:
    idu = dataclasses.replace(load_snapshot().indoor_units[0], unit_serial_number="QN1-TEST")
    for build in (self_test.build_start, self_test.build_cancel):
        request = build(idu)
        assert (request.system_id, request.target_serial_number) == (idu.system_id, "QN1-TEST")
        assert request.diagnostic_type == 0  # the app leaves it unset


async def test_client_resolves_the_unit_and_refreshes_the_cache() -> None:
    snap = load_snapshot()
    idu = snap.indoor_units[0]
    client = QuiltClient("user@example.com")
    client.get_snapshot = AsyncMock(return_value=snap)  # type: ignore[method-assign]
    service = AsyncMock()
    client._self_test = service

    client._snapshot_cache = object()  # type: ignore[assignment]
    await client.start_self_test(idu.id)
    service.start.assert_awaited_once_with(idu)
    assert client._snapshot_cache is None

    await client.cancel_self_test(idu)
    service.cancel.assert_awaited_once_with(idu)


async def test_service_sends_the_request() -> None:
    idu = dataclasses.replace(load_snapshot().indoor_units[0], unit_serial_number="QN1-TEST")
    service = self_test.SelfTestService.__new__(self_test.SelfTestService)
    service._stub = AsyncMock()
    await service.start(idu)
    await service.cancel(idu)
    assert service._stub.StartDiagnosticRun.await_args.args[0].target_serial_number == "QN1-TEST"
    assert service._stub.CancelDiagnosticRun.await_args.args[0].system_id == idu.system_id
