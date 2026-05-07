# Automation service/daemon playbook

## Architecture

```mermaid
flowchart LR
    BOOT[Service bootstrap] --> AUTH[QuiltClient.login()]
    AUTH --> SNAP[Initial get_snapshot()]
    SNAP --> LOOP[Automation policy loop]
    LOOP --> WRITE[set_space / set_indoor_unit / schedule APIs]
    LOOP --> OBS[metrics + logs]
    LOOP --> STREAM[Optional NotifierStream]
```

## Playbook

1. Use a single long-lived async client per account/system target.
2. Implement `TokenStore` with secure secret backend (keyring/KMS/secret manager).
3. Prime state with `get_snapshot()`; use `snapshot_ttl_s` only if your loop tolerates cached reads.
4. Apply policy decisions using typed methods (`set_space`, `set_indoor_unit`, schedule methods).
5. For near-real-time workflows, run `NotifierStream` and merge sparse updates with `SystemSnapshot.apply_*`.
6. On auth failures, attempt controlled refresh and escalate when OTP re-auth is required.

## Reliability

- Use bounded retry around writes; include idempotency checks against current snapshot.
- Keep circuit-breaker behavior around persistent upstream failures.
- Separate "read freshness" SLOs from "write success" SLOs and alert independently.
