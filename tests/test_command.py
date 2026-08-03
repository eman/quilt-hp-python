"""Tests for CommandService/RequestFastUpdates and the client wrapper."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import grpc
import pytest

from quilt_hp._proto import quilt_hds_pb2 as hds
from quilt_hp.client import QuiltClient
from quilt_hp.exceptions import QuiltError
from quilt_hp.models.enums import FastUpdateReason
from quilt_hp.services import command as command_service


class _FakeRpcError(grpc.aio.AioRpcError):
    def __init__(self, code: grpc.StatusCode, details: str = "") -> None:
        self._code = code
        self._details = details

    def code(self) -> grpc.StatusCode:  # type: ignore[override]
        return self._code

    def details(self) -> str:  # type: ignore[override]
        return self._details


@pytest.mark.asyncio
async def test_request_fast_updates_builds_request(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = MagicMock(RequestFastUpdates=AsyncMock(return_value=None))
    monkeypatch.setattr(command_service.hds_grpc, "CommandServiceStub", lambda _ch: stub)

    svc = command_service.CommandService(MagicMock())
    await svc.request_fast_updates("sys-1", FastUpdateReason.LOCAL_COMMS_UNHEALTHY)

    stub.RequestFastUpdates.assert_awaited_once()
    sent = stub.RequestFastUpdates.await_args.args[0]
    assert isinstance(sent, hds.RequestFastUpdatesRequest)
    assert sent.system_id == "sys-1"
    assert sent.reason == hds.FAST_UPDATE_REASON_LOCAL_COMMS_UNHEALTHY


@pytest.mark.asyncio
async def test_request_fast_updates_default_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = MagicMock(RequestFastUpdates=AsyncMock(return_value=None))
    monkeypatch.setattr(command_service.hds_grpc, "CommandServiceStub", lambda _ch: stub)

    svc = command_service.CommandService(MagicMock())
    await svc.request_fast_updates("sys-1")

    sent = stub.RequestFastUpdates.await_args.args[0]
    assert sent.reason == hds.FAST_UPDATE_REASON_USER_ACTIVITY


@pytest.mark.asyncio
async def test_request_fast_updates_translates_grpc_error(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = MagicMock(
        RequestFastUpdates=AsyncMock(side_effect=_FakeRpcError(grpc.StatusCode.INTERNAL, "boom"))
    )
    monkeypatch.setattr(command_service.hds_grpc, "CommandServiceStub", lambda _ch: stub)

    svc = command_service.CommandService(MagicMock())
    with pytest.raises(QuiltError, match="RequestFastUpdates failed"):
        await svc.request_fast_updates("sys-1")


@pytest.mark.asyncio
async def test_client_request_fast_updates_resolves_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = QuiltClient("user@example.com")
    command = MagicMock(request_fast_updates=AsyncMock(return_value=None))
    client._command = command
    monkeypatch.setattr(client, "_resolve_system_id", AsyncMock(return_value="sys-42"))

    await client.request_fast_updates(reason=FastUpdateReason.USER_ACTIVITY)

    command.request_fast_updates.assert_awaited_once_with("sys-42", FastUpdateReason.USER_ACTIVITY)


@pytest.mark.asyncio
async def test_client_request_fast_updates_requires_connection() -> None:
    client = QuiltClient("user@example.com")
    with pytest.raises(QuiltError, match="not connected"):
        await client.request_fast_updates()
