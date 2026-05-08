# Public API reference

This page documents every symbol exported from `quilt_hp.__init__`. These are the only names you need to import for normal usage.

```python
from quilt_hp import (
    QuiltClient,
    Environment,
    QuiltError,
    QuiltAuthError,
    QuiltConnectionError,
    QuiltNotFoundError,
)
```

---

## `QuiltClient`

```python
class QuiltClient:
    def __init__(
        self,
        email: str,
        *,
        home: str | None = None,
        environment: Environment = Environment.PROD,
        snapshot_ttl_s: float = 0,
        token_store: TokenStoreLike | None = None,
        token_refresh_hooks: TokenRefreshHooks | None = None,
        token_refresh_policy: TokenRefreshPolicy | None = None,
    ) -> None: ...
```

The primary user-facing class. Manages authentication, the gRPC channel lifecycle, and exposes all high-level HVAC control methods.

**Parameters**:

- `email` — Quilt account email address. Used to look up tokens in the token store and as the Cognito username.
- `home` — Optional home name filter (substring match, case-insensitive) for multi-home accounts. When omitted, the first system returned by `ListSystems` is used.
- `environment` — Which Quilt API environment to connect to. Use `Environment.PROD` (default) for production.
- `snapshot_ttl_s` — If > 0, the result of `get_snapshot()` is cached for this many seconds. Subsequent calls within the TTL return the cached copy without a network round-trip. Set to 0 (default) to disable caching.
- `token_store` — Optional `TokenStore` (async) or `LegacyTokenStore` (sync) implementation for token persistence. Pass `None` (default) for in-memory-only operation.
- `token_refresh_hooks` — Optional `TokenRefreshHooks` implementation for observing token refresh lifecycle events.
- `token_refresh_policy` — Optional `TokenRefreshPolicy` implementation for controlling behaviour on refresh failure.

**Context manager**: `QuiltClient` implements `__aenter__` / `__aexit__`. On exit, the gRPC channel is closed. Always use as an async context manager:

```python
async with QuiltClient("you@example.com") as client:
    ...
```

For the complete method reference, see [QuiltClient API reference](client-reference.md).

---

## `Environment`

```python
class Environment(Enum):
    PROD = "prod"
    STAGING = "staging"
    DEV = "dev"
```

Selects which Quilt API environment to connect to.

| Value | gRPC host |
| --- | --- |
| `Environment.PROD` | `api.prod.quilt.cloud:443` |
| `Environment.STAGING` | `api.staging.quilt.cloud:443` |
| `Environment.DEV` | `api.dev.quilt.cloud:443` |

Most users should use `Environment.PROD` (the default). `STAGING` and `DEV` are for Quilt internal testing.

---

## `QuiltError`

```python
class QuiltError(Exception): ...
```

The base class for all exceptions raised by the library. Catch this to handle any library error generically:

```python
try:
    snapshot = await client.get_snapshot()
except QuiltError as e:
    print(f"Quilt error: {e}")
```

---

## `QuiltAuthError`

```python
class QuiltAuthError(QuiltError): ...
```

Raised when authentication fails. Common causes:
- Invalid or expired OTP code.
- Cognito API error during initiation or challenge response.
- Malformed or missing token in the token store.
- No `otp_callback` provided when OTP is required.

```python
try:
    await client.login(otp_callback=lambda email: input("OTP: "))
except QuiltAuthError as e:
    print(f"Auth failed: {e}")
```

---

## `QuiltConnectionError`

```python
class QuiltConnectionError(QuiltError): ...
```

Raised when the library cannot connect to the Quilt gRPC API. Typically indicates a network problem or incorrect environment selection.

---

## `QuiltNotFoundError`

```python
class QuiltNotFoundError(QuiltError): ...
```

Raised when a requested resource does not exist. For example, `get_snapshot()` raises this if the `system_id` is not found (gRPC `NOT_FOUND` status). The message includes the system ID.

---

## `__version__`

```python
__version__: str  # e.g. "0.1.0"
```

The installed package version.
