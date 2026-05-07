# Python API usage (async patterns)

For parameter-level details and edge-case behavior, use:

- [QuiltClient API reference](client-reference.md)
- [Service and model reference](services-and-models.md)
- [Token management reference](token-management.md)
- [Advanced workflows](advanced-workflows.md)
- [Examples](examples.md)


## Core client lifecycle

`QuiltClient` is async and should normally be used as an async context manager:

```python
import asyncio
from quilt_hp import QuiltClient

async def main() -> None:
    async with QuiltClient("user@example.com") as client:
        await client.login(otp_callback=lambda email: input(f"OTP for {email}: "))
        rooms = await client.list_spaces()
        print([room.name for room in rooms])

asyncio.run(main())
```

## Auth patterns

- `login()` uses cached/refresh tokens when available.
- OTP callback is only required when no valid cached login path exists.
- Token persistence is pluggable via `token_store`.

## Snapshot access patterns

- `get_snapshot()` fetches full state.
- `snapshot_ttl_s` can cache default snapshot reads.
- `invalidate_snapshot()` clears cache explicitly.

## Control/update patterns

`QuiltClient` exposes focused async methods:

- space controls/settings
- indoor unit controls/settings
- comfort settings
- schedules
- location schedule execution
- energy queries

Most update methods accept either object instances or IDs.

## Streaming patterns

Background/context-managed:

```python
async with client.stream(topics) as stream:
    stream.on_space_update(lambda space: print(space.name))
    await asyncio.sleep(60)
```

Blocking mode:

```python
stream = client.stream(topics)
stream.on_space_update(handle_space)
await stream.run_forever()
```

Use `on_error(...)` to observe fatal stream failures in long-running hosts.
