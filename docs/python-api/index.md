# Python API

The `quilt_hp` Python package provides an async client library for controlling Quilt mini-split HVAC systems. The entire public API is accessible through a single entry point: `QuiltClient`.

## Entry point

```python
from quilt_hp import QuiltClient, Environment
```

`QuiltClient` is the façade for everything: authentication, system discovery, space control, indoor unit control, comfort settings, schedules, energy metrics, and real-time streaming. You do not need to interact with the service classes, proto objects, or transport layer directly.

## Context manager pattern

`QuiltClient` is designed to be used as an async context manager. This ensures the gRPC channel is properly closed when you are done:

```python
async with QuiltClient("you@example.com") as client:
    await client.login(otp_callback=lambda email: input(f"OTP for {email}: "))
    spaces = await client.list_spaces()
```

If you construct `QuiltClient` without the context manager, you are responsible for closing the channel yourself (the channel is accessible at `client._channel`).

## Token persistence

By default, `QuiltClient` does not persist tokens. Each time you create a new `QuiltClient` instance you will need to supply an `otp_callback` unless you pass a `token_store`:

```python
from quilt_hp.cli.store import FileStore

store = FileStore()  # ~/.config/quilt-hp/tokens.json

async with QuiltClient("you@example.com", token_store=store) as client:
    await client.login(otp_callback=lambda email: input(f"OTP for {email}: "))
    # Future runs skip OTP if the cached token or refresh token is still valid.
```

## Service coverage

`QuiltClient` wraps four gRPC services:

- **HomeDatastoreService** — snapshot fetch, space control, IDU control, comfort settings, schedules.
- **SystemInformationService** — listing available systems, energy metrics.
- **UserService** — current user info and attributes.
- **NotifierService** — real-time streaming via `NotifierStream`.

## Documentation in this section

- [Usage patterns](usage.md) — the most common patterns with working code examples.
- [Advanced workflows](advanced-workflows.md) — custom token stores, multi-system handling, long-running daemons.
- [Public API reference](public-api-reference.md) — all publicly exported symbols from `quilt_hp`.
- [QuiltClient API reference](client-reference.md) — complete method-by-method reference.
- [Service and model reference](services-and-models.md) — lower-level service classes and all model dataclasses.
- [Token management reference](token-management.md) — `TokenStore`, `CachedTokens`, refresh hooks and policies.
- [Examples](examples.md) — complete, runnable Python scripts.
