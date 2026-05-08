# Protocol

quilt-hp-python communicates with the Quilt cloud over gRPC on TLS. The production endpoint is `api.prod.quilt.cloud:443`. All API calls go through this single address — there is no separate REST API used by the library (though Cognito authentication is handled through the AWS SDK which makes HTTPS calls to `cognito-idp.us-west-2.amazonaws.com`).

## Why gRPC

Quilt's mobile applications (iOS and Android) communicate with the cloud backend over gRPC. The wire protocol was reconstructed from the mobile apps and documented in `proto/cleaned/`. Using gRPC rather than a hypothetical REST API means the library speaks the same protocol as the official apps, which is the most stable and feature-complete interface available.

## Proto stubs are vendored

The Python protobuf stubs in `src/quilt_hp/_proto/` are committed to the repository rather than generated at install time. Vendoring means:

- The package installs and works without `protoc` or `grpc_tools` in the user's environment.
- The generated code is pinned — new proto tool versions won't silently change behaviour.
- CI can verify the stubs are up-to-date by regenerating them and checking for diffs.

When the proto definitions change, run `./scripts/regen_protos.sh` to regenerate the stubs. See [Protobuf artifacts and regeneration](protobuf-artifacts.md) for details.

## Section contents

- [Transport and auth behavior](transport-auth.md) — TLS channel setup, `_AuthInterceptor`, Cognito OTP and refresh-token flows, `UNAUTHENTICATED` retry, sequence diagrams.
- [Streaming protocol behavior](streaming-protocol.md) — `NotifierService.Subscribe` bidirectional stream, topic format, wire format parsing, reconnect with back-off.
- [gRPC protocol concepts](grpc-concepts.md) — the five proto services, unary vs. streaming RPCs, keepalive configuration.
- [Protobuf artifacts and regeneration](protobuf-artifacts.md) — how to regenerate stubs, what the script does, CI enforcement.
- [gRPC services and method matrix](grpc-services-matrix.md) — table of every RPC method, request/response types, and what the library does with each.
- [HDS entities and field semantics](hds-entities.md) — Space, IndoorUnit, ComfortSetting, ScheduleDay/Week, and their important behavioural semantics.
