# Architecture

```mermaid
flowchart TD
    A[CLI/TUI surface] --> B[QuiltClient async facade]
    B --> C[Service layer]
    C --> C1[HomeDatastoreService]
    C --> C2[SystemInformationService]
    C --> C3[UserService]
    B --> S[NotifierStream]
    C1 --> T[Transport grpc.aio]
    C2 --> T
    C3 --> T
    S --> T
    T --> AU[Auth token refresh + metadata]
    T --> P[Vendored protobuf stubs _proto]
    T --> Q[Quilt cloud gRPC endpoints]
```

This section explains how the project is layered and how data and control flow through the system.

Scope:

- package and runtime layering
- snapshot and stream data model behavior
- high-level control/data flow

Start here:

- [Architecture and layering](layering.md)
- [Source-to-documentation inventory](source-inventory.md)
