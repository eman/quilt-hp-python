from __future__ import annotations

import logging

import grpc
import pytest

from quilt_hp.exceptions import QuiltConnectionError, QuiltError
from quilt_hp.services import grpc_call


class _FakeRpcError(grpc.aio.AioRpcError):
    def __init__(self, code: grpc.StatusCode, details: str = "") -> None:
        self._code = code
        self._details = details

    def code(self) -> grpc.StatusCode:  # type: ignore[override]
        return self._code

    def details(self) -> str:  # type: ignore[override]
        return self._details


@pytest.mark.asyncio
async def test_grpc_call_translates_transient_errors_without_retries() -> None:
    with pytest.raises(QuiltConnectionError, match="ListSystems failed: down"):
        async with grpc_call("ListSystems"):
            raise _FakeRpcError(grpc.StatusCode.UNAVAILABLE, "down")


@pytest.mark.asyncio
async def test_grpc_call_retries_transient_errors(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls = 0
    sleep_calls: list[float] = []

    async def _flaky(_request: object) -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise _FakeRpcError(grpc.StatusCode.UNAVAILABLE, "down")
        return "ok"

    async def _fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("quilt_hp.services.asyncio.sleep", _fake_sleep)

    with caplog.at_level(logging.WARNING):
        async with grpc_call(
            "ListSystems", max_retries=2, retry_delay=0.5, retry_backoff=3.0
        ) as call:
            result = await call(_flaky, object())

    assert result == "ok"
    assert calls == 3
    assert sleep_calls == [0.5, 1.5]
    assert "retrying in 0.5s (1/2)" in caplog.text
    assert "retrying in 1.5s (2/2)" in caplog.text


@pytest.mark.asyncio
async def test_grpc_call_stops_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    sleep_calls: list[float] = []

    async def _always_fails() -> None:
        nonlocal calls
        calls += 1
        raise _FakeRpcError(grpc.StatusCode.DEADLINE_EXCEEDED, "timeout")

    async def _fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("quilt_hp.services.asyncio.sleep", _fake_sleep)

    with pytest.raises(QuiltConnectionError, match="GetEnergyMetrics failed: timeout"):
        async with grpc_call("GetEnergyMetrics", max_retries=1) as call:
            await call(_always_fails)

    assert calls == 2
    assert sleep_calls == [1.0]


@pytest.mark.asyncio
async def test_grpc_call_does_not_retry_non_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep_calls: list[float] = []

    async def _unknown() -> None:
        raise _FakeRpcError(grpc.StatusCode.UNKNOWN, "boom")

    async def _fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("quilt_hp.services.asyncio.sleep", _fake_sleep)

    with pytest.raises(QuiltError, match="UpdateSpace failed: boom"):
        async with grpc_call("UpdateSpace", max_retries=3) as call:
            await call(_unknown)

    assert sleep_calls == []


@pytest.mark.asyncio
async def test_grpc_call_preserves_existing_quilt_errors() -> None:
    with pytest.raises(QuiltError, match="already wrapped"):
        async with grpc_call("UpdateSpace", max_retries=3) as call:
            await call(_raise_wrapped)


async def _raise_wrapped() -> None:
    raise QuiltError("already wrapped")
