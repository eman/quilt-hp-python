"""Async gRPC transport — channel creation and auth interceptor."""

from __future__ import annotations

import inspect
import logging
import weakref
from collections.abc import Awaitable, Callable
from typing import cast

import grpc
import grpc.aio

from quilt_hp.const import (
    APP_VERSION,
    GRPC_CHANNEL_OPTIONS,
    Environment,
    grpc_host,
)
from quilt_hp.exceptions import QuiltAuthError
from quilt_hp.tokens import CurrentTokenProvider, TokenRefreshContext, TokenRefreshReason

type RefreshCallback = (
    Callable[[], Awaitable[None]] | Callable[[TokenRefreshContext], Awaitable[None]]
)
type TokenProviderLike = Callable[[], str] | CurrentTokenProvider

logger = logging.getLogger(__name__)
_REFRESH_CALLBACK_HAS_PARAMS: weakref.WeakKeyDictionary[object, bool] = weakref.WeakKeyDictionary()


def _resolve_token_provider(token_provider: TokenProviderLike) -> Callable[[], str]:
    if callable(token_provider):
        return token_provider
    return token_provider.get_current_token


async def _invoke_refresh_callback(
    refresh_callback: RefreshCallback, context: TokenRefreshContext
) -> None:
    has_params = _REFRESH_CALLBACK_HAS_PARAMS.get(refresh_callback)
    if has_params is None:
        try:
            has_params = bool(inspect.signature(refresh_callback).parameters)
        except TypeError, ValueError:
            has_params = False
        try:
            _REFRESH_CALLBACK_HAS_PARAMS[refresh_callback] = has_params
        except TypeError:
            pass  # unhashable callable — skip caching
    if has_params:
        await cast("Callable[[TokenRefreshContext], Awaitable[None]]", refresh_callback)(context)
        return
    await cast("Callable[[], Awaitable[None]]", refresh_callback)()


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
        return grpc.aio.ClientCallDetails(
            method=client_call_details.method,
            timeout=client_call_details.timeout,
            metadata=list(client_call_details.metadata or []) + self._metadata(),
            credentials=client_call_details.credentials,
            wait_for_ready=client_call_details.wait_for_ready,
        )

    async def _refresh_and_retry(
        self,
        continuation: Callable[..., Awaitable[object]],
        client_call_details: grpc.aio.ClientCallDetails,
        *args: object,
    ) -> object:
        """Refresh the token and retry the call once.

        Raises:
            QuiltAuthError: If the retry still receives UNAUTHENTICATED after
                the token refresh, indicating the refresh token is also expired
                or the credentials are otherwise invalid.
        """
        if self._refresh_callback is not None:
            await _invoke_refresh_callback(
                self._refresh_callback,
                TokenRefreshContext(
                    reason=TokenRefreshReason.TRANSPORT_UNAUTHENTICATED,
                    source="transport",
                ),
            )
        try:
            return await continuation(self._patch(client_call_details), *args)
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
        try:
            return await continuation(self._patch(client_call_details), request)
        except grpc.aio.AioRpcError as exc:
            if exc.code() == grpc.StatusCode.UNAUTHENTICATED and self._refresh_callback:
                logger.warning("Retrying unary RPC after UNAUTHENTICATED response")
                return await self._refresh_and_retry(continuation, client_call_details, request)
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
        try:
            return await continuation(self._patch(client_call_details), request)
        except grpc.aio.AioRpcError as exc:
            if exc.code() == grpc.StatusCode.UNAUTHENTICATED and self._refresh_callback:
                logger.warning("Retrying streaming RPC setup after UNAUTHENTICATED response")
                return await self._refresh_and_retry(continuation, client_call_details, request)
            raise

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

    Useful for stream-stream RPCs where the channel interceptor may not fire.
    """
    resolved_provider = _resolve_token_provider(token_provider)
    logger.debug("Building auth metadata")
    return [
        ("authorization", resolved_provider()),
        ("x-quilt-app-version", APP_VERSION),
    ]
