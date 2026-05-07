"""NotifierService streaming - real-time HDS change subscriptions.

Handles the complex nested wire format:
  NotifierEvent.topic (bytes) -> C1517Ta{type_url, value} ->
    google.protobuf.Any -> HdsNotification -> HomeDatastoreObjectDiff
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field

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


async def _dispatch(cb: SpaceCallback | IndoorUnitCallback | ErrorCallback, arg: object) -> None:
    """Call a callback, awaiting it if it returns a coroutine."""
    result = cb(arg)  # type: ignore[call-arg]
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
        max_reconnects: Maximum automatic reconnect attempts per disconnect event.
            ``-1`` means unlimited. Default: ``-1``.
        reconnect_delay_s: Initial back-off delay in seconds before the first
            reconnect. Doubles on each subsequent attempt, capped at 60 s.
            Default: ``1.0``.
    """

    _channel: grpc.aio.Channel
    _topics: list[str]
    _metadata_provider: Callable[[], Sequence[tuple[str, str]]] | None = None
    _authenticate: Callable[[], Awaitable[None]] | None = None
    _max_reconnects: int = -1
    _reconnect_delay_s: float = 1.0

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
    _running: bool = field(default=False, init=False)
    _task: asyncio.Task[None] | None = field(default=None, init=False)
    _error: Exception | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._stub = notifier_grpc.NotifierServiceStub(self._channel)
        self._request_queue = asyncio.Queue()

    # --- Public constructor (friendlier than dataclass __init__) ---

    @classmethod
    def create(
        cls,
        channel: grpc.aio.Channel,
        topics: list[str],
        *,
        metadata_provider: Callable[[], Sequence[tuple[str, str]]] | None = None,
        authenticate: Callable[[], Awaitable[None]] | None = None,
        max_reconnects: int = -1,
        reconnect_delay_s: float = 1.0,
    ) -> NotifierStream:
        """Create a NotifierStream with named parameters."""
        return cls(
            _channel=channel,
            _topics=list(topics),
            _metadata_provider=metadata_provider,
            _authenticate=authenticate,
            _max_reconnects=max_reconnects,
            _reconnect_delay_s=reconnect_delay_s,
        )

    # --- Callback registration ---

    def on_space_update(self, callback: SpaceCallback) -> None:
        """Register a callback for space change events (sync or async)."""
        self._space_callbacks.append(callback)

    def on_indoor_unit_update(self, callback: IndoorUnitCallback) -> None:
        """Register a callback for indoor unit change events (sync or async)."""
        self._idu_callbacks.append(callback)

    def on_outdoor_unit_update(self, callback: OutdoorUnitCallback) -> None:
        """Register a callback for outdoor unit change events (sync or async)."""
        self._odu_callbacks.append(callback)

    def on_controller_update(self, callback: ControllerCallback) -> None:
        """Register a callback for controller (Dial) change events (sync or async)."""
        self._ctrl_callbacks.append(callback)

    def on_qsm_update(self, callback: QsmCallback) -> None:
        """Register a callback for QuiltSmartModule change events (sync or async)."""
        self._qsm_callbacks.append(callback)

    def on_remote_sensor_update(self, callback: RemoteSensorCallback) -> None:
        """Register a callback for RemoteSensor change events (sync or async)."""
        self._rs_callbacks.append(callback)

    def on_controller_remote_sensor_update(self, callback: ControllerRemoteSensorCallback) -> None:
        """Register a callback for ControllerRemoteSensor change events (sync or async)."""
        self._crs_callbacks.append(callback)

    def on_software_update_info(self, callback: SoftwareUpdateInfoCallback) -> None:
        """Register a callback for SoftwareUpdateInfo change events (sync or async)."""
        self._sui_callbacks.append(callback)

    def on_error(self, callback: ErrorCallback) -> None:
        """Register a callback invoked when the stream encounters a fatal error."""
        self._error_callbacks.append(callback)

    @property
    def error(self) -> Exception | None:
        """The last fatal stream error, or None if the stream is healthy."""
        return self._error

    # --- Subscription management ---

    async def subscribe(self, topics: list[str]) -> None:
        """Add more topics to the subscription (after stream is started)."""
        self._topics.extend(topics)
        await self._request_queue.put(_make_subscribe_request(topics))

    async def unsubscribe(self, topics: list[str]) -> None:
        """Remove topics from the subscription."""
        for t in topics:
            if t in self._topics:
                self._topics.remove(t)
        req = notifier.SubscribeRequest(
            remove=notifier.TopicsMessage(
                subscriptions=[notifier.Subscription(topic=t) for t in topics]
            )
        )
        await self._request_queue.put(req)

    # --- Internal stream machinery ---

    async def _request_iterator(self) -> AsyncIterator[notifier.SubscribeRequest]:
        """Yields SubscribeRequests — initial subscription first, then from queue.

        A 30-second timeout on the queue read keeps the async generator alive
        without re-sending the topic list; gRPC channel keepalives (configured
        in GRPC_CHANNEL_OPTIONS) handle the underlying TCP connection.
        """
        yield _make_subscribe_request(self._topics)
        while self._running:
            try:
                req = await asyncio.wait_for(self._request_queue.get(), timeout=30.0)
                yield req
            except TimeoutError:
                continue  # keepalive handled by gRPC channel options

    def _parse_event(self, evt: object) -> StreamEvent | None:
        """Parse the complex nested wire format of a NotifierEvent."""
        topic_bytes: bytes = evt.topic  # type: ignore[attr-defined]
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

        if (event.space is None and event.indoor_unit is None and event.outdoor_unit is None
                and event.controller is None and event.qsm is None
                and event.remote_sensor is None and event.controller_remote_sensor is None
                and event.software_update_info is None):
            event.raw_bytes = inner_notif

        return event

    async def _run_one_stream(self) -> None:
        """Run a single stream connection until it ends or errors."""
        metadata = self._metadata_provider() if self._metadata_provider else None
        call = self._stub.Subscribe(
            self._request_iterator(),
            metadata=metadata,
        )
        async for response in call:
            for ctrl in response.control_events:
                event_name = notifier.ControlEventType.Name(ctrl.type)
                logger.debug("Control event: %s topics=%s", event_name, list(ctrl.topics))

            for evt in response.notifier_events:
                parsed = self._parse_event(evt)
                if parsed is None:
                    continue
                if parsed.space is not None:
                    for cb in self._space_callbacks:
                        try:
                            await _dispatch(cb, parsed.space)
                        except Exception:
                            logger.exception("Error in space callback")
                if parsed.indoor_unit is not None:
                    for cb in self._idu_callbacks:
                        try:
                            await _dispatch(cb, parsed.indoor_unit)
                        except Exception:
                            logger.exception("Error in indoor unit callback")
                if parsed.outdoor_unit is not None:
                    for cb in self._odu_callbacks:
                        try:
                            await _dispatch(cb, parsed.outdoor_unit)
                        except Exception:
                            logger.exception("Error in outdoor unit callback")
                if parsed.controller is not None:
                    for cb in self._ctrl_callbacks:
                        try:
                            await _dispatch(cb, parsed.controller)
                        except Exception:
                            logger.exception("Error in controller callback")
                if parsed.qsm is not None:
                    for cb in self._qsm_callbacks:
                        try:
                            await _dispatch(cb, parsed.qsm)
                        except Exception:
                            logger.exception("Error in QSM callback")
                if parsed.remote_sensor is not None:
                    for cb in self._rs_callbacks:
                        try:
                            await _dispatch(cb, parsed.remote_sensor)
                        except Exception:
                            logger.exception("Error in remote sensor callback")
                if parsed.controller_remote_sensor is not None:
                    for cb in self._crs_callbacks:
                        try:
                            await _dispatch(cb, parsed.controller_remote_sensor)
                        except Exception:
                            logger.exception("Error in controller remote sensor callback")
                if parsed.software_update_info is not None:
                    for cb in self._sui_callbacks:
                        try:
                            await _dispatch(cb, parsed.software_update_info)
                        except Exception:
                            logger.exception("Error in software update info callback")

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
                    logger.warning("Stream got UNAUTHENTICATED; refreshing token (attempt %d)", attempt + 1)
                    try:
                        await self._authenticate()
                    except Exception:
                        logger.exception("Token refresh failed; giving up stream")
                        self._error = exc
                        break
                elif can_retry:
                    logger.warning(
                        "Stream error %s: %s; reconnecting in %.1fs (attempt %d)",
                        exc.code(),
                        exc.details(),
                        delay,
                        attempt + 1,
                    )
                else:
                    logger.error("Stream error %s: %s; max reconnects reached", exc.code(), exc.details())
                    self._error = QuiltStreamError(f"Stream error: {exc.code()} - {exc.details()}")
                    break

                await asyncio.sleep(delay)
                delay = min(delay * 2, 60.0)
                attempt += 1
                # Reset request queue so the next connection re-subscribes cleanly
                self._request_queue = asyncio.Queue()

        if self._error is not None:
            for cb in self._error_callbacks:
                try:
                    await _dispatch(cb, self._error)
                except Exception:
                    logger.exception("Error in error callback")
            if not self._error_callbacks:
                # Propagate to the task so the caller can observe it
                raise self._error

    # --- Lifecycle ---

    async def run_forever(self) -> None:
        """Run the stream inline (blocking) until cancelled or fatal error."""
        self._running = True
        await self._run_stream_with_reconnect()

    async def start(self) -> None:
        """Start the stream listener as a background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_stream_with_reconnect())
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
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, QuiltStreamError):
                await self._task
            self._task = None

    async def __aenter__(self) -> NotifierStream:
        await self.start()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.stop()
