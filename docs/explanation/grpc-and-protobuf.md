# gRPC and protobuf

This page explains the gRPC design decisions, the five proto services, why the stubs are vendored, and why the library configures keepalives the way it does.

---

## Why gRPC for this API

Quilt's mobile applications (iOS and Android) communicate with the cloud backend over gRPC. The wire protocol was reconstructed from the mobile apps and documented in `proto/cleaned/`. Using gRPC lets the library speak the same protocol as the official apps, which is the most stable and complete interface available.

There are three properties of gRPC that make it particularly well-suited here:

1. **Bidirectional streaming.** The `NotifierService.Subscribe` RPC is a persistent bidirectional stream. The server pushes change events as they happen; the client manages subscriptions in the same connection. This is not easily expressible in REST.
2. **Strong typing.** Proto definitions are a contract. Adding a new field to a proto message does not break existing clients because proto3 is forward-compatible. REST APIs typically need versioned endpoints or loose JSON schemas to achieve the same stability.
3. **Efficient wire format.** Protobuf is a compact binary format. For high-frequency telemetry (temperature readings every few seconds from multiple rooms) this matters for bandwidth and parsing latency.

---

## The five proto services and their roles

The Quilt API is split across five proto files, each defining one or more services:

**`quilt_hds.proto`: `HomeDatastoreService`**
The central service. All HDS (Home Datastore) entities live here: spaces, indoor units, outdoor units, controllers, sensors, comfort settings, and schedules. This is where all HVAC control RPCs are defined. The library wraps eleven methods: `GetHomeDatastoreSystem`, `UpdateSpace`, `UpdateIndoorUnit`, `UpdateComfortSetting`, and the CRUD methods for schedule days, schedule weeks, and location (for schedule pausing).

**`quilt_services.proto`: `SystemInformationService`, `UserService`, and others**
Contains system-level queries (`ListSystems`, `GetEnergyMetrics`) and user management (`GetLoggedInUser`, `UpdateLoggedInUser`, `GetUserAttributes`, `PatchUserAttributes`). It also defines `InvitationService`, `PartnerService`, `SystemUserService`, and `MobileAppService`. Those services are in the proto files but are not currently wrapped by the library.

**`quilt_notifier.proto`: `NotifierService`**
A single RPC: `Subscribe(stream SubscribeRequest) returns (stream SubscribeResponse)`. This is the only streaming RPC in the library. The client sends subscription management messages (add/remove topics); the server sends change notifications.

**`quilt_system.proto`: `SystemService`**
System-level RPCs. Not currently wrapped by the library.

**`quilt_device_pairing.proto`: `DevicePairingService`**
Device pairing RPCs. Not currently wrapped by the library.

For the complete method matrix, see [gRPC services matrix](../reference/grpc-services-matrix.md).

---

## Why the stubs are vendored

Generated protobuf stubs (`*_pb2.py`, `*_pb2_grpc.py`, `*_pb2.pyi`) are committed to the repository rather than generated at install time. There are three reasons:

**Simpler installation.** `pip install quilt-hp-python` works in any Python environment without needing `protoc`, `grpcio-tools`, or any proto-related build dependencies. A user installing the library to write an automation script should not need to care about proto compilation.

**Reproducibility.** The exact generated code is pinned in git. Different versions of `grpcio-tools.protoc` generate subtly different code (import style, comment format, type stub content). Vendoring eliminates that variability. The code in the repo is the code that was tested.

**Auditable diffs.** When proto definitions change, the diff in the pull request shows exactly what changed in the generated code. A reviewer can see whether a new field was added to the right message, whether the import rewriting was applied correctly, and whether the Python models were updated accordingly.

The trade-off is that the generated files must be kept in sync manually via `./scripts/regen_protos.sh`. The CI pipeline enforces this: it regenerates the stubs and checks `git diff --exit-code` to verify that the committed files match the current proto definitions.

---

## The import rewriting done by the regen script

`grpcio-tools.protoc` generates gRPC stub files (`*_pb2_grpc.py`) with absolute imports:

```python
import quilt_hds_pb2 as quilt_hds_pb2__
```

This works when the generated files are placed at the top level of the Python path, but not inside a sub-package like `quilt_hp/_proto/`. Python would look for `quilt_hds_pb2` as a top-level module and fail.

The `regen_protos.sh` script post-processes all generated `.py` files with `sed` to rewrite absolute imports to relative imports:

```python
from . import quilt_hds_pb2 as quilt_hds_pb2__
```

This rewriting is applied to all five proto module names. The script handles both macOS (`sed -i ''`) and Linux (`sed -i`) `sed` variants automatically.

This rewriting is a known limitation of `grpcio-tools`. There is an open issue in the gRPC repository requesting native relative import support; until it is addressed, the `sed` post-processing is the standard approach.

---

## Keepalive settings and why long-lived connections need them

The gRPC channel is created with aggressive keepalive settings:

```python
GRPC_CHANNEL_OPTIONS = [
    ("grpc.keepalive_time_ms", 30_000),        # send keepalive ping every 30s
    ("grpc.keepalive_timeout_ms", 10_000),      # wait up to 10s for ping ack
    ("grpc.keepalive_permit_without_calls", 1), # send pings even when idle
    ("grpc.http2.max_pings_without_data", 0),   # no cap on pings without data
]
```

NAT devices and load balancers silently drop idle TCP connections after a timeout, typically 60 to 300 seconds. Without keepalives, the `NotifierStream` (which maintains a persistent connection for hours) would appear alive to the application while the underlying TCP connection had been silently dropped. The stream would stop receiving events with no error, no reconnect, and no indication that anything was wrong.

Sending a keepalive ping every 30 seconds prevents the NAT entry from timing out. `keepalive_permit_without_calls = 1` is necessary because gRPC does not send keepalives by default when no calls are in flight. The notification stream is always in flight from the client's perspective, even when it is not sending messages. Setting `http2.max_pings_without_data = 0` removes the gRPC default cap that would otherwise stop sending pings after a few unanswered attempts.

These settings are defined in `const.py` as `GRPC_CHANNEL_OPTIONS` and are applied to every channel created by `create_channel()` in `transport.py`.
