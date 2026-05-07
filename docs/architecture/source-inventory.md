# Source-to-documentation inventory

This page maps major repository surfaces to the documentation pages that explain
them.

## Python implementation surfaces

| Surface | Source path(s) | Primary docs |
| --- | --- | --- |
| High-level client | `src/quilt_hp/client.py` | [Python API usage](../python-api/usage.md), [QuiltClient API reference](../python-api/client-reference.md), [Public API reference](../python-api/public-api-reference.md) |
| Service wrappers | `src/quilt_hp/services/hds.py`, `src/quilt_hp/services/system.py`, `src/quilt_hp/services/user.py`, `src/quilt_hp/services/streaming.py` | [Service and model reference](../python-api/services-and-models.md), [gRPC services matrix](../protocol/grpc-services-matrix.md), [streaming protocol behavior](../protocol/streaming-protocol.md) |
| Domain models | `src/quilt_hp/models/*.py` | [Service and model reference](../python-api/services-and-models.md), [HDS entities and field semantics](../protocol/hds-entities.md), [Public API reference](../python-api/public-api-reference.md) |
| Auth/token lifecycle | `src/quilt_hp/auth.py`, `src/quilt_hp/tokens.py` | [Token management reference](../python-api/token-management.md), [transport and auth behavior](../protocol/transport-auth.md) |
| gRPC transport | `src/quilt_hp/transport.py` | [transport and auth behavior](../protocol/transport-auth.md), [gRPC protocol concepts](../protocol/grpc-concepts.md) |
| CLI/TUI integration | `src/quilt_hp/cli/main.py`, `src/quilt_hp/cli/tui.py`, `src/quilt_hp/cli/settings.py`, `src/quilt_hp/cli/store.py` | [CLI automation scripts playbook](../integrations/cli-automation-playbook.md), [TUI playbook](../integrations/tui-event-driven-playbook.md) |

## Protocol contract surfaces

| Surface | Source path(s) | Primary docs |
| --- | --- | --- |
| Cleaned protobuf schemas | `proto/cleaned/quilt_hds.proto`, `proto/cleaned/quilt_services.proto`, `proto/cleaned/quilt_notifier.proto`, `proto/cleaned/quilt_system.proto`, `proto/cleaned/quilt_device_pairing.proto` | [Protobuf artifacts and regeneration](../protocol/protobuf-artifacts.md), [gRPC protocol concepts](../protocol/grpc-concepts.md), [gRPC services matrix](../protocol/grpc-services-matrix.md) |
| Generated Python stubs | `src/quilt_hp/_proto/*_pb2.py`, `src/quilt_hp/_proto/*_pb2_grpc.py` | [Protobuf artifacts and regeneration](../protocol/protobuf-artifacts.md) |

## Reference material

These sources support protocol understanding and implementation guidance:

| Surface | Source path(s) | Primary docs |
| --- | --- | --- |
| gRPC research corpus | `reference/grpc/README.md`, `reference/grpc/api_reference.md` | [gRPC protocol concepts](../protocol/grpc-concepts.md), [gRPC services matrix](../protocol/grpc-services-matrix.md) |
| REST/auth research corpus | `reference/rest/README.md`, `reference/rest/api_reference.md` | [transport and auth behavior](../protocol/transport-auth.md), [token management reference](../python-api/token-management.md) |
| Local-network research corpus | `reference/local/README.md` | [architecture and layering](layering.md) |
