# Token management reference

This page is a complete reference for the token system: data types, store protocols, refresh hooks and policies, and custom token persistence.

## Overview

Authentication uses AWS Cognito. After a successful login, the library holds two tokens:

- **IdToken**: A short-lived JWT (typically about 1 hour) sent as the `authorization` header on every gRPC call.
- **RefreshToken**: A long-lived token (weeks to months) used to renew the IdToken without user interaction.

The library never stores tokens globally. They live on the `QuiltClient` instance (`self._token`) and optionally in a `TokenStore` for persistence across processes. The `FileStore` in `quilt_hp.cli.store` is the CLI's implementation, but you can provide any store that implements the protocol.

---

## `CachedTokens`

```python
@dataclass(slots=True)
class CachedTokens:
    id_token: str        # Cognito IdToken (JWT)
    refresh_token: str   # Cognito RefreshToken
    expires_at: float    # Unix timestamp when id_token expires

    @property
    def is_expired(self) -> bool:
        """True if the IdToken should be treated as expired.

        Applies a 5-minute safety buffer: returns True when
        time.time() > expires_at - 300.
        """
```

`CachedTokens` is the data class that holds the token pair. `expires_at` is set from Cognito's `ExpiresIn` field (number of seconds until expiry) added to the current time at login or refresh time.

The 5-minute buffer in `is_expired` means the library proactively refreshes before actual expiry, preventing races where a token is valid at the start of an operation but expires before the RPC completes.

---

## `TokenStore` (async)

```python
class TokenStore(Protocol):
    async def load(self, email: str) -> CachedTokens | None:
        """Return cached tokens for email, or None if absent / invalid."""
        ...

    async def save(self, email: str, tokens: CachedTokens) -> None:
        """Persist tokens for email."""
        ...
```

The preferred protocol for new implementations. Both `load` and `save` are async coroutines. The store is keyed by email address, so a single store instance can manage tokens for multiple accounts.

---

## `LegacyTokenStore` (sync)

```python
class LegacyTokenStore(Protocol):
    def load(self, email: str) -> CachedTokens | None: ...
    def save(self, email: str, tokens: CachedTokens) -> None: ...
```

A compatibility protocol for synchronous stores. The library wraps synchronous calls with `asyncio.to_thread()` so they do not block the event loop.

---

## `TokenStoreLike`

```python
type TokenStoreLike = TokenStore | LegacyTokenStore
```

Type alias accepted by `QuiltClient(token_store=...)` and `authenticate()`.

---

## `FileStore`

`FileStore` in `quilt_hp.cli.store` is the CLI's implementation of `TokenStore`. It stores tokens as JSON in `~/.config/quilt-hp/tokens.json` with `chmod 0o600` (readable only by the owner).

```python
from quilt_hp.cli.store import FileStore

store = FileStore()
tokens = await store.load("you@example.com")  # CachedTokens | None
await store.save("you@example.com", tokens)
store.clear_tokens("you@example.com")  # remove cached tokens
emails = store.list_emails()  # all accounts with cached tokens
```

The JSON format is:
```json
{
  "you@example.com": {
    "id_token": "eyJ...",
    "refresh_token": "eyJ...",
    "expires_at": 1720000000.0
  }
}
```

---

## Implementing a custom `TokenStore`

Implement `TokenStore` for any backend (database, Redis, AWS Secrets Manager, Home Assistant storage, system keychain, etc.):

```python
from quilt_hp.tokens import TokenStore, CachedTokens
import json

class DatabaseTokenStore:
    def __init__(self, db_session) -> None:
        self._db = db_session

    async def load(self, email: str) -> CachedTokens | None:
        row = await self._db.fetch_one(
            "SELECT id_token, refresh_token, expires_at FROM quilt_tokens WHERE email = :email",
            {"email": email},
        )
        if row is None:
            return None
        return CachedTokens(
            id_token=row["id_token"],
            refresh_token=row["refresh_token"],
            expires_at=row["expires_at"],
        )

    async def save(self, email: str, tokens: CachedTokens) -> None:
        await self._db.execute(
            """
            INSERT INTO quilt_tokens (email, id_token, refresh_token, expires_at)
            VALUES (:email, :id_token, :refresh_token, :expires_at)
            ON CONFLICT (email) DO UPDATE SET
                id_token = EXCLUDED.id_token,
                refresh_token = EXCLUDED.refresh_token,
                expires_at = EXCLUDED.expires_at
            """,
            {
                "email": email,
                "id_token": tokens.id_token,
                "refresh_token": tokens.refresh_token,
                "expires_at": tokens.expires_at,
            },
        )
```

