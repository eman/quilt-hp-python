# gRPC protocol concepts

## Transport metadata and auth

Every gRPC call includes:

- `authorization` (current token from token provider)
- `x-quilt-app-version`

Transport behavior is implemented in `transport.py`.

When unary RPCs return `UNAUTHENTICATED`, the interceptor can invoke refresh and retry once.

## Services used by this library

The Python implementation currently wraps these RPC surfaces:

- **HomeDatastoreService** (`quilt_hds.proto`)
  - snapshot fetch (`GetHomeDatastoreSystem`)
  - entity updates (space, indoor unit, comfort setting, schedules, location schedule execution)
- **SystemInformationService** (`quilt_services.proto`)
  - `ListSystems`
  - `GetEnergyMetrics`
- **UserService** (`quilt_services.proto`)
  - `GetLoggedInUser`
- **NotifierService** (`quilt_notifier.proto`)
  - `Subscribe` (bidirectional stream)

## Streaming model

`NotifierStream` in `services/streaming.py` handles:

- topic subscription requests (`append`/`remove`)
- async callback registration for entity-specific updates
- reconnect with backoff
- optional refresh callback on stream `UNAUTHENTICATED`

Topic values follow the `hds/<entity_type>/<entity_id>` pattern.

## Important runtime behavior

- Stream payload parsing is custom because notifier events contain nested wire payloads.
- Stream updates are partial/sparse and are merged into snapshot models by `SystemSnapshot.apply_*` methods.
