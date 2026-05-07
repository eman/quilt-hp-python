"""Tests for the transport layer interceptor."""

from __future__ import annotations

import pytest

from quilt_hp import transport
from quilt_hp.const import APP_VERSION, Environment, grpc_host
from quilt_hp.tokens import TokenRefreshContext, TokenRefreshReason


def test_grpc_host_prod() -> None:
    """PROD endpoint returns the expected host."""
    assert grpc_host(Environment.PROD) == "api.prod.quilt.cloud:443"


def test_grpc_host_staging() -> None:
    """STAGING endpoint returns the expected host."""
    assert grpc_host(Environment.STAGING) == "api.staging.quilt.cloud:443"


def test_app_version() -> None:
    """App version constant is set."""
    assert APP_VERSION == "1.0.25"


class _Provider:
    def get_current_token(self) -> str:
        return "Bearer protocol-token"


def test_auth_metadata_accepts_provider_protocol() -> None:
    metadata = transport.auth_metadata(_Provider())
    assert ("authorization", "Bearer protocol-token") in metadata


@pytest.mark.asyncio
async def test_invoke_refresh_callback_passes_context() -> None:
    captured: list[TokenRefreshContext] = []

    async def _with_context(context: TokenRefreshContext) -> None:
        captured.append(context)

    context = TokenRefreshContext(
        reason=TokenRefreshReason.TRANSPORT_UNAUTHENTICATED,
        source="test",
    )
    await transport._invoke_refresh_callback(_with_context, context)
    assert captured == [context]


@pytest.mark.asyncio
async def test_invoke_refresh_callback_supports_legacy_signature() -> None:
    calls: list[str] = []

    async def _legacy() -> None:
        calls.append("called")

    context = TokenRefreshContext(
        reason=TokenRefreshReason.TRANSPORT_UNAUTHENTICATED,
        source="test",
    )
    await transport._invoke_refresh_callback(_legacy, context)
    assert calls == ["called"]
