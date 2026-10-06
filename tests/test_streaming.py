"""Tests for the streaming wire format parser and NotifierStream behaviour."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import grpc
import pytest
from google.protobuf import any_pb2

from quilt_hp._proto import quilt_hds_pb2 as hds
from quilt_hp._proto import quilt_notifier_pb2 as notifier
from quilt_hp.models import ControllerViewState, NotificationType
from quilt_hp.services.streaming import (
    NotifierStream,
    _dispatch,
)
from quilt_hp.tokens import TokenRefreshContext, TokenRefreshReason
from quilt_hp.tokens import invoke_refresh_callback as _invoke_refresh_callback


class _FakeRpcError(grpc.aio.AioRpcError):
    """Minimal concrete AioRpcError for testing."""

    def __init__(self, code: grpc.StatusCode, details: str = "") -> None:
        self._code = code
        self._details = details

    def code(self) -> grpc.StatusCode:  # type: ignore[override]
        return self._code

    def details(self) -> str:  # type: ignore[override]
        return self._details


def _notifier_event(topic: str, note: hds.Notification | None = None) -> notifier.NotifierEvent:
    payload = any_pb2.Any(value=note.SerializeToString()) if note is not None else None
    return notifier.NotifierEvent(topic=topic, payload=payload)


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


def test_parse_event_empty_topic_is_ignored() -> None:
    stream = _make_stream()
    assert stream._parse_event(notifier.NotifierEvent()) is None


def test_parse_event_topic_without_payload_returns_bare_event() -> None:
    stream = _make_stream()
    result = stream._parse_event(_notifier_event("hds/space/space-1"))
    assert result is not None
    assert result.topic == "hds/space/space-1"
    assert result.space is None and result.raw_bytes is None


def test_parse_event_decodes_space_diff() -> None:
    stream = _make_stream()
    space = hds.Space(header=hds.EntityMetadata(object_id="space-1"))
    space.state.ambient_temperature_c = 21.5
    note = hds.Notification(
        notification_type=hds.NOTIFICATION_TYPE_UPDATED,
        payload=hds.HomeDatastoreObjectDiff(space=space),
    )
    result = stream._parse_event(_notifier_event("hds/space/space-1", note))
    assert result is not None
    assert result.space is not None
    assert result.space.id == "space-1"
    assert result.space.state.ambient_temperature_c == pytest.approx(21.5)


def test_parse_event_decodes_controller_diff() -> None:
    stream = _make_stream()
    ctrl = hds.Controller(header=hds.EntityMetadata(object_id="dial-1"))
    ctrl.state.calculated_ambient_temperature_c = 20.0
    note = hds.Notification(payload=hds.HomeDatastoreObjectDiff(controller=ctrl))
    result = stream._parse_event(_notifier_event("hds/controller/dial-1", note))
    assert result is not None
    assert result.controller is not None
    assert result.controller.calibrated_ambient_c == pytest.approx(20.0)


def test_parse_event_unmodelled_entity_keeps_raw_bytes() -> None:
    stream = _make_stream()
    note = hds.Notification(
        payload=hds.HomeDatastoreObjectDiff(automation=hds.Automation()),
    )
    result = stream._parse_event(_notifier_event("hds/automation/a-1", note))
    assert result is not None
    assert result.raw_bytes == note.SerializeToString()


def test_parses_real_server_frame() -> None:
    """Decode a SubscribeResponse captured from the live notifier stream (2026-10-05).

    The frame is the raw gRPC message for a Dial UPDATED notification. Every string in it
    (ids, name, Wi-Fi details) was replaced by a same-length placeholder, so the wire
    layout is exactly what the server sent.
    """
    raw = (Path(__file__).parent / "fixtures" / "subscribe_response_controller.bin").read_bytes()
    resp = notifier.SubscribeResponse.FromString(raw)
    assert len(resp.event.notifier_events) == 1
    evt = resp.event.notifier_events[0]
    assert evt.payload.type_url == "type.googleapis.com/core.protos.home_datastore.Notification"

    parsed = _make_stream()._parse_event(evt)

    assert parsed is not None
    assert parsed.topic == "hds/controller/00000000-0000-4000-8000-000000000001"
    assert parsed.notification_type is NotificationType.UPDATED
    assert parsed.controller is not None
    assert parsed.controller.id == "00000000-0000-4000-8000-000000000001"
    assert parsed.controller.view_state is ControllerViewState.GLANCE
    assert parsed.controller.screen_brightness == pytest.approx(0.5)
    assert parsed.controller.state_updated_at is not None


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


@pytest.mark.asyncio
async def test_subscribe_after_queue_reset_resubscribes_from_topics() -> None:
    stream = _make_stream(["topic-a"])
    stream._running = True  # simulate a live stream mid-reconnect
    stream._request_queue = asyncio.Queue()

    await stream.subscribe(["topic-b"])

    request_iterator = stream._request_iterator(list(stream._topics), stream._request_queue)
    initial = await anext(request_iterator)
    queued = await anext(request_iterator)
    await request_iterator.aclose()

    assert [sub.topic for sub in initial.append.subscriptions] == ["topic-a", "topic-b"]
    assert [sub.topic for sub in queued.append.subscriptions] == ["topic-b"]


@pytest.mark.asyncio
async def test_subscribe_before_start_does_not_queue_duplicate_request() -> None:
    stream = _make_stream(["topic-a"])

    await stream.subscribe(["topic-b"])

    # Before start, only _topics is extended; the initial request snapshots
    # it, so queueing as well would send topic-b twice on the first stream.
    assert stream._topics == ["topic-a", "topic-b"]
    assert stream._request_queue.empty()


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


@pytest.mark.asyncio
async def test_stream_refresh_callback_receives_context() -> None:
    captured: list[TokenRefreshContext] = []

    async def _with_context(context: TokenRefreshContext) -> None:
        captured.append(context)

    context = TokenRefreshContext(
        reason=TokenRefreshReason.STREAM_UNAUTHENTICATED,
        source="test",
        attempt=2,
    )
    await _invoke_refresh_callback(_with_context, context)
    assert captured == [context]


# ─── deletions ───────────────────────────────────────────────────────────────


def _space_note(notification_type: int, space_id: str = "space-1") -> hds.Notification:
    space = hds.Space(header=hds.EntityMetadata(object_id=space_id))
    return hds.Notification(
        notification_type=notification_type,  # type: ignore[arg-type]
        payload=hds.HomeDatastoreObjectDiff(space=space),
        system_version=42,
    )


def test_parse_event_records_notification_type_and_system_version() -> None:
    from quilt_hp.models import NotificationType

    stream = _make_stream()
    parsed = stream._parse_event(
        _notifier_event("hds/space/space-1", _space_note(hds.NOTIFICATION_TYPE_DELETED))
    )
    assert parsed is not None
    assert parsed.notification_type is NotificationType.DELETED
    assert parsed.system_version == 42


@pytest.mark.asyncio
async def test_deleted_event_goes_to_delete_callbacks_not_updates() -> None:
    stream = _make_stream()
    updates: list[object] = []
    deletes: list[tuple[str, str]] = []
    stream.on_space_update(updates.append)
    stream.on_delete(lambda kind, entity_id: deletes.append((kind, entity_id)))

    parsed = stream._parse_event(
        _notifier_event("hds/space/space-1", _space_note(hds.NOTIFICATION_TYPE_DELETED))
    )
    assert parsed is not None
    await stream._dispatch_parsed_event(parsed)

    assert deletes == [("space", "space-1")]
    assert updates == []


@pytest.mark.asyncio
async def test_delete_cancels_pending_debounced_update() -> None:
    with patch("quilt_hp.services.streaming.notifier_grpc.NotifierServiceStub"):
        stream = NotifierStream.create(MagicMock(), ["hds/space/space-1"], debounce_s=0.05)
    updates: list[object] = []
    stream.on_space_update(updates.append)

    for kind in (hds.NOTIFICATION_TYPE_UPDATED, hds.NOTIFICATION_TYPE_DELETED):
        parsed = stream._parse_event(_notifier_event("hds/space/space-1", _space_note(kind)))
        assert parsed is not None
        await stream._dispatch_parsed_event(parsed)
    await asyncio.sleep(0.1)

    assert updates == []


def test_snapshot_remove_drops_object() -> None:
    from quilt_hp.models import SystemSnapshot

    system = hds.HomeDatastoreSystem()
    system.spaces.add().header.object_id = "space-1"
    system.spaces.add().header.object_id = "space-2"
    snap = SystemSnapshot.from_proto(system)

    assert snap.remove("space", "space-1") is True
    assert [s.id for s in snap.spaces] == ["space-2"]
    assert snap.remove("space", "space-1") is False
    with pytest.raises(ValueError, match="unknown entity kind"):
        snap.remove("gizmo", "x")


@pytest.mark.asyncio
async def test_child_deleted_goes_to_delete_callbacks() -> None:
    """CHILD_DELETED arrives on the parent's topic and carries the deleted child."""
    stream = _make_stream()
    updates: list[object] = []
    deletes: list[tuple[str, str]] = []
    stream.on_indoor_unit_update(updates.append)
    stream.on_delete(lambda kind, entity_id: deletes.append((kind, entity_id)))
    note = hds.Notification(
        notification_type=hds.NOTIFICATION_TYPE_CHILD_DELETED,
        payload=hds.HomeDatastoreObjectDiff(
            indoor_unit=hds.IndoorUnit(header=hds.EntityMetadata(object_id="idu-1"))
        ),
    )

    parsed = stream._parse_event(_notifier_event("hds/space/space-1", note))
    assert parsed is not None
    await stream._dispatch_parsed_event(parsed)

    assert deletes == [("indoor_unit", "idu-1")]
    assert updates == []


