from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import grpc
import pytest

from quilt_hp.services.streaming import NotifierStream


class _FakeRpcError(grpc.aio.AioRpcError):
    def __init__(self, code: grpc.StatusCode, details: str = "") -> None:
        self._code = code
        self._details = details

    def code(self) -> grpc.StatusCode:  # type: ignore[override]
        return self._code

    def details(self) -> str:  # type: ignore[override]
        return self._details


class _BlockingCall:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self._cancelled = asyncio.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def __aiter__(self) -> _BlockingCall:
        return self

    async def __anext__(self) -> object:
        self.started.set()
        await self._cancelled.wait()
        raise StopAsyncIteration


def _make_stream(topics: list[str] | None = None) -> NotifierStream:
    with patch("quilt_hp.services.streaming.notifier_grpc.NotifierServiceStub"):
        return NotifierStream.create(MagicMock(), topics or ["topic-a"])


@pytest.mark.asyncio
async def test_concurrent_start_stop_calls_do_not_deadlock_or_raise() -> None:
    stream = _make_stream()

    async def _wait_for_stop() -> None:
        await stream._stop_event.wait()

    stream._run_stream_with_reconnect = _wait_for_stop  # type: ignore[method-assign]

    tasks = [
        asyncio.create_task(stream.start()),
        asyncio.create_task(stream.start()),
        asyncio.create_task(stream.stop()),
        asyncio.create_task(stream.stop()),
    ]
    results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=1.0)

    assert not [result for result in results if isinstance(result, Exception)]

    await stream.stop()
    assert stream._task is None


@pytest.mark.asyncio
async def test_subscribe_during_active_reconnect_keeps_topics() -> None:
    stream = _make_stream(["topic-a"])
    stream._running = True
    stream._max_reconnects = 1

    attempts = 0
    reconnect_waiting = asyncio.Event()
    continue_reconnect = asyncio.Event()

    async def _flaky() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise _FakeRpcError(grpc.StatusCode.UNAVAILABLE, "down")
        stream._running = False

    async def _fake_wait_for_stop(_delay: float) -> bool:
        reconnect_waiting.set()
        await continue_reconnect.wait()
        return False

    stream._wait_for_stop = _fake_wait_for_stop  # type: ignore[method-assign]
    stream._run_one_stream = _flaky  # type: ignore[method-assign]

    task = asyncio.create_task(stream._run_stream_with_reconnect())
    await reconnect_waiting.wait()
    await stream.subscribe(["topic-b"])
    continue_reconnect.set()
    await task

    assert stream._topics == ["topic-a", "topic-b"]


@pytest.mark.asyncio
async def test_rapid_subscribe_and_unsubscribe_preserve_final_topics() -> None:
    stream = _make_stream(["topic-a"])

    async def _subscribe(topics: list[str], delay: float) -> None:
        await asyncio.sleep(delay)
        await stream.subscribe(topics)

    async def _unsubscribe(topics: list[str], delay: float) -> None:
        await asyncio.sleep(delay)
        await stream.unsubscribe(topics)

    await asyncio.gather(
        _subscribe(["topic-b"], 0.0),
        _unsubscribe(["topic-a"], 0.001),
        _subscribe(["topic-c"], 0.002),
        _unsubscribe(["topic-b"], 0.003),
        _subscribe(["topic-d"], 0.004),
        _unsubscribe(["topic-c"], 0.005),
    )

    assert set(stream._topics) == {"topic-d"}


@pytest.mark.asyncio
async def test_stop_during_active_run_forever_terminates_cleanly() -> None:
    stream = _make_stream(["topic-a"])
    blocking_call = _BlockingCall()
    stream._stub = MagicMock(Subscribe=lambda *_args, **_kwargs: blocking_call)

    run_task = asyncio.create_task(stream.run_forever())
    await blocking_call.started.wait()

    await stream.stop()
    await asyncio.wait_for(run_task, timeout=1.0)

    assert stream._running is False
    assert stream.stream_state == "stopped"
