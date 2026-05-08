# Regenerate protobuf stubs

This guide covers when and how to regenerate the Python protobuf stubs after changing a `.proto` file.

For background on why the stubs are vendored and what the script does internally, see [gRPC and protobuf](../explanation/grpc-and-protobuf.md).

---

## When to regenerate

Regenerate the stubs whenever you change a `.proto` file in `proto/cleaned/`. Regenerate the stubs for changes such as:

- Adding, removing, or renaming an RPC method
- Adding, removing, or renaming a message field
- Adding a new `.proto` file
- Changing a field type or `oneof` grouping

Do not regenerate just for comment or whitespace changes. The generated output will not change.

---

## Run the regeneration script

1. Install the required tools:

   ```bash
   pip install grpcio-tools mypy-protobuf
   ```

2. Run the script from the repository root:

   ```bash
   ./scripts/regen_protos.sh
   ```

   The script searches for the `google/protobuf/*.proto` include directory at `/opt/homebrew/include` (macOS Homebrew) and `/usr/local/include` (Linux). If your protobuf headers are elsewhere, set `PROTO_INCLUDE` before running:

   ```bash
   PROTO_INCLUDE=/usr/include ./scripts/regen_protos.sh
   ```

3. Inspect the diff in `src/quilt_hp/_proto/`:

   ```bash
   git diff src/quilt_hp/_proto/
   ```

   Verify that the changes match your proto edits and nothing unexpected changed.

---

## What the script does

The script runs `python -m grpc_tools.protoc` against all five proto files in `proto/cleaned/`, generating `*_pb2.py`, `*_pb2_grpc.py`, and `*_pb2.pyi` files. It then rewrites absolute package imports to relative imports (for example, `import quilt_hds_pb2` becomes `from . import quilt_hds_pb2`) using `sed`, so the stubs work inside the `_proto` sub-package.

For a detailed description of what the script does step by step, see [gRPC and protobuf](../explanation/grpc-and-protobuf.md).

---

## Commit the regenerated stubs

After regenerating, commit both the proto change and the generated stubs together:

```bash
git add proto/cleaned/quilt_hds.proto src/quilt_hp/_proto/
git commit -m "proto: add new SpaceSettings field for X

- Add field Y to SpaceSettings in quilt_hds.proto
- Regenerate Python stubs
- Update SpaceSettings model in models/space.py
- Update docs/reference/hds-entities.md"
```

Always include the generated files in the same commit as the proto change. Do not commit proto changes without regenerating. The CI pipeline will catch the mismatch.

---

## CI enforcement

The CI pipeline runs `./scripts/regen_protos.sh` and then checks `git diff --exit-code src/quilt_hp/_proto/` to verify that the committed stubs match the current proto definitions. If you push a proto change without regenerating, CI fails with a diff showing the expected changes.
