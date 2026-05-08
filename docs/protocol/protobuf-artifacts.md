# Protobuf artifacts and regeneration

This page explains where the proto definitions live, what the generated stubs are, and how to regenerate them when the definitions change.

## Proto source files

The Quilt API proto definitions live in `proto/cleaned/`. These are hand-cleaned reconstructions of the wire protocol, derived from analysis of the Quilt mobile applications. There are five files:

| File | Package | Content |
| --- | --- | --- |
| `quilt_hds.proto` | `core.protos.home_datastore` | All HDS entities (Space, IndoorUnit, OutdoorUnit, Controller, etc.), enums, and the `HomeDatastoreService` |
| `quilt_services.proto` | `core.protos.app` | UserService, SystemInformationService, InvitationService, PartnerService, SystemUserService, MobileAppService |
| `quilt_notifier.proto` | `core.protos.notifier` | `NotifierService.Subscribe` — the bidirectional streaming service |
| `quilt_system.proto` | `core.protos.system` | `SystemService` |
| `quilt_device_pairing.proto` | `core.protos.device_pairing` | `DevicePairingService` |

## Generated stubs

The generated Python files live in `src/quilt_hp/_proto/`:

```
src/quilt_hp/_proto/
├── __init__.py
├── quilt_hds_pb2.py          # message classes
├── quilt_hds_pb2_grpc.py     # stub and servicer classes
├── quilt_hds_pb2.pyi         # type stubs for mypy
├── quilt_services_pb2.py
├── quilt_services_pb2_grpc.py
├── quilt_services_pb2.pyi
├── quilt_notifier_pb2.py
├── quilt_notifier_pb2_grpc.py
├── quilt_notifier_pb2.pyi
├── quilt_system_pb2.py
├── quilt_system_pb2_grpc.py
├── quilt_system_pb2.pyi
├── quilt_device_pairing_pb2.py
├── quilt_device_pairing_pb2_grpc.py
└── quilt_device_pairing_pb2.pyi
```

**Do not edit these files by hand.** They are generated artifacts. Any manual edits will be overwritten the next time `regen_protos.sh` is run.

## Regenerating stubs

When you change a `.proto` file, regenerate the stubs:

```bash
./scripts/regen_protos.sh
```

The script requires:
- Python with `grpc_tools` installed: `pip install grpcio-tools`
- `mypy-protobuf` installed: `pip install mypy-protobuf`
- `protoc` include path for `google/protobuf/*.proto` (the script searches `/opt/homebrew/include` and `/usr/local/include`)

### What the script does

1. Creates `src/quilt_hp/_proto/` if it does not exist.
2. Runs `python -m grpc_tools.protoc` with three output options:
   - `--python_out` — generates `*_pb2.py` message classes.
   - `--grpc_python_out` — generates `*_pb2_grpc.py` stub and servicer classes.
   - `--mypy_out` — generates `*_pb2.pyi` type stubs.
3. Post-processes all generated `.py` files to rewrite absolute package imports to relative imports. For example, `import quilt_hds_pb2` becomes `from . import quilt_hds_pb2`. This is necessary because the generated grpc stubs use absolute package imports by default, which would not work inside the `_proto` sub-package.
4. Ensures `__init__.py` exists in the output directory.

### After regenerating

After running the script, commit the changed `*_pb2.py`, `*_pb2_grpc.py`, and `*_pb2.pyi` files along with your proto changes. A typical commit touching proto changes looks like:

```
proto: add new SpaceSettings field for X

- Add field Y to SpaceSettings in quilt_hds.proto
- Regenerate Python stubs
- Update SpaceSettings model in models/space.py
- Update docs/protocol/hds-entities.md
```

## CI enforcement

The CI pipeline runs `./scripts/regen_protos.sh` and checks `git diff --exit-code src/quilt_hp/_proto/` to verify that the committed stubs match the proto definitions. If you change a `.proto` file without regenerating, CI fails with a diff showing the expected changes.

## Import rewriting detail

The import rewriting in `regen_protos.sh` uses `sed` to replace lines like:

```python
import quilt_hds_pb2 as quilt_hds_pb2__
```

with:

```python
from . import quilt_hds_pb2 as quilt_hds_pb2__
```

This is applied to all five proto module names. The script handles both macOS (`sed -i ''`) and Linux (`sed -i`) variants automatically.

## Adding new proto files

If the Quilt API adds new services, follow this process:

1. Create the new `.proto` file in `proto/cleaned/`.
2. Add the file to the `grpc_tools.protoc` command in `regen_protos.sh`.
3. Add the import rewriting `sed` lines for the new module name.
4. Run `./scripts/regen_protos.sh`.
5. Create a service wrapper in `src/quilt_hp/services/`.
6. Expose methods on `QuiltClient` if appropriate.
7. Update `docs/protocol/grpc-services-matrix.md` and `docs/protocol/grpc-concepts.md`.
