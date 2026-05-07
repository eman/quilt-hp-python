from __future__ import annotations

import asyncio
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
async def test_reconnect_retries_then_resubscribes(monkeypatch: pytest.MonkeyPatch) -> None:
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

    await stream._run_stream_with_reconnect()

    assert calls == 2
    assert sleep_calls == [1.0]
    assert stream._request_queue is not old_queue


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
