# Protocol/docs update process

Keep protocol and API docs synchronized with implementation and protobuf changes.

## Update triggers

### When `src/` changes

Update:

- `docs/python-api/*` for public behavior changes.
- `docs/protocol/grpc-services-matrix.md` if wrapped RPC coverage changes.
- `docs/protocol/hds-entities.md` for entity or merge semantic changes.

If public signatures changed, regenerate:

```bash
python scripts/generate_public_api_reference.py
```

### When `proto/cleaned` changes

Update:

- `docs/protocol/protobuf-artifacts.md` for regeneration and packaging impacts.
- `docs/protocol/grpc-concepts.md` and
  `docs/protocol/grpc-services-matrix.md` for service/method additions/removals.

### When `reference/` changes

Update protocol pages that rely on those findings, but keep them framed as
integration guidance rather than reverse-engineering notes.

## Practical routine per PR

1. Identify touched source class: `src/`, `proto/cleaned`, and/or `reference/`.
2. Update matching docs in the same PR.
3. Regenerate API signatures if public APIs changed.
4. Run docs checks:
   - `python scripts/check_docs_nav.py`
   - `mkdocs build --strict`
