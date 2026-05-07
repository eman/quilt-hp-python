"""Token types and storage protocols for Quilt authentication.

The core library defines the data types and an async-first ``TokenStore``
protocol. Persistence is the caller's responsibility — the CLI provides
``FileStore`` in ``quilt_hp.cli.store``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

_TOKEN_BUFFER_S = 300  # treat tokens as expired 5 min before actual expiry


@dataclass(slots=True)
class CachedTokens:
    """A Cognito IdToken plus its refresh token and expiry timestamp."""

    id_token: str
    refresh_token: str
    expires_at: float  # unix timestamp

    @property
    def is_expired(self) -> bool:
        """True if the IdToken has expired (with a 5-minute safety buffer)."""
        return time.time() > self.expires_at - _TOKEN_BUFFER_S


class TokenStore(Protocol):
    """Async-first protocol for token persistence.

    Implement this to integrate with any storage backend
    (filesystem, HA secure storage, database, keychain, …).
    """

    async def load(self, email: str) -> CachedTokens | None:
        """Return cached tokens for *email*, or None if absent / invalid."""
        ...

    async def save(self, email: str, tokens: CachedTokens) -> None:
        """Persist *tokens* for *email*."""
        ...


class LegacyTokenStore(Protocol):
    """Compatibility protocol for existing synchronous token stores."""

    def load(self, email: str) -> CachedTokens | None:
        """Return cached tokens for *email*, or None if absent / invalid."""
        ...

    def save(self, email: str, tokens: CachedTokens) -> None:
        """Persist *tokens* for *email*."""
        ...


type TokenStoreLike = TokenStore | LegacyTokenStore
type TokenPersistenceBackend = TokenStoreLike


class CurrentTokenProvider(Protocol):
    """Protocol for objects that can provide the current auth token."""

    def get_current_token(self) -> str:
        """Return the current authorization token."""
        ...


class TokenRefreshReason(StrEnum):
    """Why a token refresh is being attempted."""

    EXPIRED_CACHED_TOKEN = "expired_cached_token"
    TRANSPORT_UNAUTHENTICATED = "transport_unauthenticated"
    STREAM_UNAUTHENTICATED = "stream_unauthenticated"


@dataclass(slots=True, frozen=True)
class TokenRefreshContext:
    """Context describing a token refresh attempt."""

    reason: TokenRefreshReason
    source: str
    attempt: int = 1


class RefreshFailureAction(StrEnum):
    """Policy decision for handling refresh failures."""

    FALLBACK_TO_OTP = "fallback_to_otp"
    RAISE = "raise"


class TokenRefreshHooks(Protocol):
    """Optional lifecycle hooks invoked around token refresh attempts."""

    async def on_refresh_start(self, context: TokenRefreshContext) -> None:
        """Called before attempting token refresh."""
        ...

    async def on_refresh_success(self, context: TokenRefreshContext, tokens: CachedTokens) -> None:
        """Called when refresh succeeds and new tokens are produced."""
        ...

    async def on_refresh_failure(self, context: TokenRefreshContext, error: Exception) -> None:
        """Called when refresh fails."""
        ...


class TokenRefreshPolicy(Protocol):
    """Host-defined policy for deciding what to do after refresh failure."""

    def on_refresh_failure(
        self, context: TokenRefreshContext, error: Exception
    ) -> RefreshFailureAction:
        """Return fallback strategy when refresh fails."""
        ...
