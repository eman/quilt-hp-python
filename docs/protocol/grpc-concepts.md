# gRPC protocol concepts

This page provides an overview of the five protobuf services defined for the Quilt API, the difference between unary and streaming RPCs, and how the library's gRPC configuration decisions were made.

## The five proto services

The Quilt API is split across five proto files, each defining one or more services. The library currently wraps four of them.

### HomeDatastoreService (`quilt_hds.proto`)

The central service. Manages all HDS (Home Datastore) entities — spaces, indoor units, outdoor units, controllers, sensors, comfort settings, and schedules. This is where all HVAC control RPCs live.

The library wraps:
- `GetHomeDatastoreSystem` — unary, returns the full system snapshot.
- `UpdateSpace` — unary, updates space controls or settings.
- `UpdateIndoorUnit` — unary, updates IDU controls or settings.
- `UpdateComfortSetting` — unary, updates a comfort preset.
- `CreateScheduleDay`, `UpdateScheduleDay`, `DeleteScheduleDay` — unary CRUD for schedule day programs.
- `CreateScheduleWeek`, `UpdateScheduleWeek`, `DeleteScheduleWeek` — unary CRUD for schedule weeks.
- `UpdateLocation` — unary, used to pause/resume all schedules.

### SystemInformationService (`quilt_services.proto`)

Provides system-level queries:
- `ListSystems` — unary, returns all systems the user has access to.
- `GetEnergyMetrics` — unary, returns hourly energy data for a time range.
- `SetAddress` — unary, sets the system address (not currently wrapped).

### UserService (`quilt_services.proto`)

Manages the authenticated user's profile:
- `GetLoggedInUser` — unary, returns the current user.
- `UpdateLoggedInUser` — unary, updates name and phone.
- `GetUserAttributes` — unary, returns user type attributes.
- `PatchUserAttributes` — unary, updates user type.

### NotifierService (`quilt_notifier.proto`)

The streaming notification service:
- `Subscribe` — **bidirectional streaming**. The client streams `SubscribeRequest` messages to manage subscriptions; the server streams `SubscribeResponse` messages containing change notifications. This is the only streaming RPC in the library.

### DevicePairingService (`quilt_device_pairing.proto`)

Device pairing RPCs. This service is defined in the proto files but **not currently wrapped** by the library. It handles pairing new Quilt devices to a system.

## Unary RPCs vs. bidirectional streaming

All control and query RPCs are **unary**: the client sends one request message and receives one response message. This is the standard request/response pattern. The gRPC async Python API treats these as `await stub.MethodName(request)` calls.

`NotifierService.Subscribe` is **bidirectional streaming**. Both client and server send a stream of messages independently. The Python gRPC API exposes this as an async iterator: you send requests by putting them on a queue that feeds the outbound iterator, and you receive responses by iterating the returned stream object. `NotifierStream` encapsulates this complexity.

## Keepalive configuration

The library configures the gRPC channel with aggressive keepalive settings to maintain long-lived connections through NAT devices and load balancers:

```python
GRPC_CHANNEL_OPTIONS = [
    ("grpc.keepalive_time_ms", 30_000),       # send keepalive ping every 30s
    ("grpc.keepalive_timeout_ms", 10_000),     # wait up to 10s for ping ack
    ("grpc.keepalive_permit_without_calls", 1), # send pings even when idle
    ("grpc.http2.max_pings_without_data", 0),  # no cap on pings without data
]
```

These settings are particularly important for the `NotifierStream` which maintains a persistent connection for minutes or hours. Without keepalives, a NAT or firewall may silently drop the connection, causing the stream to appear alive while actually being dead.

## Why stubs are vendored

Generated protobuf stubs (`*_pb2.py`, `*_pb2_grpc.py`) are committed to the repository rather than generated at install time. This decision has three benefits:

1. **Simpler installation** — users `pip install quilt-hp-python` without needing `protoc`, `grpc_tools`, or any proto-related build dependencies.
2. **Reproducibility** — the exact generated code is pinned in git. Different versions of `grpc_tools.protoc` generate subtly different code; vendoring eliminates that variability.
3. **Auditable diffs** — when proto definitions change, the diff in the PR shows exactly what changed in the generated code, making review easier.

The trade-off is that the generated files must be kept in sync manually via `./scripts/regen_protos.sh`. See [Protobuf artifacts and regeneration](protobuf-artifacts.md) for the workflow.

## gRPC package choices

The library uses `grpc.aio` (the asyncio-native gRPC API) rather than the synchronous `grpc` API or a thread-pool bridge. This gives true async I/O without threads for unary calls and native async iteration for streaming. `grpc.aio` is stable as of `grpcio >= 1.32` and is the recommended approach for async Python applications.