---

## `TokenRefreshHooks`

```python
class TokenRefreshHooks(Protocol):
    async def on_refresh_start(self, context: TokenRefreshContext) -> None:
        """Called before attempting a token refresh."""
        ...

    async def on_refresh_success(
        self, context: TokenRefreshContext, tokens: CachedTokens
    ) -> None:
        """Called when refresh succeeds and new tokens are produced."""
        ...

    async def on_refresh_failure(
        self, context: TokenRefreshContext, error: Exception
    ) -> None:
        """Called when refresh fails."""
        ...
```

Hooks are called in `authenticate()` during the refresh path. They are useful for logging, metrics, and updating secondary caches. Hook failures are not caught, so if a hook raises, the exception propagates.

---

## `TokenRefreshPolicy`

```python
class TokenRefreshPolicy(Protocol):
    def on_refresh_failure(
        self, context: TokenRefreshContext, error: Exception
    ) -> RefreshFailureAction:
        """Return the action to take when token refresh fails."""
        ...
```

The policy is consulted after `TokenRefreshHooks.on_refresh_failure`. The return value determines what happens next:

- `RefreshFailureAction.FALLBACK_TO_OTP`: Falls through to the OTP login flow. This is the default when no policy is configured, and it is not useful in daemon contexts where there is no OTP prompt.
- `RefreshFailureAction.RAISE`: Re-raises the refresh error immediately without attempting OTP.

---

## `TokenRefreshContext`

```python
@dataclass(slots=True, frozen=True)
class TokenRefreshContext:
    reason: TokenRefreshReason
    source: str
    attempt: int = 1
```

Context object passed to refresh hooks and the refresh callback. Fields:

- `reason`: Why the refresh is happening (see below).
- `source`: Module or location that triggered the refresh (for example, `"authenticate"`, `"transport"`, `"streaming"`).
- `attempt`: Which attempt this is, starting at 1.

---

## `TokenRefreshReason`

```python
class TokenRefreshReason(StrEnum):
    EXPIRED_CACHED_TOKEN = "expired_cached_token"
    TRANSPORT_UNAUTHENTICATED = "transport_unauthenticated"
    STREAM_UNAUTHENTICATED = "stream_unauthenticated"
```

- `EXPIRED_CACHED_TOKEN`: The cached token expired, so `authenticate()` is performing a proactive refresh.
- `TRANSPORT_UNAUTHENTICATED`: The gRPC transport interceptor received `UNAUTHENTICATED` on a unary RPC.
- `STREAM_UNAUTHENTICATED`: The `NotifierStream` received `UNAUTHENTICATED` and is refreshing before reconnecting.

For the two `*_UNAUTHENTICATED` reasons, `authenticate()` does **not** trust a
locally-unexpired cached IdToken — the server just rejected it, so a Cognito
refresh is forced. If the Cognito response contains a rotated `RefreshToken`,
the new value is persisted to the token store.

---

## `RefreshFailureAction`

```python
class RefreshFailureAction(StrEnum):
    FALLBACK_TO_OTP = "fallback_to_otp"
    RAISE = "raise"
```

---

## `CurrentTokenProvider`

```python
class CurrentTokenProvider(Protocol):
    def get_current_token(self) -> str:
        """Return the current authorization token."""
        ...
```

Protocol implemented by `QuiltClient` (`get_current_token` returns `self._token`). The transport interceptor calls `get_current_token()` on every outbound RPC. You can use this protocol to supply tokens from any source when using `create_channel()` directly.
