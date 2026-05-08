# Advanced workflows

This page covers patterns that go beyond the basics: custom token stores, refresh hooks, multi-system handling, long-running daemons, and combining snapshot with stream.

## Custom token stores

The `TokenStore` protocol has two async methods: `load(email) -> CachedTokens | None` and `save(email, tokens) -> None`. Implement it to integrate with any backend:

```python
from quilt_hp.tokens import TokenStore, CachedTokens
import json

class RedisTokenStore:
    def __init__(self, redis_client: "aioredis.Redis") -> None:
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
            ex=86400,  # TTL: 24 hours
        )
```

Use it exactly like `FileStore`:

```python
store = RedisTokenStore(redis_client)
async with QuiltClient("you@example.com", token_store=store) as client:
    await client.login(otp_callback=...)
```

If you have an existing synchronous token store, implement `LegacyTokenStore` instead (synchronous `load` and `save` methods). The library wraps synchronous stores with `asyncio.to_thread` automatically.

## Token refresh hooks

`TokenRefreshHooks` lets you observe refresh events — useful for logging, monitoring, or updating secondary caches:

```python
from quilt_hp.tokens import TokenRefreshHooks, TokenRefreshContext, CachedTokens
import logging

logger = logging.getLogger(__name__)

class LoggingRefreshHooks:
    async def on_refresh_start(self, context: TokenRefreshContext) -> None:
        logger.info("Token refresh starting: reason=%s source=%s", context.reason, context.source)

    async def on_refresh_success(self, context: TokenRefreshContext, tokens: CachedTokens) -> None:
        logger.info("Token refreshed successfully. Expires at %s", tokens.expires_at)

    async def on_refresh_failure(self, context: TokenRefreshContext, error: Exception) -> None:
        logger.error("Token refresh failed: %s", error)
```

```python
client = QuiltClient(
    "you@example.com",
    token_store=store,
    token_refresh_hooks=LoggingRefreshHooks(),
)
```

## Token refresh policy

`TokenRefreshPolicy` lets you decide what happens when a silent token refresh fails. The default is to fall back to the OTP login flow. Override this to raise immediately instead:

```python
from quilt_hp.tokens import TokenRefreshPolicy, TokenRefreshContext, RefreshFailureAction

class RaiseOnRefreshFailure:
    def on_refresh_failure(
        self, context: TokenRefreshContext, error: Exception
    ) -> RefreshFailureAction:
        # Raise immediately instead of prompting for OTP
        return RefreshFailureAction.RAISE
```

```python
client = QuiltClient(
    "you@example.com",
    token_store=store,
    token_refresh_policy=RaiseOnRefreshFailure(),
)
```

This is useful in daemon contexts where there is no way to present an OTP prompt.

## Multi-system accounts

For accounts with multiple homes, list systems first and then create a separate `QuiltClient` for each:

```python
# Use a throwaway client to list systems (needs auth)
async with QuiltClient("you@example.com", token_store=store) as client:
    await client.login()
    systems = await client.list_systems()

# Now create per-system clients
for system in systems:
    async with QuiltClient("you@example.com", home=system.name, token_store=store) as client:
        await client.login()
        snapshot = await client.get_snapshot()
        print(f"{system.name}: {len(snapshot.rooms)} rooms")
```

Or use `get_snapshot(system_id=...)` to query a specific system from a single client:

```python
async with QuiltClient("you@example.com", token_store=store) as client:
    await client.login()
    systems = await client.list_systems()
    for s in systems:
        snapshot = await client.get_snapshot(system_id=s.id)
        print(f"{s.name}: {len(snapshot.rooms)} rooms")
```

Note that `get_snapshot(system_id=...)` bypasses and does not populate the snapshot cache.

## Using the transport layer directly

For advanced use cases, you can create the gRPC channel directly without `QuiltClient`:

