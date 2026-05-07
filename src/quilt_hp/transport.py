"""Async gRPC transport — channel creation and auth interceptor."""

from __future__ import annotations

from typing import TYPE_CHECKING

import grpc
import grpc.aio

from quilt_hp.const import APP_VERSION, GRPC_CHANNEL_OPTIONS, Environment, grpc_host

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class _AuthInterceptor(  # type: ignore[misc]
    grpc.aio.UnaryUnaryClientInterceptor,
    grpc.aio.UnaryStreamClientInterceptor,
    grpc.aio.StreamUnaryClientInterceptor,
    grpc.aio.StreamStreamClientInterceptor,
):
    """Injects authorization and app-version metadata into every gRPC call.

    If ``refresh_callback`` is provided, it is awaited once on
    ``UNAUTHENTICATED`` and the call is retried with fresh credentials.
    """

    def __init__(
        self,
        token_provider: Callable[[], str],
        refresh_callback: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._token_provider = token_provider
        self._refresh_callback = refresh_callback

    def _metadata(self) -> list[tuple[str, str]]:
        return [
            ("authorization", self._token_provider()),
            ("x-quilt-app-version", APP_VERSION),
        ]

    def _patch(self, client_call_details: grpc.aio.ClientCallDetails) -> grpc.aio.ClientCallDetails:
        return grpc.aio.ClientCallDetails(
            method=client_call_details.method,
            timeout=client_call_details.timeout,
            metadata=list(client_call_details.metadata or []) + self._metadata(),
            credentials=client_call_details.credentials,
            wait_for_ready=client_call_details.wait_for_ready,
        )

    async def _refresh_and_retry(self, continuation, client_call_details, *args):
        """Refresh the token and retry the call once."""
        if self._refresh_callback is not None:
            await self._refresh_callback()
        return await continuation(self._patch(client_call_details), *args)

    async def intercept_unary_unary(
        self,
        continuation: grpc.aio.UnaryUnaryClientInterceptor,
        client_call_details: grpc.aio.ClientCallDetails,
        request: object,
    ) -> object:
        try:
            return await continuation(self._patch(client_call_details), request)
        except grpc.aio.AioRpcError as exc:
            if exc.code() == grpc.StatusCode.UNAUTHENTICATED and self._refresh_callback:
                return await self._refresh_and_retry(continuation, client_call_details, request)
            raise

    async def intercept_unary_stream(
        self,
        continuation: grpc.aio.UnaryStreamClientInterceptor,
        client_call_details: grpc.aio.ClientCallDetails,
        request: object,
    ) -> object:
        try:
            return await continuation(self._patch(client_call_details), request)
        except grpc.aio.AioRpcError as exc:
            if exc.code() == grpc.StatusCode.UNAUTHENTICATED and self._refresh_callback:
                return await self._refresh_and_retry(continuation, client_call_details, request)
            raise

    async def intercept_stream_unary(
        self,
        continuation: grpc.aio.StreamUnaryClientInterceptor,
        client_call_details: grpc.aio.ClientCallDetails,
        request_iterator: object,
    ) -> object:
        return await continuation(self._patch(client_call_details), request_iterator)

    async def intercept_stream_stream(
        self,
        continuation: grpc.aio.StreamStreamClientInterceptor,
        client_call_details: grpc.aio.ClientCallDetails,
        request_iterator: object,
    ) -> object:
        return await continuation(self._patch(client_call_details), request_iterator)


def create_channel(
    token_provider: Callable[[], str],
    environment: Environment = Environment.PROD,
    refresh_callback: Callable[[], Awaitable[None]] | None = None,
) -> grpc.aio.Channel:
    """Create an authenticated async gRPC channel.

    Args:
        token_provider: A callable that returns the current JWT token.
        environment: Which Quilt API environment to connect to.
        refresh_callback: Optional async callable invoked once on
            UNAUTHENTICATED to refresh the token before retrying.

    Returns:
        An async gRPC channel with TLS and auth interceptor.
    """
    host = grpc_host(environment)
    creds = grpc.ssl_channel_credentials()
    interceptors = [_AuthInterceptor(token_provider, refresh_callback)]
    return grpc.aio.secure_channel(
        host,
        creds,
        options=GRPC_CHANNEL_OPTIONS,
        interceptors=interceptors,
    )


def auth_metadata(token_provider: Callable[[], str]) -> list[tuple[str, str]]:
    """Build gRPC metadata with auth headers.

    Useful for stream-stream RPCs where the channel interceptor may not fire.
    """
    return [
        ("authorization", token_provider()),
        ("x-quilt-app-version", APP_VERSION),
    ]
