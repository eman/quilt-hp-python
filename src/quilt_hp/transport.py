"""Async gRPC transport — channel creation and auth interceptor."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

import grpc
import grpc.aio

from quilt_hp.const import (
    APP_VERSION,
    GRPC_CHANNEL_OPTIONS,
    Environment,
    grpc_host,
)
from quilt_hp.exceptions import QuiltAuthError
from quilt_hp.tokens import (
    CurrentTokenProvider,
    TokenRefreshContext,
    TokenRefreshReason,
    invoke_refresh_callback,
)

type RefreshCallback = (
    Callable[[], Awaitable[None]] | Callable[[TokenRefreshContext], Awaitable[None]]
)
type TokenProviderLike = Callable[[], str] | CurrentTokenProvider

logger = logging.getLogger(__name__)


def _resolve_token_provider(token_provider: TokenProviderLike) -> Callable[[], str]:
    if callable(token_provider):
        return token_provider
    return token_provider.get_current_token


class _AuthInterceptor(
    grpc.aio.UnaryUnaryClientInterceptor,  # type: ignore[misc]
    grpc.aio.UnaryStreamClientInterceptor,  # type: ignore[misc]
    grpc.aio.StreamUnaryClientInterceptor,  # type: ignore[misc]
    grpc.aio.StreamStreamClientInterceptor,  # type: ignore[misc]
):
    """Injects authorization and app-version metadata into every gRPC call.

    If ``refresh_callback`` is provided, it is awaited once on
    ``UNAUTHENTICATED`` and the call is retried with fresh credentials.
    """

    def __init__(
        self,
        token_provider: TokenProviderLike,
        refresh_callback: RefreshCallback | None = None,
    ) -> None:
        self._token_provider = _resolve_token_provider(token_provider)
        self._refresh_callback = refresh_callback

    def _metadata(self) -> list[tuple[str, str]]:
        logger.debug("Attaching auth metadata")
        return [
            ("authorization", self._token_provider()),
            ("x-quilt-app-version", APP_VERSION),
        ]

    def _patch(
        self, client_call_details: grpc.aio.ClientCallDetails
    ) -> grpc.aio.ClientCallDetails:
        existing = list(client_call_details.metadata or [])
        # Never duplicate keys: explicit per-call metadata (e.g. the notifier
        # stream's metadata_provider) wins over interceptor-supplied values.
        # Some proxies reject repeated authorization headers.
        existing_keys = {key.lower() for key, _ in existing}
        patched = existing + [
            (key, value) for key, value in self._metadata() if key.lower() not in existing_keys
        ]
        return grpc.aio.ClientCallDetails(
            method=client_call_details.method,
            timeout=client_call_details.timeout,
            metadata=patched,
            credentials=client_call_details.credentials,
            wait_for_ready=client_call_details.wait_for_ready,
        )

    async def _refresh(self) -> None:
        if self._refresh_callback is not None:
            await invoke_refresh_callback(
                self._refresh_callback,
                TokenRefreshContext(
                    reason=TokenRefreshReason.TRANSPORT_UNAUTHENTICATED,
                    source="transport",
                ),
            )

    async def _refresh_and_retry_unary(
        self,
        continuation: Callable[..., Awaitable[object]],
        client_call_details: grpc.aio.ClientCallDetails,
        request: object,
    ) -> object:
        """Refresh the token and retry a unary RPC once.

        Raises:
            QuiltAuthError: If the retry still receives UNAUTHENTICATED after
                the token refresh, indicating the refresh token is also expired
                or the credentials are otherwise invalid.
        """
        await self._refresh()
        call = await continuation(self._patch(client_call_details), request)
        try:
            return await cast("Awaitable[object]", call)
        except grpc.aio.AioRpcError as exc:
            if exc.code() == grpc.StatusCode.UNAUTHENTICATED:
                raise QuiltAuthError(
                    "Token refresh did not restore authentication; re-login required"
                ) from exc
            raise

    async def intercept_unary_unary(
        self,
        continuation: Callable[
            [grpc.aio.ClientCallDetails, object],
            Awaitable[object],
        ],
        client_call_details: grpc.aio.ClientCallDetails,
        request: object,
    ) -> object:
        # NOTE: awaiting the continuation only returns the *call* object; the
        # RPC result (and any AioRpcError) surfaces when the call itself is
        # awaited.  The call must be awaited here for UNAUTHENTICATED retry
        # to work — returning the un-awaited call would make this dead code.
        call = await continuation(self._patch(client_call_details), request)
        try:
            return await cast("Awaitable[object]", call)
        except grpc.aio.AioRpcError as exc:
            if exc.code() == grpc.StatusCode.UNAUTHENTICATED and self._refresh_callback:
                logger.warning("Retrying unary RPC after UNAUTHENTICATED response")
                return await self._refresh_and_retry_unary(
                    continuation, client_call_details, request
                )
            raise

    async def intercept_unary_stream(
        self,
        continuation: Callable[
            [grpc.aio.ClientCallDetails, object],
            Awaitable[object],
        ],
        client_call_details: grpc.aio.ClientCallDetails,
        request: object,
    ) -> object:
        call = await continuation(self._patch(client_call_details), request)
        try:
            await cast("Any", call).wait_for_connection()
        except grpc.aio.AioRpcError as exc:
            if exc.code() == grpc.StatusCode.UNAUTHENTICATED and self._refresh_callback:
                logger.warning("Retrying streaming RPC setup after UNAUTHENTICATED response")
                await self._refresh()
                retried = await continuation(self._patch(client_call_details), request)
                try:
                    await cast("Any", retried).wait_for_connection()
                except grpc.aio.AioRpcError as retry_exc:
                    if retry_exc.code() == grpc.StatusCode.UNAUTHENTICATED:
                        raise QuiltAuthError(
                            "Token refresh did not restore authentication; re-login required"
                        ) from retry_exc
                    raise
                return retried
            raise
        return call

    async def intercept_stream_unary(
        self,
        continuation: Callable[
            [grpc.aio.ClientCallDetails, object],
            Awaitable[object],
        ],
        client_call_details: grpc.aio.ClientCallDetails,
        request_iterator: object,
    ) -> object:
        return await continuation(self._patch(client_call_details), request_iterator)

    async def intercept_stream_stream(
        self,
        continuation: Callable[
            [grpc.aio.ClientCallDetails, object],
            Awaitable[object],
        ],
        client_call_details: grpc.aio.ClientCallDetails,
        request_iterator: object,
    ) -> object:
        return await continuation(self._patch(client_call_details), request_iterator)


def create_channel(
    token_provider: TokenProviderLike,
    environment: Environment = Environment.PROD,
    refresh_callback: RefreshCallback | None = None,
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
    logger.debug("Creating gRPC channel for host %s", host)
    creds = grpc.ssl_channel_credentials()
    interceptors = [_AuthInterceptor(token_provider, refresh_callback)]
    return grpc.aio.secure_channel(
        host,
        creds,
        options=GRPC_CHANNEL_OPTIONS,
        interceptors=interceptors,
    )


def auth_metadata(token_provider: TokenProviderLike) -> list[tuple[str, str]]:
    """Build gRPC metadata with auth headers.

    Used by the notifier stream to capture fresh credentials per (re)connect.
    The channel interceptor skips keys already present in per-call metadata,
    so headers built here are never duplicated on the wire.
    """
    resolved_provider = _resolve_token_provider(token_provider)
    logger.debug("Building auth metadata")
    return [
        ("authorization", resolved_provider()),
        ("x-quilt-app-version", APP_VERSION),
    ]
