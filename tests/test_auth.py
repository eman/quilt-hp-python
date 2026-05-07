"""Tests for authentication token-store behavior."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from quilt_hp import auth
from quilt_hp.exceptions import QuiltAuthError
from quilt_hp.tokens import (
    CachedTokens,
    RefreshFailureAction,
    TokenRefreshContext,
    TokenRefreshReason,
)


@dataclass(slots=True)
class _AsyncStore:
    loaded: CachedTokens | None = None
    saved: list[tuple[str, CachedTokens]] = field(default_factory=list)

    async def load(self, _email: str) -> CachedTokens | None:
        return self.loaded

    async def save(self, email: str, tokens: CachedTokens) -> None:
        self.saved.append((email, tokens))


@dataclass(slots=True)
class _SyncStore:
    loaded: CachedTokens | None = None
    saved: list[tuple[str, CachedTokens]] = field(default_factory=list)

    def load(self, _email: str) -> CachedTokens | None:
        return self.loaded

    def save(self, email: str, tokens: CachedTokens) -> None:
        self.saved.append((email, tokens))


@dataclass(slots=True)
class _RefreshHooks:
    starts: list[TokenRefreshContext] = field(default_factory=list)
    successes: list[TokenRefreshContext] = field(default_factory=list)
    failures: list[tuple[TokenRefreshContext, Exception]] = field(default_factory=list)

    async def on_refresh_start(self, context: TokenRefreshContext) -> None:
        self.starts.append(context)

    async def on_refresh_success(
        self, context: TokenRefreshContext, _tokens: CachedTokens
    ) -> None:
        self.successes.append(context)

    async def on_refresh_failure(self, context: TokenRefreshContext, error: Exception) -> None:
        self.failures.append((context, error))


class _RaisePolicy:
    def on_refresh_failure(
        self, _context: TokenRefreshContext, _error: Exception
    ) -> RefreshFailureAction:
        return RefreshFailureAction.RAISE


@pytest.mark.asyncio
async def test_authenticate_returns_cached_token_without_saving() -> None:
    store = _AsyncStore(
        loaded=CachedTokens(id_token="cached-id", refresh_token="refresh", expires_at=9999999999.0)
    )

    token = await auth.authenticate("user@test.com", token_store=store)

    assert token == "cached-id"
    assert store.saved == []


@pytest.mark.asyncio
async def test_authenticate_refreshes_and_persists_with_async_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _AsyncStore(
        loaded=CachedTokens(id_token="old-id", refresh_token="refresh-1", expires_at=0.0)
    )

    async def _fake_refresh(_refresh: str) -> dict[str, str | int]:
        return {"IdToken": "new-id", "ExpiresIn": 3600}

    monkeypatch.setattr(auth, "_do_refresh", _fake_refresh)

    token = await auth.authenticate("user@test.com", token_store=store)

    assert token == "new-id"
    assert len(store.saved) == 1
    email, saved = store.saved[0]
    assert email == "user@test.com"
    assert saved.id_token == "new-id"
    assert saved.refresh_token == "refresh-1"


@pytest.mark.asyncio
async def test_authenticate_otp_login_and_persist_with_sync_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _SyncStore(loaded=None)

    async def _fake_otp_login(
        _email: str, _otp_callback: auth.OtpCallback
    ) -> dict[str, str | int]:
        return {
            "IdToken": "otp-id",
            "RefreshToken": "otp-refresh",
            "ExpiresIn": 900,
        }

    monkeypatch.setattr(auth, "_do_otp_login", _fake_otp_login)

    token = await auth.authenticate(
        "user@test.com", otp_callback=lambda _email: "123456", token_store=store
    )

    assert token == "otp-id"
    assert len(store.saved) == 1
    email, saved = store.saved[0]
    assert email == "user@test.com"
    assert saved.id_token == "otp-id"
    assert saved.refresh_token == "otp-refresh"


@pytest.mark.asyncio
async def test_authenticate_refresh_hooks_receive_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _AsyncStore(
        loaded=CachedTokens(id_token="old-id", refresh_token="refresh-1", expires_at=0.0)
    )
    hooks = _RefreshHooks()

    async def _fake_refresh(_refresh: str) -> dict[str, str | int]:
        return {"IdToken": "new-id", "ExpiresIn": 3600}

    monkeypatch.setattr(auth, "_do_refresh", _fake_refresh)

    context = TokenRefreshContext(
        reason=TokenRefreshReason.TRANSPORT_UNAUTHENTICATED,
        source="test",
    )
    token = await auth.authenticate(
        "user@test.com",
        token_store=store,
        refresh_context=context,
        refresh_hooks=hooks,
    )

    assert token == "new-id"
    assert hooks.starts == [context]
    assert hooks.successes == [context]
    assert hooks.failures == []


@pytest.mark.asyncio
async def test_authenticate_refresh_failure_uses_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _AsyncStore(
        loaded=CachedTokens(id_token="old-id", refresh_token="refresh-1", expires_at=0.0)
    )
    hooks = _RefreshHooks()

    async def _fake_refresh(_refresh: str) -> dict[str, str | int]:
        raise QuiltAuthError("boom")

    monkeypatch.setattr(auth, "_do_refresh", _fake_refresh)

    with pytest.raises(QuiltAuthError, match="boom"):
        await auth.authenticate(
            "user@test.com",
            otp_callback=lambda _email: "123456",
            token_store=store,
            refresh_hooks=hooks,
            refresh_policy=_RaisePolicy(),
        )

    assert len(hooks.starts) == 1
    assert hooks.successes == []
    assert len(hooks.failures) == 1
