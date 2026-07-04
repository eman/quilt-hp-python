from __future__ import annotations

import asyncio
import logging
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


@pytest.mark.asyncio
async def test_parse_event_decode_and_raw_fallback_branches() -> None:
    stream = _make_stream()

    evt_no_notif = SimpleNamespace(topic=b"\x0a\x01\xff")
    parsed = stream._parse_event(evt_no_notif)
    assert parsed is not None
    assert parsed.topic

    notif = b"\x12\x03abc"
    evt_no_inner = SimpleNamespace(topic=b"\x0a\x04test\x12\x05" + notif)
    parsed_inner = stream._parse_event(evt_no_inner)
    assert parsed_inner is not None
    assert parsed_inner.raw_bytes == b"abc"


@pytest.mark.asyncio
async def test_run_one_stream_dispatches_callbacks_and_swallows_callback_errors() -> None:
    stream = _make_stream()

    values: list[str] = []

    async def _space_cb(_arg: object) -> None:
        values.append("space")

    def _idu_cb(_arg: object) -> None:
        values.append("idu")
        raise RuntimeError("ignore")

    stream.on_space_update(_space_cb)
    stream.on_indoor_unit_update(_idu_cb)
    stream.on_outdoor_unit_update(lambda _arg: values.append("odu"))
    stream.on_controller_update(lambda _arg: values.append("ctrl"))
    stream.on_qsm_update(lambda _arg: values.append("qsm"))
    stream.on_remote_sensor_update(lambda _arg: values.append("rs"))
    stream.on_controller_remote_sensor_update(lambda _arg: values.append("crs"))
    stream.on_software_update_info(lambda _arg: values.append("sui"))

    stream._parse_event = MagicMock(
        return_value=StreamEvent(
            topic="topic",
            space=object(),
            indoor_unit=object(),
            outdoor_unit=object(),
            controller=object(),
            qsm=object(),
            remote_sensor=object(),
            controller_remote_sensor=object(),
            software_update_info=object(),
        )
    )

    response = SimpleNamespace(
        control_events=[SimpleNamespace(type=0, topics=["hds/space/space-1"])],
        notifier_events=[object()],
    )

    async def _iter() -> asyncio.AsyncIterator[object]:
        yield response

    stream._stub = MagicMock(Subscribe=lambda *_args, **_kwargs: _iter())
    await stream._run_one_stream()
    assert values == ["space", "idu", "odu", "ctrl", "qsm", "rs", "crs", "sui"]


