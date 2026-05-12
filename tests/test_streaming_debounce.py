from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace as _ns
from unittest.mock import MagicMock, patch

import pytest

from quilt_hp.services.streaming import NotifierStream, StreamEvent


def _make_stream(*, debounce_s: float) -> NotifierStream:
    with patch("quilt_hp.services.streaming.notifier_grpc.NotifierServiceStub"):
        return NotifierStream.create(
            MagicMock(),
            ["hds/space/space-1"],
            debounce_s=debounce_s,
        )


def _response() -> object:
    return _ns(control_events=[], notifier_events=[object()])


@pytest.mark.asyncio
async def test_debounce_zero_dispatches_immediately() -> None:
    stream = _make_stream(debounce_s=0.0)
    seen: list[int] = []
    stream.on_space_update(lambda space: seen.append(space.value))
    stream._parse_event = MagicMock(
        return_value=StreamEvent(topic="topic", space=_ns(id="space-1", value=72))
    )

    async def _iter() -> AsyncIterator[object]:
        yield _response()

    stream._stub = MagicMock(Subscribe=lambda *_args, **_kwargs: _iter())

    await stream._run_one_stream()

    assert seen == [72]


@pytest.mark.asyncio
async def test_debounce_coalesces_rapid_events() -> None:
    stream = _make_stream(debounce_s=0.05)
    seen: list[int] = []
    stream.on_space_update(lambda space: seen.append(space.value))
    stream._parse_event = MagicMock(
        side_effect=[
            StreamEvent(topic="topic", space=_ns(id="space-1", value=70)),
            StreamEvent(topic="topic", space=_ns(id="space-1", value=71)),
            StreamEvent(topic="topic", space=_ns(id="space-1", value=72)),
        ]
    )

    async def _iter() -> AsyncIterator[object]:
        yield _response()
        yield _response()
        yield _response()

    stream._stub = MagicMock(Subscribe=lambda *_args, **_kwargs: _iter())

    await stream._run_one_stream()
    assert seen == []

    await asyncio.sleep(0.07)

    assert seen == [72]


@pytest.mark.asyncio
async def test_debounce_dispatches_final_value_after_quiet_period() -> None:
    stream = _make_stream(debounce_s=0.05)
    seen: list[int] = []
    stream.on_space_update(lambda space: seen.append(space.value))
    stream._parse_event = MagicMock(
        side_effect=[
            StreamEvent(topic="topic", space=_ns(id="space-1", value=68)),
            StreamEvent(topic="topic", space=_ns(id="space-1", value=69)),
        ]
    )

    async def _iter() -> AsyncIterator[object]:
        yield _response()
        await asyncio.sleep(0.03)
        yield _response()

    stream._stub = MagicMock(Subscribe=lambda *_args, **_kwargs: _iter())

    await stream._run_one_stream()
    assert seen == []

    await asyncio.sleep(0.03)
    assert seen == []

    await asyncio.sleep(0.04)
    assert seen == [69]
