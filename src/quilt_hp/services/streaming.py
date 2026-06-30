"""NotifierService streaming - real-time HDS change subscriptions.

Handles the complex nested wire format:
  NotifierEvent.topic (bytes) -> C1517Ta{type_url, value} ->
    google.protobuf.Any -> HdsNotification -> HomeDatastoreObjectDiff
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

import grpc
import grpc.aio

from quilt_hp._proto import quilt_hds_pb2 as hds
from quilt_hp._proto import quilt_notifier_pb2 as notifier
from quilt_hp._proto import quilt_notifier_pb2_grpc as notifier_grpc
from quilt_hp.exceptions import QuiltStreamError
from quilt_hp.models.controller import Controller
from quilt_hp.models.indoor_unit import IndoorUnit
from quilt_hp.models.outdoor_unit import OutdoorUnit
from quilt_hp.models.qsm import QuiltSmartModule
from quilt_hp.models.sensor import ControllerRemoteSensor, RemoteSensor
from quilt_hp.models.software_update import SoftwareUpdateInfo
from quilt_hp.models.space import Space
from quilt_hp.tokens import TokenRefreshContext, TokenRefreshReason, invoke_refresh_callback

logger = logging.getLogger(__name__)

# Callbacks may be sync or async.
SpaceCallback = Callable[[Space], Awaitable[None] | None]
IndoorUnitCallback = Callable[[IndoorUnit], Awaitable[None] | None]
OutdoorUnitCallback = Callable[[OutdoorUnit], Awaitable[None] | None]
ControllerCallback = Callable[[Controller], Awaitable[None] | None]
QsmCallback = Callable[[QuiltSmartModule], Awaitable[None] | None]
RemoteSensorCallback = Callable[[RemoteSensor], Awaitable[None] | None]
ControllerRemoteSensorCallback = Callable[[ControllerRemoteSensor], Awaitable[None] | None]
SoftwareUpdateInfoCallback = Callable[[SoftwareUpdateInfo], Awaitable[None] | None]
ErrorCallback = Callable[[Exception], Awaitable[None] | None]


class _NotifierServiceStub(Protocol):
    def Subscribe(
        self,
        request_iterator: AsyncIterator[notifier.SubscribeRequest],
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[notifier.SubscribeResponse]: ...


RefreshCallback = Callable[[], Awaitable[None]] | Callable[[TokenRefreshContext], Awaitable[None]]

type _EventKey = tuple[str, str]
type _AnyCallback = Callable[[Any], Awaitable[None] | None]


def _parse_varint(data: bytes, pos: int) -> tuple[int, int]:
    """Parse a protobuf varint from raw bytes."""
    result, shift = 0, 0
    while True:
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return result, pos


def _get_len_field(data: bytes, field_num: int) -> bytes | None:
    """Extract the first LEN-encoded field with the given field number."""
    pos = 0
    while pos < len(data):
        tag, pos = _parse_varint(data, pos)
        fnum = tag >> 3
        wtype = tag & 0x7
        if wtype == 0:  # varint
            _, pos = _parse_varint(data, pos)
        elif wtype == 2:  # length-delimited
            length, pos = _parse_varint(data, pos)
            if fnum == field_num:
                return data[pos : pos + length]
            pos += length
        elif wtype == 5:  # 32-bit
            pos += 4
        elif wtype == 1:  # 64-bit
            pos += 8
        else:
            break
    return None


def _make_subscribe_request(topics: list[str]) -> notifier.SubscribeRequest:
    """Build a SubscribeRequest for the given topic list."""
    return notifier.SubscribeRequest(
        append=notifier.TopicsMessage(
            subscriptions=[notifier.Subscription(topic=t) for t in topics]
        )
    )


async def _dispatch[T](cb: Callable[[T], Awaitable[None] | None], arg: T) -> None:
    """Call a callback, awaiting it if it returns a coroutine."""
    result = cb(arg)
    if asyncio.iscoroutine(result):
        await result


@dataclass(slots=True)
class StreamEvent:
    """A parsed notification event from the stream."""

    topic: str
    space: Space | None = None
    indoor_unit: IndoorUnit | None = None
    outdoor_unit: OutdoorUnit | None = None
    controller: Controller | None = None
    qsm: QuiltSmartModule | None = None
    remote_sensor: RemoteSensor | None = None
    controller_remote_sensor: ControllerRemoteSensor | None = None
    software_update_info: SoftwareUpdateInfo | None = None
    raw_bytes: bytes | None = None


@dataclass(slots=True)
class _PendingDispatch:
    value: Any
    callbacks: tuple[_AnyCallback, ...]
    error_message: str
    task: asyncio.Task[None]


@dataclass
class NotifierStream:
    """Async manager for the NotifierService bidirectional stream.

    Usage as a background task (for integrations)::

        async with client.stream(topics) as stream:
            stream.on_space_update(my_callback)
            await asyncio.sleep(3600)

    Usage blocking (for CLI / scripts)::

        s = client.stream(topics)
        s.on_space_update(my_callback)
        await s.run_forever()

    Args:
        channel: The gRPC channel to use.
        topics: List of topic strings to subscribe to initially.
        metadata_provider: Optional callable that returns gRPC metadata headers.
        authenticate: Optional async callable (no args) that refreshes the auth
            token. When provided and the stream gets ``UNAUTHENTICATED``, the
            callable is awaited before reconnecting.
        max_reconnects: Maximum reconnect attempts per disconnect event.
            ``-1`` means unlimited (default).
        reconnect_delay_s: Initial back-off delay in seconds before the first
            reconnect. Doubles on each subsequent attempt, capped at 60 s.
            Default: ``1.0``.
        debounce_s: Quiet period in seconds for coalescing updates by entity
            type and ID before dispatching the latest event. Default: ``0.0``
            (dispatch immediately).
    """

    _channel: grpc.aio.Channel
    _topics: list[str]
    _metadata_provider: Callable[[], Sequence[tuple[str, str]]] | None = None
    _authenticate: RefreshCallback | None = None
    _max_reconnects: int = -1
    _reconnect_delay_s: float = 1.0
    _debounce_s: float = 0.0

    _space_callbacks: list[SpaceCallback] = field(default_factory=list, init=False)
    _idu_callbacks: list[IndoorUnitCallback] = field(default_factory=list, init=False)
    _odu_callbacks: list[OutdoorUnitCallback] = field(default_factory=list, init=False)
    _ctrl_callbacks: list[ControllerCallback] = field(default_factory=list, init=False)
    _qsm_callbacks: list[QsmCallback] = field(default_factory=list, init=False)
    _rs_callbacks: list[RemoteSensorCallback] = field(default_factory=list, init=False)
    _crs_callbacks: list[ControllerRemoteSensorCallback] = field(default_factory=list, init=False)
    _sui_callbacks: list[SoftwareUpdateInfoCallback] = field(default_factory=list, init=False)
    _error_callbacks: list[ErrorCallback] = field(default_factory=list, init=False)
    _request_queue: asyncio.Queue[notifier.SubscribeRequest] = field(init=False)
    _subscription_lock: asyncio.Lock = field(init=False)
    _lifecycle_lock: asyncio.Lock = field(init=False)
    _pending_dispatch_lock: asyncio.Lock = field(init=False)
    _stop_event: asyncio.Event = field(init=False)
    _running: bool = field(default=False, init=False)
    _task: asyncio.Task[None] | None = field(default=None, init=False)
    _active_call: Any | None = field(default=None, init=False)
    _pending_dispatches: dict[_EventKey, _PendingDispatch] = field(
        default_factory=dict, init=False
    )
    _error: Exception | None = field(default=None, init=False)
    _last_event_at: float | None = field(default=None, init=False)
    _stream_state: str = field(default="idle", init=False)

    def __post_init__(self) -> None:
        factory = cast(
            "Callable[[grpc.aio.Channel], _NotifierServiceStub]",
            notifier_grpc.NotifierServiceStub,
        )
        self._stub: _NotifierServiceStub = factory(self._channel)
        self._request_queue = asyncio.Queue()
        self._subscription_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._pending_dispatch_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()

    # --- Public constructor (friendlier than dataclass __init__) ---

    @classmethod
    def create(
        cls,
        channel: grpc.aio.Channel,
        topics: list[str],
        *,
        metadata_provider: Callable[[], Sequence[tuple[str, str]]] | None = None,
        authenticate: RefreshCallback | None = None,
        max_reconnects: int = -1,
        reconnect_delay_s: float = 1.0,
        debounce_s: float = 0.0,
    ) -> NotifierStream:
        """Create a NotifierStream with named parameters."""
        return cls(
            _channel=channel,
            _topics=list(topics),
            _metadata_provider=metadata_provider,
            _authenticate=authenticate,
            _max_reconnects=max_reconnects,
            _reconnect_delay_s=reconnect_delay_s,
            _debounce_s=debounce_s,
        )

    # --- Callback registration ---

    def on_space_update(self, callback: SpaceCallback) -> None:
        """Register a callback for space change events (sync or async)."""
        self._space_callbacks.append(callback)

    def on_indoor_unit_update(self, callback: IndoorUnitCallback) -> None:
        """Register a callback for indoor unit change events (sync or async)."""
        self._idu_callbacks.append(callback)

    def on_outdoor_unit_update(self, callback: OutdoorUnitCallback) -> None:
        """Register callback for outdoor unit change events."""
        self._odu_callbacks.append(callback)

    def on_controller_update(self, callback: ControllerCallback) -> None:
        """Register callback for controller (Dial) change events."""
        self._ctrl_callbacks.append(callback)

    def on_qsm_update(self, callback: QsmCallback) -> None:
        """Register callback for QuiltSmartModule change events."""
        self._qsm_callbacks.append(callback)

    def on_remote_sensor_update(self, callback: RemoteSensorCallback) -> None:
        """Register callback for RemoteSensor change events."""
        self._rs_callbacks.append(callback)

    def on_controller_remote_sensor_update(self, callback: ControllerRemoteSensorCallback) -> None:
        """Register callback for ControllerRemoteSensor change events."""
        self._crs_callbacks.append(callback)

    def on_software_update_info(self, callback: SoftwareUpdateInfoCallback) -> None:
        """Register callback for SoftwareUpdateInfo change events."""
        self._sui_callbacks.append(callback)

    def on_error(self, callback: ErrorCallback) -> None:
        """Register a callback invoked when the stream encounters a fatal error."""
        self._error_callbacks.append(callback)

    @property
    def error(self) -> Exception | None:
        """The last fatal stream error, or None if the stream is healthy."""
        return self._error

    @property
    def is_connected(self) -> bool:
        """Whether the stream currently has an active connection."""
        return self._stream_state == "connected"

    @property
    def last_event_at(self) -> float | None:
        """Monotonic timestamp of the last received non-heartbeat event."""
        return self._last_event_at

    @property
    def stream_state(self) -> str:
        """Current stream lifecycle state."""
        return self._stream_state

    # --- Subscription management ---

    async def subscribe(self, topics: list[str]) -> None:
        """Add more topics to the subscription (after stream is started)."""
        async with self._subscription_lock:
            self._topics.extend(topics)
            await self._request_queue.put(_make_subscribe_request(topics))

    async def unsubscribe(self, topics: list[str]) -> None:
        """Remove topics from the subscription."""
        req = notifier.SubscribeRequest(
            remove=notifier.TopicsMessage(
                subscriptions=[notifier.Subscription(topic=t) for t in topics]
            )
        )
        async with self._subscription_lock:
            for t in topics:
                if t in self._topics:
                    self._topics.remove(t)
            await self._request_queue.put(req)

    # --- Internal stream machinery ---

    async def _request_iterator(
        self,
        topics: list[str],
        request_queue: asyncio.Queue[notifier.SubscribeRequest],
    ) -> AsyncIterator[notifier.SubscribeRequest]:
        """Yield SubscribeRequests from initial subscription, then queue.

        A 30-second timeout on the queue read keeps the async generator alive
        without re-sending the topic list; gRPC channel keepalives (configured
        in GRPC_CHANNEL_OPTIONS) handle the underlying TCP connection.
        """
        yield _make_subscribe_request(topics)
        while self._running:
            try:
                req = await asyncio.wait_for(request_queue.get(), timeout=30.0)
                yield req
            except TimeoutError:
                continue  # keepalive handled by gRPC channel options

    def _parse_event(self, evt: object) -> StreamEvent | None:
        """Parse the complex nested wire format of a NotifierEvent."""
        topic_bytes: bytes = getattr(cast("Any", evt), "topic", b"")
        if not topic_bytes:
            return None  # heartbeat

        type_url_bytes = _get_len_field(topic_bytes, 1) or b""
        notif_bytes = _get_len_field(topic_bytes, 2)

        try:
            topic_str = type_url_bytes.decode("utf-8")
        except Exception:
            topic_str = type_url_bytes.hex()

        event = StreamEvent(topic=topic_str)

        if not notif_bytes:
            return event

        inner_notif = _get_len_field(notif_bytes, 2)
        if not inner_notif:
            event.raw_bytes = notif_bytes
            return event

        obj_diff = _get_len_field(inner_notif, 2)
        if obj_diff:
            space_bytes = _get_len_field(obj_diff, 3)
            if space_bytes:
                updated = hds.Space()
                updated.ParseFromString(space_bytes)
                event.space = Space.from_proto(updated)

            idu_bytes = _get_len_field(obj_diff, 9)
            if idu_bytes:
                updated_idu = hds.IndoorUnit()
                updated_idu.ParseFromString(idu_bytes)
                event.indoor_unit = IndoorUnit.from_proto(updated_idu)

            odu_bytes = _get_len_field(obj_diff, 6)
            if odu_bytes:
                updated_odu = hds.OutdoorUnit()
                updated_odu.ParseFromString(odu_bytes)
                event.outdoor_unit = OutdoorUnit.from_proto(updated_odu)

            ctrl_bytes = _get_len_field(obj_diff, 11)
            if ctrl_bytes:
                updated_ctrl = hds.Controller()
                updated_ctrl.ParseFromString(ctrl_bytes)
                event.controller = Controller.from_proto(updated_ctrl)

            qsm_bytes = _get_len_field(obj_diff, 7)
            if qsm_bytes:
                updated_qsm = hds.QuiltSmartModule()
                updated_qsm.ParseFromString(qsm_bytes)
                event.qsm = QuiltSmartModule.from_proto(updated_qsm)

            rs_bytes = _get_len_field(obj_diff, 12)
            if rs_bytes:
                updated_rs = hds.RemoteSensor()
                updated_rs.ParseFromString(rs_bytes)
                event.remote_sensor = RemoteSensor.from_proto(updated_rs)

            crs_bytes = _get_len_field(obj_diff, 16)
            if crs_bytes:
                updated_crs = hds.ControllerRemoteSensor()
                updated_crs.ParseFromString(crs_bytes)
                event.controller_remote_sensor = ControllerRemoteSensor.from_proto(updated_crs)

            sui_bytes = _get_len_field(obj_diff, 18)
            if sui_bytes:
                updated_sui = hds.SoftwareUpdateInfo()
                updated_sui.ParseFromString(sui_bytes)
                event.software_update_info = SoftwareUpdateInfo.from_proto(updated_sui)

        if (
            event.space is None
            and event.indoor_unit is None
            and event.outdoor_unit is None
            and event.controller is None
            and event.qsm is None
            and event.remote_sensor is None
            and event.controller_remote_sensor is None
            and event.software_update_info is None
        ):
            event.raw_bytes = inner_notif

        return event

    async def _invoke_callbacks[T](
        self,
        callbacks: Sequence[Callable[[T], Awaitable[None] | None]],
        arg: T,
        error_message: str,
    ) -> None:
        for callback in callbacks:
            try:
                await _dispatch(callback, arg)
            except Exception:
                logger.exception(error_message)

    async def _dispatch_debounced(self, key: _EventKey) -> None:
        try:
            await asyncio.sleep(self._debounce_s)
            async with self._pending_dispatch_lock:
                pending = self._pending_dispatches.get(key)
                if pending is None or pending.task is not asyncio.current_task():
                    return
                self._pending_dispatches.pop(key, None)
            await self._invoke_callbacks(pending.callbacks, pending.value, pending.error_message)
        except asyncio.CancelledError:
            raise

    async def _queue_debounced_dispatch[T](
        self,
        entity_type: str,
        entity: T,
        callbacks: Sequence[Callable[[T], Awaitable[None] | None]],
        error_message: str,
    ) -> None:
        key = (entity_type, str(getattr(cast("Any", entity), "id", "")))
        callback_snapshot = tuple(cast("Sequence[_AnyCallback]", callbacks))
        async with self._pending_dispatch_lock:
            existing = self._pending_dispatches.get(key)
            if existing is not None:
                existing.task.cancel()
            task = asyncio.create_task(self._dispatch_debounced(key))
            self._pending_dispatches[key] = _PendingDispatch(
                value=entity,
                callbacks=callback_snapshot,
                error_message=error_message,
                task=task,
            )

    async def _cancel_pending_dispatches(self) -> None:
        async with self._pending_dispatch_lock:
            pending = list(self._pending_dispatches.values())
            self._pending_dispatches.clear()
        for item in pending:
            item.task.cancel()
        if pending:
            await asyncio.gather(*(item.task for item in pending), return_exceptions=True)

    async def _dispatch_entity[T](
        self,
        entity_type: str,
        entity: T,
        callbacks: Sequence[Callable[[T], Awaitable[None] | None]],
        error_message: str,
    ) -> None:
        if self._debounce_s <= 0:
            await self._invoke_callbacks(callbacks, entity, error_message)
            return
        await self._queue_debounced_dispatch(entity_type, entity, callbacks, error_message)

    async def _dispatch_parsed_event(self, parsed: StreamEvent) -> None:
        if parsed.space is not None:
            await self._dispatch_entity(
                "space", parsed.space, self._space_callbacks, "Error in space callback"
            )
        if parsed.indoor_unit is not None:
            await self._dispatch_entity(
                "indoor_unit",
                parsed.indoor_unit,
                self._idu_callbacks,
                "Error in indoor unit callback",
            )
        if parsed.outdoor_unit is not None:
            await self._dispatch_entity(
                "outdoor_unit",
                parsed.outdoor_unit,
                self._odu_callbacks,
                "Error in outdoor unit callback",
            )
        if parsed.controller is not None:
            await self._dispatch_entity(
                "controller",
                parsed.controller,
                self._ctrl_callbacks,
                "Error in controller callback",
            )
        if parsed.qsm is not None:
            await self._dispatch_entity(
                "qsm", parsed.qsm, self._qsm_callbacks, "Error in QSM callback"
            )
        if parsed.remote_sensor is not None:
            await self._dispatch_entity(
                "remote_sensor",
                parsed.remote_sensor,
                self._rs_callbacks,
                "Error in remote sensor callback",
            )
        if parsed.controller_remote_sensor is not None:
            await self._dispatch_entity(
                "controller_remote_sensor",
                parsed.controller_remote_sensor,
                self._crs_callbacks,
                "Error in controller remote sensor callback",
            )
        if parsed.software_update_info is not None:
            await self._dispatch_entity(
                "software_update_info",
                parsed.software_update_info,
                self._sui_callbacks,
                "Error in software update info callback",
            )

    async def _run_one_stream(self) -> None:
        """Run a single stream connection until it ends or errors."""
        metadata = self._metadata_provider() if self._metadata_provider else None
        async with self._subscription_lock:
            # Snapshot topics and queue together so reconnect queue swaps and
            # subscribe/unsubscribe calls cannot interleave between them.
            topics = list(self._topics)
            request_queue = self._request_queue
            call = self._stub.Subscribe(
                self._request_iterator(topics, request_queue),
                metadata=metadata,
            )
            self._active_call = call
        self._stream_state = "connected"
        try:
            async for response in call:
                saw_event = False
                for ctrl in response.control_events:
                    saw_event = True
                    event_name = notifier.ControlEventType.Name(ctrl.type)
                    logger.debug("Control event: %s topics=%s", event_name, list(ctrl.topics))

                for evt in response.notifier_events:
                    parsed = self._parse_event(evt)
                    if parsed is None:
                        continue
                    saw_event = True
                    await self._dispatch_parsed_event(parsed)
                if saw_event:
                    self._last_event_at = time.monotonic()
        finally:
            if self._active_call is call:
                self._active_call = None

    async def _run_stream_with_reconnect(self) -> None:
        """Run the stream with automatic reconnect and exponential back-off."""
        attempt = 0
        delay = self._reconnect_delay_s

        while self._running:
            try:
                self._error = None
                await self._run_one_stream()
                # Clean exit (stream ended without error) — stop.
                break
            except grpc.aio.AioRpcError as exc:
                if not self._running:
                    break
                is_unauth = exc.code() == grpc.StatusCode.UNAUTHENTICATED
                can_retry = self._max_reconnects < 0 or attempt < self._max_reconnects

                if is_unauth and self._authenticate is not None and can_retry:
                    self._stream_state = "reconnecting"
                    # Token expiry is handled automatically — INFO to confirm it
                    # happened without alarming the user.
                    logger.info(
                        "Stream got UNAUTHENTICATED; refreshing token (attempt %d)",
                        attempt + 1,
                    )
                    try:
                        context = TokenRefreshContext(
                            reason=TokenRefreshReason.STREAM_UNAUTHENTICATED,
                            source="streaming",
                            attempt=attempt + 1,
                        )
                        await invoke_refresh_callback(self._authenticate, context)
                    except Exception:
                        logger.exception("Token refresh failed; giving up stream")
                        self._error = exc
                        self._stream_state = "error"
                        break
                elif can_retry:
                    self._stream_state = "reconnecting"
                    details = exc.details() or ""
                    # Classify the error to pick the right log level:
                    #   DEBUG  — HTTP/2 NO_ERROR RST_STREAM: server gracefully
                    #            recycled the connection (load balancer, keepalive).
                    #   INFO   — CANCELLED: server closed the stream normally
                    #            (keepalive timeout, server rotation, etc.).
                    #   WARNING — anything else is unexpected.
                    is_graceful_reset = "RST_STREAM with error code 0" in details
                    is_server_cancel = exc.code() == grpc.StatusCode.CANCELLED
                    if is_graceful_reset:
                        log = logger.debug
                    elif is_server_cancel:
                        log = logger.info
                    else:
                        log = logger.warning
                    log(
                        "Stream error %s: %s; reconnecting in %.1fs (attempt %d)",
                        exc.code(),
                        details,
                        delay,
                        attempt + 1,
                    )
                else:
                    logger.error(
                        "Stream error %s: %s; max reconnects reached",
                        exc.code(),
                        exc.details(),
                    )
                    self._error = QuiltStreamError(f"Stream error: {exc.code()} - {exc.details()}")
                    self._stream_state = "error"
                    break

                if await self._wait_for_stop(delay):
                    break
                delay = min(delay * 2, 60.0)
                attempt += 1
                async with self._subscription_lock:
                    logger.info(
                        "Resetting subscription queue before reconnect; "
                        "tracked topics will be re-subscribed on the next stream"
                    )
                    # _topics is the source of truth. The next request iterator
                    # snapshots the current topics and sends them as its first
                    # request, so discarding any stale queued requests is safe.
                    self._request_queue = asyncio.Queue()

        if self._error is None and self._stream_state != "stopped":
            self._stream_state = "stopped"

        if self._error is not None:
            for cb in self._error_callbacks:
                try:
                    await _dispatch(cb, self._error)
                except Exception:
                    logger.exception("Error in error callback")
            if not self._error_callbacks:
                # Propagate to the task so the caller can observe it
                raise self._error

    async def _wait_for_stop(self, delay: float) -> bool:
        sleep_task = asyncio.create_task(asyncio.sleep(delay))
        stop_task = asyncio.create_task(self._stop_event.wait())
        done, pending = await asyncio.wait(
            {sleep_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        return stop_task in done

    async def _run_until_stopped(self) -> None:
        try:
            await self._run_stream_with_reconnect()
        finally:
            await self._cancel_pending_dispatches()
            async with self._lifecycle_lock:
                self._running = False
                self._active_call = None
                if self._task is asyncio.current_task():
                    self._task = None
                if self._error is None and self._stream_state != "error":
                    self._stream_state = "stopped"

    # --- Lifecycle ---

    async def run_forever(self) -> None:
        """Run the stream inline (blocking) until cancelled or fatal error."""
        async with self._lifecycle_lock:
            if self._running:
                return
            self._running = True
            self._error = None
            self._stream_state = "idle"
            self._stop_event.clear()
        await self._run_until_stopped()

    async def start(self) -> None:
        """Start the stream listener as a background task."""
        async with self._lifecycle_lock:
            if self._running:
                return
            self._running = True
            self._error = None
            self._stream_state = "idle"
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run_until_stopped())
            self._task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        """Log unhandled task exceptions so they aren't silently swallowed."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("NotifierStream task exited with error: %s", exc)

    async def stop(self) -> None:
        """Stop the stream listener."""
        async with self._lifecycle_lock:
            self._running = False
            self._stream_state = "stopped"
            self._stop_event.set()
            task = self._task
            self._task = None
            active_call = self._active_call

        cancel = getattr(active_call, "cancel", None)
        if callable(cancel):
            cancel()

        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, QuiltStreamError):
                await task

        await self._cancel_pending_dispatches()

    async def __aenter__(self) -> NotifierStream:
        await self.start()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.stop()
