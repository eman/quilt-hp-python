#!/usr/bin/env bash
# Recompile .proto files to Python stubs and vendor them into the package.
# Run from the quilt-hp-python directory.
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
    "$PROTO_SRC/quilt_device_pairing.proto"

# Fix imports in generated files: grpc stubs use absolute imports that won't
# work inside our package. Rewrite them to relative imports.
cd "$OUT_DIR"
for f in *.py; do
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
done

# Ensure __init__.py exists
touch "$OUT_DIR/__init__.py"

echo "Generated stubs in $OUT_DIR:"
ls "$OUT_DIR"/*.py
