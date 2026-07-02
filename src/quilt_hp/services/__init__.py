"""Service layer — thin async wrappers around gRPC stubs."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

import grpc
import grpc.aio

from quilt_hp.exceptions import QuiltConnectionError, QuiltError, QuiltNotFoundError

logger = logging.getLogger(__name__)

_TRANSIENT_GRPC_CODES = {
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.DEADLINE_EXCEEDED,
}


class _GrpcCallContext:
    def __init__(
        self,
        operation: str,
        *,
        max_retries: int = 0,
        retry_delay: float = 1.0,
        retry_backoff: float = 2.0,
    ) -> None:
        self._operation = operation
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._retry_backoff = retry_backoff

    async def __aenter__(self) -> Callable[..., Awaitable[Any]]:
        return self.run

    async def __aexit__(self, exc_type: object, exc: BaseException | None, tb: object) -> bool:
        del exc_type, tb
        if exc is None:
            return False
        # Never translate CancelledError / KeyboardInterrupt / SystemExit —
        # swallowing cancellation breaks asyncio.timeout() and task
        # cancellation semantics for the caller.
        if not isinstance(exc, Exception):
            return False
        translated = self._translate_exception(exc)
        if translated is exc:
            raise exc
        raise translated from exc

    async def run(self, func: Callable[..., Awaitable[Any]], /, *args: Any, **kwargs: Any) -> Any:
        attempt = 0
        delay = self._retry_delay
        while True:
            try:
                return await func(*args, **kwargs)
            except Exception as exc:
                wrapped = self._translate_exception(exc)
                if not self._should_retry(exc, attempt):
                    if wrapped is exc:
                        raise
                    raise wrapped from exc
                attempt += 1
                logger.warning(
                    "%s failed with %s; retrying in %.1fs (%d/%d)",
                    self._operation,
                    cast("grpc.aio.AioRpcError", exc).code(),
                    delay,
                    attempt,
                    self._max_retries,
                )
                await asyncio.sleep(delay)
                delay *= self._retry_backoff

    def _should_retry(self, exc: BaseException, attempt: int) -> bool:
        return (
            isinstance(exc, grpc.aio.AioRpcError)
            and exc.code() in _TRANSIENT_GRPC_CODES
            and attempt < self._max_retries
        )

    def _translate_exception(self, exc: BaseException) -> QuiltError:
        if isinstance(exc, QuiltError):
            return exc
        if isinstance(exc, grpc.aio.AioRpcError):
            if exc.code() in _TRANSIENT_GRPC_CODES:
                return QuiltConnectionError(f"{self._operation} failed: {exc.details()}")
            if exc.code() == grpc.StatusCode.NOT_FOUND:
                return QuiltNotFoundError(f"{self._operation} failed: {exc.details()}")
            return QuiltError(f"{self._operation} failed: {exc.details()}")
        logger.debug("Unexpected error in %s: %s", self._operation, exc)
        return QuiltError(f"{self._operation} failed: {exc}")


def grpc_call(
    operation: str,
    *,
    max_retries: int = 0,
    retry_delay: float = 1.0,
    retry_backoff: float = 2.0,
) -> _GrpcCallContext:
    """Translate gRPC errors and optionally retry transient unary calls.

    Usage::

        async with grpc_call("UpdateSpace"):
            result = await stub.UpdateSpace(request)

        async with grpc_call("ListSystems", max_retries=2) as call:
            result = await call(stub.ListSystems, request)
    """
    return _GrpcCallContext(
        operation,
        max_retries=max_retries,
        retry_delay=retry_delay,
        retry_backoff=retry_backoff,
    )