```python
from quilt_hp.transport import create_channel
from quilt_hp.const import Environment

token = "your-jwt-token"
channel = create_channel(
    token_provider=lambda: token,
    environment=Environment.PROD,
)

# Use the channel directly with generated stubs
from quilt_hp._proto import quilt_hds_pb2_grpc as hds_grpc
stub = hds_grpc.HomeDatastoreServiceStub(channel)
```

This is useful when integrating the library into a framework that manages its own connection pool.

## Snapshot cache for read-heavy integrations

Set `snapshot_ttl_s` to reduce network calls in polling-heavy integrations:

```python
# Cache snapshots for 30 seconds
client = QuiltClient("you@example.com", snapshot_ttl_s=30.0, token_store=store)
```

After a write operation, invalidate the cache so the next read fetches fresh data:

```python
await client.set_space(room, mode=HVACMode.HEAT)
client.invalidate_snapshot()
```

## Combining snapshot and stream

The recommended pattern for a live integration is to fetch an initial snapshot and then apply stream updates:

```python
import asyncio
from quilt_hp import QuiltClient
from quilt_hp.cli.store import FileStore
from quilt_hp.models.space import Space
from quilt_hp.models.indoor_unit import IndoorUnit

store = FileStore()

async def main() -> None:
    async with QuiltClient("you@example.com", token_store=store) as client:
        await client.login()

        # Get the full initial state
        snapshot = await client.get_snapshot()
        print(f"Loaded {len(snapshot.rooms)} rooms, {len(snapshot.indoor_units)} IDUs")

        def on_space(space: Space) -> None:
            # Merge sparse diff into snapshot; enriches comfort setting type
            merged = snapshot.apply_space(space)
            print(f"Space update: {merged.name} → {merged.state.ambient_temperature_c:.1f}°C")

        def on_idu(idu: IndoorUnit) -> None:
            merged = snapshot.apply_indoor_unit(idu)
            print(f"IDU update: {merged.settings.name}, online={merged.is_online}")

        async with client.stream(snapshot.stream_topics()) as stream:
            stream.on_space_update(on_space)
            stream.on_indoor_unit_update(on_idu)
            stream.on_error(lambda e: print(f"Fatal stream error: {e}"))
            # Block here; stream runs in background task
            await asyncio.Event().wait()  # run forever until cancelled

asyncio.run(main())
```

## Long-running daemon with reconnect

For a production daemon that must stay running indefinitely:

```python
import asyncio
import signal
import logging
from quilt_hp import QuiltClient
from quilt_hp.cli.store import FileStore

logger = logging.getLogger(__name__)

async def run_daemon() -> None:
    store = FileStore()
    shutdown = asyncio.Event()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, shutdown.set)
    loop.add_signal_handler(signal.SIGINT, shutdown.set)

    async with QuiltClient(
        "you@example.com",
        token_store=store,
        snapshot_ttl_s=60.0,
    ) as client:
        # Silent login — OTP only required on first run when no token is cached
        await client.login()
        snapshot = await client.get_snapshot()

        def on_space(space) -> None:
            snapshot.apply_space(space)
            logger.info("Space %s updated", space.name)

        # Unlimited reconnects, 1s initial backoff doubling to 60s cap
        stream = client.stream(
            snapshot.stream_topics(),
            max_reconnects=-1,
            reconnect_delay_s=1.0,
        )
        stream.on_space_update(on_space)
        stream.on_error(lambda e: logger.error("Stream fatal: %s", e))

        async with stream:
            await shutdown.wait()
            logger.info("Shutdown signal received, stopping.")

asyncio.run(run_daemon())
```

The stream reconnects automatically with exponential back-off (1s → 2s → 4s → ... → 60s cap). Token refresh happens transparently when the stream gets `UNAUTHENTICATED`.

## Pausing and resuming schedules

```python
# Pause all schedules for the primary location
await client.set_schedule_execution(paused=True)

# Resume
await client.set_schedule_execution(paused=False)
```

This is a global switch — it pauses all schedule weeks across all spaces in the system.
