# Protocol update process

This page describes how to keep documentation synchronized with changes to the gRPC proto definitions and the Python source code.

---

## Why synchronization matters

The docs in `docs/protocol/` and `docs/python-api/` are written from the actual source code, not auto-generated. When either the proto files or the Python implementation changes, the corresponding documentation must be updated in the same pull request. Stale docs are a maintenance hazard — they cause users to write code against an interface that no longer exists.

---

## Triggers and what to update

### When Python source (`src/`) changes

| Source change | Docs to update |
|--------------|----------------|
| New or changed public `QuiltClient` method | `docs/python-api/client-reference.md` |
| New or changed model field | `docs/python-api/services-and-models.md` |
| New or changed token protocol | `docs/python-api/token-management.md` |
| New or changed service class | `docs/python-api/services-and-models.md` |
| Changed exception type or message | `docs/python-api/public-api-reference.md` |
| New or changed HDS entity semantic | `docs/protocol/hds-entities.md` |
| Changed wrapped RPC coverage | `docs/protocol/grpc-services-matrix.md` |

### When proto files (`src/quilt_hp/proto/cleaned/`) change

Run the proto regeneration script first (see [Protobuf artifacts](../protocol/protobuf-artifacts.md)):

```bash
bash scripts/regen_protos.sh
```

Then update documentation:

| Proto change | Docs to update |
|-------------|----------------|
| New RPC method | `docs/protocol/grpc-services-matrix.md`, `docs/protocol/grpc-concepts.md` |
| Removed RPC method | Same, plus check `docs/python-api/client-reference.md` |
| New proto file / service | `docs/protocol/grpc-concepts.md`, `docs/protocol/grpc-services-matrix.md` |
| Changed message fields | `docs/protocol/hds-entities.md` or `docs/python-api/services-and-models.md` |

---

## Step-by-step: updating after a proto change

1. **Edit the cleaned proto** in `src/quilt_hp/proto/cleaned/`. Do not edit files in `src/quilt_hp/proto/` directly — they are generated.

2. **Regenerate stubs**:
   ```bash
   bash scripts/regen_protos.sh
   ```
   This regenerates `*_pb2.py`, `*_pb2_grpc.py`, and `*_pb2.pyi` stubs and rewrites their absolute imports to relative imports.

3. **Update the service wrapper** in `src/quilt_hp/services/` to call the new or changed RPC.

4. **Update `QuiltClient`** in `src/quilt_hp/client.py` if the service change is exposed publicly.

5. **Update docs** as described in the table above.

6. **Run all checks**:
   ```bash
   ruff check src/
   mypy src/
   pytest
   python3 scripts/check_docs_nav.py
   python3 -m mkdocs build --strict -q
   ```

7. **Open a PR** with source and doc changes together.

---

## Step-by-step: updating after a Python source change

1. **Make the source change** in `src/quilt_hp/`.

2. **Update tests** in `tests/`.

3. **Update documentation** for any affected public surface (see table above). Focus on:
   - Correct method signatures (including default values).
   - Updated behavioural notes.
   - New or removed exceptions.

4. **Run all checks** (same commands as above).

---

## Checking doc and nav consistency

Run the nav consistency check before every commit that touches `docs/` or `mkdocs.yml`:

```bash
python3 scripts/check_docs_nav.py
```

This script verifies that every file referenced in `mkdocs.yml` exists on disk and that no doc file exists without a nav entry. It exits non-zero on any mismatch.

---

## What the CI pipeline checks

The CI pipeline runs:

1. `ruff check src/` — linting
2. `mypy src/` — type checking
3. `pytest` — unit and integration tests
4. `python3 scripts/check_docs_nav.py` — nav integrity
5. `python3 -m mkdocs build --strict -q` — docs build with broken-link detection

A PR cannot be merged until all five pass on the CI run.

---

## Proto versioning policy

Proto files in this repository are vendored snapshots of the Quilt gRPC API. They are updated by pulling the latest `.proto` files from the upstream Quilt SDK, copying them to `src/quilt_hp/proto/cleaned/`, and running `regen_protos.sh`. The version of the API in use is tracked by the `APP_VERSION` constant in `const.py` (`"1.0.25"` as of this writing). When the upstream API version changes, update `APP_VERSION` and the proto files together.
