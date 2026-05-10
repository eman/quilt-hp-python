from __future__ import annotations

from unittest.mock import MagicMock

import grpc
import pytest

from quilt_hp import transport
from quilt_hp.const import Environment
from quilt_hp.exceptions import QuiltAuthError


class _FakeRpcError(grpc.aio.AioRpcError):
    def __init__(self, code: grpc.StatusCode, details: str = "") -> None:
        self._code = code
        self._details = details

    def code(self) -> grpc.StatusCode:  # type: ignore[override]
        return self._code

    def details(self) -> str:  # type: ignore[override]
        return self._details


@pytest.mark.asyncio
async def test_invoke_refresh_callback_handles_signature_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []

    async def _legacy() -> None:
        called.append("legacy")

    monkeypatch.setattr(transport.inspect, "signature", MagicMock(side_effect=TypeError("bad")))

    await transport._invoke_refresh_callback(
        _legacy,
        transport.TokenRefreshContext(
            reason=transport.TokenRefreshReason.TRANSPORT_UNAUTHENTICATED,
            source="test",
        ),
    )
    assert called == ["legacy"]


@pytest.mark.asyncio
async def test_auth_interceptor_retry_paths() -> None:
    refreshed: list[str] = []

    async def _refresh(_context: transport.TokenRefreshContext) -> None:
        refreshed.append("yes")

    interceptor = transport._AuthInterceptor(lambda: "Bearer abc", refresh_callback=_refresh)
    details = grpc.aio.ClientCallDetails(
        method="/svc/method",
        timeout=1,
        metadata=[("x-test", "1")],
        credentials=None,
        wait_for_ready=False,
    )

    calls = 0

    async def _continuation(call_details: grpc.aio.ClientCallDetails, request: object) -> object:
        nonlocal calls
        calls += 1
        assert ("authorization", "Bearer abc") in list(call_details.metadata or [])
        if calls == 1:
            raise _FakeRpcError(grpc.StatusCode.UNAUTHENTICATED, "expired")
        return request

    assert await interceptor.intercept_unary_unary(_continuation, details, "req") == "req"
    assert (
        await interceptor.intercept_unary_stream(_continuation, details, "stream-req")
        == "stream-req"
    )
    assert refreshed == ["yes"]


@pytest.mark.asyncio
async def test_auth_interceptor_non_retry_paths() -> None:
    interceptor = transport._AuthInterceptor(lambda: "Bearer abc")
    details = grpc.aio.ClientCallDetails(
        method="/svc/method",
        timeout=1,
        metadata=None,
        credentials=None,
        wait_for_ready=False,
    )

    async def _stream_continuation(
        call_details: grpc.aio.ClientCallDetails, request: object
    ) -> object:
        assert ("authorization", "Bearer abc") in list(call_details.metadata or [])
        return request

    req_iter = object()
    assert (
        await interceptor.intercept_stream_unary(_stream_continuation, details, req_iter)
        is req_iter
    )
    assert (
        await interceptor.intercept_stream_stream(_stream_continuation, details, req_iter)
        is req_iter
    )

    async def _failing(_call_details: grpc.aio.ClientCallDetails, _request: object) -> object:
        raise _FakeRpcError(grpc.StatusCode.INTERNAL, "boom")

    with pytest.raises(_FakeRpcError):
        await interceptor.intercept_unary_unary(_failing, details, "req")


@pytest.mark.asyncio
async def test_auth_interceptor_raises_auth_error_when_retry_also_fails() -> None:
    """If the token refresh doesn't help (e.g. refresh token expired), raise QuiltAuthError."""
    refreshed: list[str] = []

    async def _refresh(_context: transport.TokenRefreshContext) -> None:
        refreshed.append("yes")

    interceptor = transport._AuthInterceptor(lambda: "Bearer abc", refresh_callback=_refresh)
    details = grpc.aio.ClientCallDetails(
        method="/svc/method",
        timeout=1,
        metadata=None,
        credentials=None,
        wait_for_ready=False,
    )

    async def _always_unauthenticated(
        _call_details: grpc.aio.ClientCallDetails, _request: object
    ) -> object:
        raise _FakeRpcError(grpc.StatusCode.UNAUTHENTICATED, "Jwt is expired")

    with pytest.raises(QuiltAuthError, match="re-login required"):
        await interceptor.intercept_unary_unary(_always_unauthenticated, details, "req")

    assert refreshed == ["yes"], "refresh callback should have been called exactly once"


def test_create_channel_and_provider_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Provider:
        def get_current_token(self) -> str:
            return "Bearer token"

    provider = _Provider()
    assert transport._resolve_token_provider(provider)() == "Bearer token"

    secure = MagicMock(return_value="channel")
    monkeypatch.setattr(transport.grpc, "ssl_channel_credentials", lambda: "creds")
    monkeypatch.setattr(transport.grpc.aio, "secure_channel", secure)

    channel = transport.create_channel(lambda: "Bearer x", environment=Environment.STAGING)
    assert channel == "channel"
    secure.assert_called_once()