@pytest.mark.asyncio
async def test_reconnect_retries_then_resubscribes(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
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

    old_queue = stream._request_queue
    stream._run_one_stream = _flaky  # type: ignore[method-assign]

    sleep_calls: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("quilt_hp.services.streaming.asyncio.sleep", _fake_sleep)

    with caplog.at_level(logging.INFO):
        await stream._run_stream_with_reconnect()

    assert calls == 2
    # Back-off is 1.0s with ±50% jitter applied at sleep time.
    assert len(sleep_calls) == 1
    assert 0.5 <= sleep_calls[0] <= 1.5
    assert stream._request_queue is not old_queue
    assert "Resetting subscription queue before reconnect" in caplog.text


@pytest.mark.asyncio
async def test_unauth_refresh_failure_sets_error_and_calls_error_callback() -> None:
    stream = _make_stream()
    stream._running = True
    stream._max_reconnects = 2
    stream._run_one_stream = AsyncMock(
        side_effect=_FakeRpcError(grpc.StatusCode.UNAUTHENTICATED, "bad")
    )

    async def _refresh(_context) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("refresh failed")

    stream._authenticate = _refresh

    seen: list[Exception] = []
    stream.on_error(lambda exc: seen.append(exc))

    await stream._run_stream_with_reconnect()
    assert stream.error is not None
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_run_forever_propagates_error_without_callbacks() -> None:
    stream = _make_stream()
    stream._running = True
    stream._max_reconnects = 0
    stream._run_one_stream = AsyncMock(
        side_effect=_FakeRpcError(grpc.StatusCode.UNAVAILABLE, "down")
    )

    with pytest.raises(QuiltStreamError):
        await stream._run_stream_with_reconnect()


@pytest.mark.asyncio
async def test_on_task_done_logs_only_for_exceptions() -> None:
    stream = _make_stream()
    cancelled_task = MagicMock(cancelled=lambda: True)
    stream._on_task_done(cancelled_task)

    error_task = MagicMock(cancelled=lambda: False, exception=lambda: RuntimeError("boom"))
    stream._on_task_done(error_task)


@pytest.mark.asyncio
async def test_non_grpc_error_reconnects_then_surfaces_via_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected (non-AioRpcError) failures reconnect and, once the budget
    is exhausted, surface via on_error instead of silently killing the task."""
    stream = _make_stream()
    stream._running = True
    stream._max_reconnects = 1

    calls = 0

    async def _broken() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("metadata provider exploded")

    stream._run_one_stream = _broken  # type: ignore[method-assign]
    monkeypatch.setattr("quilt_hp.services.streaming.asyncio.sleep", AsyncMock())

    errors: list[Exception] = []
    stream.on_error(errors.append)

    await stream._run_stream_with_reconnect()

    assert calls == 2  # initial + one reconnect
    assert stream.stream_state == "error"
    assert len(errors) == 1
    assert isinstance(errors[0], QuiltStreamError)


@pytest.mark.asyncio
async def test_backoff_and_budget_reset_after_healthy_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A connection that stays up past the health threshold resets attempt
    and delay, so routine stream recycling never escalates to 60s waits."""
    stream = _make_stream()
    stream._running = True
    stream._max_reconnects = 1  # one consecutive retry allowed

    clock = {"now": 0.0}
    monkeypatch.setattr("quilt_hp.services.streaming.time.monotonic", lambda: clock["now"])

    sleeps: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("quilt_hp.services.streaming.asyncio.sleep", _fake_sleep)

    calls = 0

    async def _recycled() -> None:
        nonlocal calls
        calls += 1
        # Each connection lives 120s (> healthy threshold) before the server
        # recycles it — with per-lifetime counting the old code died here.
        clock["now"] += 120.0
        if calls >= 4:
            stream._running = False
            return
        raise _FakeRpcError(grpc.StatusCode.CANCELLED, "recycled")

    stream._run_one_stream = _recycled  # type: ignore[method-assign]

    await stream._run_stream_with_reconnect()

    assert calls == 4  # three recycles + final clean run — budget never exhausted
    assert stream.error is None
    # Delay never escalated: every wait is the initial 1.0s (±50% jitter).
    assert all(0.5 <= s <= 1.5 for s in sleeps)


@pytest.mark.asyncio
async def test_token_refresh_success_reconnects_without_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = _make_stream()
    stream._running = True
    refreshed: list[str] = []

    async def _refresh() -> None:
        refreshed.append("yes")

    stream._authenticate = _refresh

    calls = 0

    async def _unauth_once() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _FakeRpcError(grpc.StatusCode.UNAUTHENTICATED, "expired")
        stream._running = False

    stream._run_one_stream = _unauth_once  # type: ignore[method-assign]

    sleeps: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("quilt_hp.services.streaming.asyncio.sleep", _fake_sleep)

    await stream._run_stream_with_reconnect()

    assert refreshed == ["yes"]
    assert calls == 2
    assert sleeps == [0.0]  # prompt reconnect after successful refresh


@pytest.mark.asyncio
async def test_on_connected_fires_per_connect_and_unsubscribe_detaches() -> None:
    stream = _make_stream()
    connected: list[str] = []
    unsubscribe = stream.on_connected(lambda: connected.append("up"))

    async def _empty_iter() -> asyncio.AsyncIterator[object]:
        return
        yield

    stream._stub = MagicMock(Subscribe=lambda *_a, **_k: _empty_iter())
    await stream._run_one_stream()
    assert connected == ["up"]

    unsubscribe()
    await stream._run_one_stream()
    assert connected == ["up"]  # detached — no second invocation


@pytest.mark.asyncio
async def test_malformed_event_is_skipped_not_fatal() -> None:
    stream = _make_stream()
    seen: list[object] = []
    stream.on_space_update(seen.append)

    good_event = StreamEvent(topic="t", space=object())
    parse = MagicMock(side_effect=[IndexError("truncated varint"), good_event])
    stream._parse_event = parse  # type: ignore[method-assign]

    response = SimpleNamespace(control_events=[], notifier_events=[object(), object()])

    async def _iter() -> asyncio.AsyncIterator[object]:
        yield response

    stream._stub = MagicMock(Subscribe=lambda *_a, **_k: _iter())
    await stream._run_one_stream()  # must not raise

    assert parse.call_count == 2
    assert len(seen) == 1  # the good event still dispatched
