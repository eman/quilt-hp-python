"""NotifierService streaming - real-time HDS change subscriptions.

Wire format:
  SubscribeResponse.event -> SubscribeEvent{notifier_events, control_events, system_events}
  NotifierEvent{topic, payload: Any} -> Any.value = Notification -> HomeDatastoreObjectDiff
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
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
from quilt_hp.models.enums import NotificationType
from quilt_hp.models.indoor_unit import IndoorUnit
from quilt_hp.models.outdoor_unit import OutdoorUnit
from quilt_hp.models.qsm import QuiltSmartModule
from quilt_hp.models.sensor import ControllerRemoteSensor, RemoteSensor
from quilt_hp.models.software_update import SoftwareUpdateInfo
from quilt_hp.models.space import Space
from quilt_hp.tokens import TokenRefreshContext, TokenRefreshReason, invoke_refresh_callback

logger = logging.getLogger(__name__)

# A connection that stays up at least this long is considered healthy: the
# reconnect budget and exponential back-off reset when it ends, so routine
# server-side stream recycling never escalates reconnect latency permanently.
_HEALTHY_CONNECTION_S = 30.0

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
# Called with (entity kind, entity id) when the server reports an object deleted. Kinds match
# StreamEvent attribute names: "space", "indoor_unit", "outdoor_unit", "controller", "qsm",
# "remote_sensor", "controller_remote_sensor", "software_update_info".
DeleteCallback = Callable[[str, str], Awaitable[None] | None]
ConnectedCallback = Callable[[], Awaitable[None] | None]

# Returned by the on_* registration methods; call it to unregister.
Unsubscribe = Callable[[], None]


class _NotifierServiceStub(Protocol):
    def Subscribe(
        self,
        request_iterator: AsyncIterator[notifier.SubscribeRequest],
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[notifier.SubscribeResponse]: ...


RefreshCallback = Callable[[], Awaitable[None]] | Callable[[TokenRefreshContext], Awaitable[None]]

type _EventKey = tuple[str, str]
type _AnyCallback = Callable[[Any], Awaitable[None] | None]


# HomeDatastoreObjectDiff oneof member -> (StreamEvent attribute, model class).
_DIFF_MODELS: dict[str, tuple[str, Any]] = {
    "space": ("space", Space),
    "indoor_unit": ("indoor_unit", IndoorUnit),
    "outdoor_unit": ("outdoor_unit", OutdoorUnit),
    "controller": ("controller", Controller),
    "quilt_smart_module": ("qsm", QuiltSmartModule),
    "remote_sensor": ("remote_sensor", RemoteSensor),
    "controller_remote_sensor": ("controller_remote_sensor", ControllerRemoteSensor),
    "software_update_info": ("software_update_info", SoftwareUpdateInfo),
}


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
    notification_type: NotificationType = NotificationType.UPDATED
    system_version: int | None = None
    """``Notification.system_version``. The server sends 0 for every event observed (2026-10),
    so this is None in practice; use ``QuiltClient.get_system_version()`` instead."""


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
        max_reconnects: Maximum consecutive reconnect attempts.  The counter
            resets after a connection stays healthy for a while, so this
            bounds retries per disconnect event rather than per stream
            lifetime.  ``-1`` means unlimited (default).
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
    _delete_callbacks: list[DeleteCallback] = field(default_factory=list, init=False)
    _connected_callbacks: list[ConnectedCallback] = field(default_factory=list, init=False)
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
    #
    # Each on_* method returns an unsubscribe callable so long-lived
    # consumers (e.g. HA config entries) can detach callbacks without
    # tearing down the stream.
    #
    # Callbacks run on the event loop: keep them non-blocking.  A slow or
    # blocking callback delays delivery of subsequent stream events.

    @staticmethod
    def _register[T](callbacks: list[T], callback: T) -> Unsubscribe:
        callbacks.append(callback)

        def _unsubscribe() -> None:
            with contextlib.suppress(ValueError):
                callbacks.remove(callback)

        return _unsubscribe

    def on_space_update(self, callback: SpaceCallback) -> Unsubscribe:
        """Register a callback for space change events (sync or async)."""
        return self._register(self._space_callbacks, callback)

    def on_indoor_unit_update(self, callback: IndoorUnitCallback) -> Unsubscribe:
        """Register a callback for indoor unit change events (sync or async)."""
        return self._register(self._idu_callbacks, callback)

    def on_outdoor_unit_update(self, callback: OutdoorUnitCallback) -> Unsubscribe:
        """Register callback for outdoor unit change events."""
        return self._register(self._odu_callbacks, callback)

    def on_controller_update(self, callback: ControllerCallback) -> Unsubscribe:
        """Register callback for controller (Dial) change events."""
        return self._register(self._ctrl_callbacks, callback)

    def on_qsm_update(self, callback: QsmCallback) -> Unsubscribe:
        """Register callback for QuiltSmartModule change events."""
        return self._register(self._qsm_callbacks, callback)

    def on_remote_sensor_update(self, callback: RemoteSensorCallback) -> Unsubscribe:
        """Register callback for RemoteSensor change events."""
        return self._register(self._rs_callbacks, callback)

    def on_controller_remote_sensor_update(
        self, callback: ControllerRemoteSensorCallback
    ) -> Unsubscribe:
        """Register callback for ControllerRemoteSensor change events."""
        return self._register(self._crs_callbacks, callback)

    def on_software_update_info(self, callback: SoftwareUpdateInfoCallback) -> Unsubscribe:
        """Register callback for SoftwareUpdateInfo change events."""
        return self._register(self._sui_callbacks, callback)

    def on_delete(self, callback: DeleteCallback) -> Unsubscribe:
        """Register a callback for deleted objects, called with ``(kind, entity_id)``.

        Deletions are never delivered to the ``on_*_update`` callbacks (which would
        otherwise re-add the object to a snapshot); pair this with
        ``SystemSnapshot.remove(kind, entity_id)``.
        """
        return self._register(self._delete_callbacks, callback)

    def on_error(self, callback: ErrorCallback) -> Unsubscribe:
        """Register a callback invoked when the stream encounters a fatal error."""
        return self._register(self._error_callbacks, callback)

    def on_connected(self, callback: ConnectedCallback) -> Unsubscribe:
        """Register a callback invoked on every successful (re)connect.

        Events published while the stream was disconnected are lost; use this
        to re-fetch a snapshot after a reconnect and close the gap.
        """
        return self._register(self._connected_callbacks, callback)

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
        """Add more topics to the subscription (before or after start)."""
        async with self._subscription_lock:
            self._topics.extend(topics)
            # Before start, _topics alone is the source of truth: the initial
            # request snapshots it.  Queueing here as well would send the
            # topics twice on the first stream.
            if self._running:
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
            if self._running:
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

    def _parse_event(self, evt: notifier.NotifierEvent) -> StreamEvent | None:
        """Decode one NotifierEvent: a topic plus an Any-wrapped Notification."""
        if not evt.topic:
            return None
        event = StreamEvent(topic=evt.topic)
        payload = evt.payload.value
        if not payload:
            return event
        note = hds.Notification.FromString(payload)
        try:
            event.notification_type = NotificationType(note.notification_type)
        except ValueError:
            event.notification_type = NotificationType.UNSPECIFIED
        event.system_version = note.system_version or None
        diff = note.payload
        which = diff.WhichOneof("data")
        if which is None or which not in _DIFF_MODELS:
            # An entity type the models don't cover (e.g. automation, ducted_zone).
            event.raw_bytes = payload
            return event
        attr, model = _DIFF_MODELS[which]
        setattr(event, attr, model.from_proto(getattr(diff, which)))
        return event

    async def _dispatch_delete(self, parsed: StreamEvent) -> None:
        for kind in _DIFF_MODELS.values():
            entity = getattr(parsed, kind[0])
            if entity is None:
                continue
            entity_id = str(getattr(entity, "id", ""))
            # A debounced update still pending for this object must not land after the delete.
            async with self._pending_dispatch_lock:
                pending = self._pending_dispatches.pop((kind[0], entity_id), None)
            if pending is not None:
                pending.task.cancel()
            for callback in list(self._delete_callbacks):
                try:
                    result = callback(kind[0], entity_id)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    logger.exception("Error in delete callback")

    async def _invoke_callbacks[T](
        self,
        callbacks: Sequence[Callable[[T], Awaitable[None] | None]],
        arg: T,
        error_message: str,
    ) -> None:
        # Iterate a snapshot: a callback may unsubscribe itself (or others)
        # while being dispatched.
        for callback in list(callbacks):
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
        if parsed.notification_type == NotificationType.DELETED:
            await self._dispatch_delete(parsed)
            return
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
        # Iterate a snapshot: a callback may unsubscribe itself (or others)
        # while being dispatched.
        for connected_cb in list(self._connected_callbacks):
            try:
                result = connected_cb()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Error in connected callback")
        try:
            async for response in call:
                saw_event = False
                batch = response.event
                for ctrl in batch.control_events:
                    saw_event = True
                    if logger.isEnabledFor(logging.DEBUG):
                        event_name = notifier.ControlEventType.Name(ctrl.type)
                        logger.debug("Control event: %s topics=%s", event_name, list(ctrl.topics))

                for evt in batch.notifier_events:
                    try:
                        parsed = self._parse_event(evt)
                    except Exception:
                        # One malformed event must not kill the stream.
                        logger.exception("Failed to parse stream event; skipping")
                        continue
                    if parsed is None:
                        continue
                    saw_event = True
                    await self._dispatch_parsed_event(parsed)
                if saw_event:
                    self._last_event_at = time.monotonic()
        finally:
            if self._active_call is call:
                self._active_call = None

    async def _prepare_reconnect(self, delay: float) -> bool:
        """Back off, then reset the request queue.  Returns True when stopped."""
        # Jitter avoids a synchronized reconnect stampede across clients
        # after a server-side restart.
        if await self._wait_for_stop(delay * random.uniform(0.5, 1.5)):
            return True
        async with self._subscription_lock:
            logger.info(
                "Resetting subscription queue before reconnect; "
                "tracked topics will be re-subscribed on the next stream"
            )
            # _topics is the source of truth. The next request iterator
            # snapshots the current topics and sends them as its first
            # request, so discarding any stale queued requests is safe.
            self._request_queue = asyncio.Queue()
        return False

    async def _run_stream_with_reconnect(self) -> None:
        """Run the stream with automatic reconnect and exponential back-off."""
        attempt = 0
        delay = self._reconnect_delay_s

        while self._running:
            connected_at = time.monotonic()
            try:
                self._error = None
                await self._run_one_stream()
                # Clean exit (stream ended without error) — stop.
                break
            except grpc.aio.AioRpcError as exc:
                if not self._running:
                    break
                # A connection that stayed healthy for a while resets the
                # reconnect budget and back-off: max_reconnects bounds
                # *consecutive* failures, and routine server-side stream
                # recycling must not permanently escalate the delay.
                if time.monotonic() - connected_at >= _HEALTHY_CONNECTION_S:
                    attempt = 0
                    delay = self._reconnect_delay_s
                is_unauth = exc.code() == grpc.StatusCode.UNAUTHENTICATED
                can_retry = self._max_reconnects < 0 or attempt < self._max_reconnects
                wait_s = delay

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
                    # Refresh succeeded — reconnect promptly instead of
                    # serving the escalated back-off for routine token expiry.
                    wait_s = 0.0
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

                if await self._prepare_reconnect(wait_s):
                    break
                delay = min(delay * 2, 60.0)
                attempt += 1
            except Exception as exc:
                # Non-gRPC failures (metadata provider errors, channel usage
                # errors, unexpected parse crashes) must not silently kill the
                # stream: reconnect if budget remains, otherwise surface via
                # on_error like any other fatal condition.
                if not self._running:
                    break
                if time.monotonic() - connected_at >= _HEALTHY_CONNECTION_S:
                    attempt = 0
                    delay = self._reconnect_delay_s
                if self._max_reconnects >= 0 and attempt >= self._max_reconnects:
                    logger.exception("Unexpected stream error; max reconnects reached")
                    self._error = QuiltStreamError(f"Stream error: {exc}")
                    self._stream_state = "error"
                    break
                self._stream_state = "reconnecting"
                logger.exception(
                    "Unexpected stream error; reconnecting in %.1fs (attempt %d)",
                    delay,
                    attempt + 1,
                )
                if await self._prepare_reconnect(delay):
                    break
                delay = min(delay * 2, 60.0)
                attempt += 1

        if self._error is None and self._stream_state != "stopped":
            self._stream_state = "stopped"

        if self._error is not None:
            for cb in list(self._error_callbacks):
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
            try:
                await task
            except asyncio.CancelledError, QuiltStreamError:
                pass
            except Exception:
                # The task may have already died with an unrelated error;
                # log it rather than masking the caller's own exception
                # (stop() often runs from __aexit__).
                logger.exception("NotifierStream task raised during stop")

        await self._cancel_pending_dispatches()

    async def __aenter__(self) -> NotifierStream:
        await self.start()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.stop()
