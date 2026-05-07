"""Tests for the streaming wire format parser and NotifierStream behaviour."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import grpc
import pytest

from quilt_hp.services.streaming import NotifierStream, _dispatch, _get_len_field, _parse_varint


class _FakeRpcError(grpc.aio.AioRpcError):
    """Minimal concrete AioRpcError for testing."""

    def __init__(self, code: grpc.StatusCode, details: str = "") -> None:
        self._code = code
        self._details = details

    def code(self) -> grpc.StatusCode:  # type: ignore[override]
        return self._code

    def details(self) -> str:  # type: ignore[override]
        return self._details


def test_parse_varint_single_byte() -> None:
    val, pos = _parse_varint(b"\x08", 0)
    assert val == 8
    assert pos == 1


def test_parse_varint_multi_byte() -> None:
    val, pos = _parse_varint(b"\xac\x02", 0)
    assert val == 300
    assert pos == 2


def test_get_len_field_present() -> None:
    data = b"\x0a\x05hello"
    assert _get_len_field(data, 1) == b"hello"


def test_get_len_field_absent() -> None:
    data = b"\x0a\x05hello"
    assert _get_len_field(data, 2) is None


def test_get_len_field_skip_varint() -> None:
    data = b"\x08\x2a\x12\x02ok"
    assert _get_len_field(data, 2) == b"ok"


# ─── _dispatch ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dispatch_sync_callback() -> None:
    results: list[str] = []
    def sync_cb(val: str) -> None:
        results.append(val)
    await _dispatch(sync_cb, "hello")
    assert results == ["hello"]


@pytest.mark.asyncio
async def test_dispatch_async_callback() -> None:
    results: list[str] = []
    async def async_cb(val: str) -> None:
        results.append(val)
    await _dispatch(async_cb, "world")
    assert results == ["world"]


# ─── NotifierStream — helpers ────────────────────────────────────────────────

def _make_stream(topics: list[str] | None = None) -> NotifierStream:
    channel = MagicMock()
    with patch("quilt_hp.services.streaming.notifier_grpc.NotifierServiceStub"):
        return NotifierStream.create(channel, topics or ["hds/space/test"])


# ─── callback registration ───────────────────────────────────────────────────

def test_on_space_update_registers_callback() -> None:
    stream = _make_stream()
    cb = MagicMock()
    stream.on_space_update(cb)
    assert cb in stream._space_callbacks


def test_on_indoor_unit_update_registers_callback() -> None:
    stream = _make_stream()
    cb = MagicMock()
    stream.on_indoor_unit_update(cb)
    assert cb in stream._idu_callbacks


def test_on_error_registers_callback() -> None:
    stream = _make_stream()
    cb = MagicMock()
    stream.on_error(cb)
    assert cb in stream._error_callbacks


def test_error_property_initially_none() -> None:
    assert _make_stream().error is None


# ─── event parsing ───────────────────────────────────────────────────────────

def test_parse_event_empty_topic_is_heartbeat() -> None:
    stream = _make_stream()
    evt = MagicMock()
    evt.topic = b""
    assert stream._parse_event(evt) is None


def test_parse_event_nonempty_topic_returns_event() -> None:
    stream = _make_stream()
    evt = MagicMock()
    # field 1 (type_url string), tag = (1<<3)|2 = 0x0A, length = 4
    evt.topic = b"\x0a\x04test"
    result = stream._parse_event(evt)
    assert result is not None
    assert result.topic == "test"


# ─── subscribe / unsubscribe ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subscribe_adds_topics() -> None:
    stream = _make_stream(["topic-a"])
    await stream.subscribe(["topic-b"])
    assert "topic-b" in stream._topics


@pytest.mark.asyncio
async def test_unsubscribe_removes_topics() -> None:
    stream = _make_stream(["topic-a", "topic-b"])
    await stream.unsubscribe(["topic-a"])
    assert "topic-a" not in stream._topics
    assert "topic-b" in stream._topics


# ─── lifecycle ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stop_before_start_is_safe() -> None:
    await _make_stream().stop()


@pytest.mark.asyncio
async def test_start_stop_lifecycle() -> None:
    stream = _make_stream()
    async def _noop() -> None:
        await asyncio.sleep(3600)
    stream._run_stream_with_reconnect = _noop  # type: ignore[method-assign]
    await stream.start()
    assert stream._running is True
    assert stream._task is not None
    await stream.stop()
    assert stream._running is False
    assert stream._task is None


@pytest.mark.asyncio
async def test_start_is_idempotent() -> None:
    stream = _make_stream()
    async def _noop() -> None:
        await asyncio.sleep(3600)
    stream._run_stream_with_reconnect = _noop  # type: ignore[method-assign]
    await stream.start()
    task1 = stream._task
    await stream.start()
    assert stream._task is task1
    await stream.stop()


# ─── error propagation ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_error_callback_called_on_fatal_error() -> None:
    stream = _make_stream()
    stream._max_reconnects = 0
    stream._running = True
    errors: list[Exception] = []

    async def err_cb(exc: Exception) -> None:
        errors.append(exc)

    stream.on_error(err_cb)

    rpc_error = _FakeRpcError(grpc.StatusCode.UNAVAILABLE, "broken")

    async def _failing() -> None:
        raise rpc_error

    stream._run_one_stream = _failing  # type: ignore[method-assign]
    await stream._run_stream_with_reconnect()

    assert len(errors) == 1
    assert stream.error is not None


@pytest.mark.asyncio
async def test_no_error_callbacks_raises_on_fatal() -> None:
    from quilt_hp.exceptions import QuiltStreamError

    stream = _make_stream()
    stream._max_reconnects = 0
    stream._running = True

    rpc_error = _FakeRpcError(grpc.StatusCode.UNAVAILABLE, "gone")

    async def _failing() -> None:
        raise rpc_error

    stream._run_one_stream = _failing  # type: ignore[method-assign]

    with pytest.raises(QuiltStreamError):
        await stream._run_stream_with_reconnect()


@pytest.mark.asyncio
async def test_unauthenticated_triggers_token_refresh() -> None:
    authenticate_calls: list[int] = []

    async def mock_auth() -> None:
        authenticate_calls.append(1)

    stream = _make_stream()
    stream._max_reconnects = 1
    stream._running = True
    stream._authenticate = mock_auth

    call_count = 0
    rpc_error = _FakeRpcError(grpc.StatusCode.UNAUTHENTICATED, "invalid token")

    async def _failing_then_ok() -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise rpc_error

    stream._run_one_stream = _failing_then_ok  # type: ignore[method-assign]
    await stream._run_stream_with_reconnect()

    assert len(authenticate_calls) == 1
    assert call_count == 2


# ─── context manager ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_context_manager_starts_and_stops() -> None:
    stream = _make_stream()
    async def _noop() -> None:
        await asyncio.sleep(3600)
    stream._run_stream_with_reconnect = _noop  # type: ignore[method-assign]
    async with stream:
        assert stream._running is True
    assert stream._running is False