@pytest.mark.asyncio
async def test_in_flight_update_cannot_resurrect_deleted_object() -> None:
    """An async update callback that awaits before applying must not re-add a deleted object."""
    from quilt_hp.models import SystemSnapshot

    system = hds.HomeDatastoreSystem()
    space = system.spaces.add()
    space.header.object_id = "space-1"
    space.settings.name = "Den"
    snap = SystemSnapshot.from_proto(system)
    with patch("quilt_hp.services.streaming.notifier_grpc.NotifierServiceStub"):
        stream = NotifierStream.create(MagicMock(), ["hds/space/space-1"], debounce_s=0.01)

    async def on_update(updated: object) -> None:
        await asyncio.sleep(0.03)  # e.g. awaiting I/O before merging
        snap.apply_space(updated)  # type: ignore[arg-type]

    stream.on_space_update(on_update)
    stream.on_delete(snap.remove)
    update = stream._parse_event(
        _notifier_event("hds/space/space-1", _space_note(hds.NOTIFICATION_TYPE_UPDATED))
    )
    delete = stream._parse_event(
        _notifier_event("hds/space/space-1", _space_note(hds.NOTIFICATION_TYPE_DELETED))
    )
    assert update is not None and delete is not None

    await stream._dispatch_parsed_event(update)
    await asyncio.sleep(0.02)  # debounce fired; the update callback is mid-await
    await stream._dispatch_parsed_event(delete)
    await asyncio.sleep(0.05)

    assert snap.spaces == []
