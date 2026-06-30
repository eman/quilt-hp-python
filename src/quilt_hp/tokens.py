"""Token types and storage protocols for Quilt authentication.

The core library defines the data types and an async-first ``TokenStore``
protocol. Persistence is the caller's responsibility — the CLI provides
``FileStore`` in ``quilt_hp.cli.store``.
"""

from __future__ import annotations

import inspect
import time
import weakref
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast

_TOKEN_BUFFER_S = 300  # treat tokens as expired 5 min before actual expiry

# Cache whether a refresh callback accepts a TokenRefreshContext argument,
# so inspect.signature is only called once per unique callable.
_REFRESH_CALLBACK_HAS_PARAMS: weakref.WeakKeyDictionary[object, bool] = weakref.WeakKeyDictionary()


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


type _RefreshCallback = (
    Callable[[], Awaitable[None]] | Callable[[TokenRefreshContext], Awaitable[None]]
)


async def invoke_refresh_callback(
    refresh_callback: _RefreshCallback, context: TokenRefreshContext
) -> None:
    """Invoke a refresh callback, passing context only if it accepts a parameter.

    Whether each callback accepts a ``TokenRefreshContext`` argument is cached
    per-callable in a WeakKeyDictionary so that ``inspect.signature`` is only
    called once per unique callback object.
    """
    try:
        has_params = _REFRESH_CALLBACK_HAS_PARAMS.get(refresh_callback)
    except TypeError:
        has_params = None  # non-weakrefable callable — skip cache
    if has_params is None:
        try:
            has_params = bool(inspect.signature(refresh_callback).parameters)
        except TypeError, ValueError:
            has_params = False
        try:
            _REFRESH_CALLBACK_HAS_PARAMS[refresh_callback] = has_params
        except TypeError:
            pass  # non-weakrefable callable — skip caching
    if has_params:
        await cast("Callable[[TokenRefreshContext], Awaitable[None]]", refresh_callback)(context)
        return
    await cast("Callable[[], Awaitable[None]]", refresh_callback)()
