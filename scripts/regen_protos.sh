#!/usr/bin/env bash
# Recompile .proto files to Python stubs and vendor them into the package.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PACKAGE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROTO_SRC="$PACKAGE_DIR/proto/cleaned"
OUT_DIR="$PACKAGE_DIR/src/quilt_hp/_proto"

if [[ ! -d "$PROTO_SRC" ]]; then
    echo "Error: Proto source directory not found at $PROTO_SRC"
    echo "Expected quilt-hp-python/proto/cleaned to exist."
    exit 1
fi

mkdir -p "$OUT_DIR"

# The generators come from the dev extra; use the project's venv when the shell hasn't
# activated it, and fail clearly rather than half-generating.
if ! command -v protoc-gen-mypy >/dev/null && [[ -x "$PACKAGE_DIR/.venv/bin/protoc-gen-mypy" ]]; then
    PATH="$PACKAGE_DIR/.venv/bin:$PATH"
fi
if ! command -v protoc-gen-mypy >/dev/null || ! python -c "import grpc_tools" 2>/dev/null; then
    echo "Error: protoc-gen-mypy / grpc_tools not found. Run: uv run --extra dev $0"
    exit 1
fi

# Locate google/protobuf includes
PROTO_INCLUDE=""
if [[ -d "/opt/homebrew/include" ]]; then
    PROTO_INCLUDE="-I /opt/homebrew/include"
elif [[ -d "/usr/local/include" ]]; then
    PROTO_INCLUDE="-I /usr/local/include"
fi

python -m grpc_tools.protoc \
    -I "$PROTO_SRC" \
    $PROTO_INCLUDE \
    --python_out="$OUT_DIR" \
    --grpc_python_out="$OUT_DIR" \
    --mypy_out="$OUT_DIR" \
    "$PROTO_SRC/quilt_hds.proto" \
    "$PROTO_SRC/quilt_services.proto" \
    "$PROTO_SRC/quilt_notifier.proto" \
    "$PROTO_SRC/quilt_system.proto" \
    "$PROTO_SRC/quilt_device_pairing.proto" \
    "$PROTO_SRC/quilt_device_config.proto" \
    "$PROTO_SRC/quilt_actions.proto"

# Fix imports in generated files (.py and .pyi): protoc emits absolute imports that won't
# work inside our package. Rewrite them to relative imports.
cd "$OUT_DIR"
for f in *.py *.pyi; do
    # quilt_hds_pb2 → .quilt_hds_pb2 (relative import within _proto package)
    sed -i '' 's/^import quilt_hds_pb2/from . import quilt_hds_pb2/' "$f" 2>/dev/null || \
    sed -i  's/^import quilt_hds_pb2/from . import quilt_hds_pb2/' "$f"

    sed -i '' 's/^import quilt_services_pb2/from . import quilt_services_pb2/' "$f" 2>/dev/null || \
    sed -i  's/^import quilt_services_pb2/from . import quilt_services_pb2/' "$f"

    sed -i '' 's/^import quilt_notifier_pb2/from . import quilt_notifier_pb2/' "$f" 2>/dev/null || \
    sed -i  's/^import quilt_notifier_pb2/from . import quilt_notifier_pb2/' "$f"

    sed -i '' 's/^import quilt_system_pb2/from . import quilt_system_pb2/' "$f" 2>/dev/null || \
    sed -i  's/^import quilt_system_pb2/from . import quilt_system_pb2/' "$f"

    sed -i '' 's/^import quilt_device_pairing_pb2/from . import quilt_device_pairing_pb2/' "$f" 2>/dev/null || \
    sed -i  's/^import quilt_device_pairing_pb2/from . import quilt_device_pairing_pb2/' "$f"

    sed -i '' 's/^import quilt_device_config_pb2/from . import quilt_device_config_pb2/' "$f" 2>/dev/null || \
    sed -i  's/^import quilt_device_config_pb2/from . import quilt_device_config_pb2/' "$f"

    sed -i '' 's/^import quilt_actions_pb2/from . import quilt_actions_pb2/' "$f" 2>/dev/null || \
    sed -i  's/^import quilt_actions_pb2/from . import quilt_actions_pb2/' "$f"
done

# Ensure __init__.py exists
touch "$OUT_DIR/__init__.py"

echo "Generated stubs in $OUT_DIR:"
ls "$OUT_DIR"/*.py
