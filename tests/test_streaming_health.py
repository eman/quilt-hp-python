from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import grpc
import pytest

from quilt_hp.exceptions import QuiltStreamError
from quilt_hp.services.streaming import NotifierStream, StreamEvent


class _FakeRpcError(grpc.aio.AioRpcError):
    def __init__(self, code: grpc.StatusCode, details: str = "") -> None:
        self._code = code
        self._details = details

    def code(self) -> grpc.StatusCode:  # type: ignore[override]
        return self._code

    def details(self) -> str:  # type: ignore[override]
        return self._details


def _make_stream() -> NotifierStream:
    with patch("quilt_hp.services.streaming.notifier_grpc.NotifierServiceStub"):
        return NotifierStream.create(MagicMock(), ["hds/space/space-1"])


def test_health_properties_default_to_idle() -> None:
    stream = _make_stream()

    assert stream.is_connected is False
    assert stream.last_event_at is None
    assert stream.stream_state == "idle"


@pytest.mark.asyncio
async def test_run_one_stream_marks_connected_and_tracks_last_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = _make_stream()
    stream._running = True
    states: list[tuple[bool, str]] = []

    async def _space_cb(_space: object) -> None:
        states.append((stream.is_connected, stream.stream_state))

    stream.on_space_update(_space_cb)
    stream._parse_event = MagicMock(return_value=StreamEvent(topic="topic", space=object()))
    monkeypatch.setattr("quilt_hp.services.streaming.time.monotonic", lambda: 123.4)

    response = SimpleNamespace(control_events=[], notifier_events=[object()])

    async def _iter() -> AsyncIterator[object]:
        yield response

    stream._stub = MagicMock(Subscribe=lambda *_args, **_kwargs: _iter())
    await stream._run_one_stream()

    assert states == [(True, "connected")]
    assert stream.last_event_at == 123.4
    assert stream.is_connected is True
    assert stream.stream_state == "connected"


@pytest.mark.asyncio
async def test_reconnect_state_is_exposed_during_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _make_stream()
    stream._running = True
    stream._max_reconnects = 1

    calls = 0

    async def _flaky() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _FakeRpcError(grpc.StatusCode.UNAVAILABLE, "down")
        stream._running = False

    seen_states: list[str] = []

    async def _fake_sleep(_delay: float) -> None:
        seen_states.append(stream.stream_state)

    stream._run_one_stream = _flaky  # type: ignore[method-assign]
    monkeypatch.setattr("quilt_hp.services.streaming.asyncio.sleep", _fake_sleep)

    await stream._run_stream_with_reconnect()

    assert seen_states == ["reconnecting"]
    assert stream.is_connected is False
    assert stream.stream_state == "stopped"


@pytest.mark.asyncio
async def test_fatal_stream_error_sets_error_state() -> None:
    stream = _make_stream()
    stream._running = True
    stream._max_reconnects = 0
    stream._run_one_stream = AsyncMock(
        side_effect=_FakeRpcError(grpc.StatusCode.UNAVAILABLE, "down")
    )

    with pytest.raises(QuiltStreamError):
        await stream._run_stream_with_reconnect()

    assert stream.is_connected is False
    assert stream.stream_state == "error"


@pytest.mark.asyncio
async def test_stop_marks_stream_stopped() -> None:
    stream = _make_stream()

    async def _noop() -> None:
        await asyncio.sleep(3600)

    stream._run_stream_with_reconnect = _noop  # type: ignore[method-assign]
    await stream.start()
    await stream.stop()

    assert stream.is_connected is False
    assert stream.stream_state == "stopped"
