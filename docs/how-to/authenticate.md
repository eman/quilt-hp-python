# Authenticate and manage tokens

This page covers authentication patterns for the `quilt_hp` library. For background on why the token resolution works this way, see [Authentication and token lifecycle](../explanation/authentication.md).

---

## Perform a first-time OTP login

To authenticate with a fresh account (no cached tokens):

1. Import `QuiltClient` and instantiate it with your email:

   ```python
   from quilt_hp import QuiltClient

   async with QuiltClient("you@example.com") as client:
       await client.login(otp_callback=lambda email: input(f"OTP for {email}: "))
   ```

2. Run the script. Quilt sends a one-time password to your email address.

3. Type the OTP at the prompt. Authentication succeeds and a Cognito session is established.

The `otp_callback` can be async:

```python
async def prompt_otp(email: str) -> str:
    return input(f"Enter OTP for {email}: ")

await client.login(otp_callback=prompt_otp)
```

---

## Persist tokens across processes with FileStore

To avoid the OTP prompt on every run:

1. Import `FileStore` and pass it as `token_store`:

   ```python
   from quilt_hp import QuiltClient
   from quilt_hp.cli.store import FileStore

   store = FileStore()  # saves to ~/.config/quilt-hp/tokens.json

   async with QuiltClient("you@example.com", token_store=store) as client:
       await client.login(otp_callback=lambda email: input(f"OTP for {email}: "))
       # Tokens are now saved; next run will not prompt
   ```

2. On subsequent runs, call `login()` with the same store. If the cached access token is still valid it is reused immediately. If it is expired but the refresh token is valid, a silent refresh is performed — no OTP required.

3. To clear cached tokens:

   ```python
   store.clear_tokens("you@example.com")
   ```

---

## Implement a custom token store (Redis example)

To integrate with a custom backend:

1. Implement the `TokenStore` protocol with `async load` and `async save` methods:

   ```python
   from quilt_hp.tokens import TokenStore, CachedTokens
   import json

   class RedisTokenStore:
       def __init__(self, redis_client) -> None:
           self._redis = redis_client

       async def load(self, email: str) -> CachedTokens | None:
           raw = await self._redis.get(f"quilt_token:{email}")
           if raw is None:
               return None
           data = json.loads(raw)
           return CachedTokens(
               id_token=data["id_token"],
               refresh_token=data["refresh_token"],
               expires_at=data["expires_at"],
           )

       async def save(self, email: str, tokens: CachedTokens) -> None:
           data = {
               "id_token": tokens.id_token,
               "refresh_token": tokens.refresh_token,
               "expires_at": tokens.expires_at,
           }
           await self._redis.set(
               f"quilt_token:{email}",
               json.dumps(data),
               ex=86400,
           )
   ```

2. Pass the store to `QuiltClient`:

   ```python
   store = RedisTokenStore(redis_client)
   async with QuiltClient("you@example.com", token_store=store) as client:
       await client.login(otp_callback=...)
   ```

For a synchronous store (e.g., wrapping a blocking database call), implement `load` and `save` as regular (non-async) methods. The library wraps synchronous stores with `asyncio.to_thread` automatically.

For the complete `TokenStore` and `LegacyTokenStore` protocol definitions, see [Token management reference](../reference/token-management.md).

---

## Handle token refresh failures in a daemon

To prevent a daemon from hanging on an OTP prompt it cannot display:

1. Implement `TokenRefreshPolicy` to return `RefreshFailureAction.RAISE` on failure:

   ```python
   from quilt_hp.tokens import TokenRefreshPolicy, TokenRefreshContext, RefreshFailureAction
   import logging

   logger = logging.getLogger(__name__)

   class DaemonRefreshPolicy:
       def on_refresh_failure(
           self, context: TokenRefreshContext, error: Exception
       ) -> RefreshFailureAction:
           logger.error(
               "Token refresh failed (source=%s attempt=%d): %s",
               context.source, context.attempt, error,
           )
           return RefreshFailureAction.RAISE
   ```

2. Pass it to `QuiltClient`:

   ```python
   async with QuiltClient(
       "you@example.com",
       token_store=store,
       token_refresh_policy=DaemonRefreshPolicy(),
   ) as client:
       await client.login()
       ...
   ```

With `RAISE`, a refresh failure propagates as `QuiltAuthError` and exits the `async with` block. A process supervisor (systemd, Docker restart policy) then restarts the daemon, which retries the OTP flow from scratch if the refresh token itself has expired.

---

## Use token refresh lifecycle hooks for logging

To observe token refresh events (for logging or metrics):

1. Implement `TokenRefreshHooks`:

   ```python
   from quilt_hp.tokens import TokenRefreshHooks, TokenRefreshContext, CachedTokens
   import logging

   logger = logging.getLogger(__name__)

   class LoggingRefreshHooks:
       async def on_refresh_start(self, context: TokenRefreshContext) -> None:
           logger.info(
               "Token refresh starting: reason=%s source=%s",
               context.reason, context.source,
           )

       async def on_refresh_success(self, context: TokenRefreshContext, tokens: CachedTokens) -> None:
           logger.info("Token refreshed. Expires at %s", tokens.expires_at)

       async def on_refresh_failure(self, context: TokenRefreshContext, error: Exception) -> None:
           logger.error("Token refresh failed: %s", error)
   ```

2. Pass it to `QuiltClient`:

   ```python
   client = QuiltClient(
       "you@example.com",
       token_store=store,
       token_refresh_hooks=LoggingRefreshHooks(),
   )
   ```

Hooks are called in addition to (not instead of) the refresh policy. If a hook raises, the exception propagates — keep hooks lightweight and non-raising.

For the complete hook and policy protocol definitions, see [Token management reference](../reference/token-management.md).
