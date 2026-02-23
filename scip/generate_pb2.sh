#!/usr/bin/env bash
# Generate scip_pb2.py from scip.proto using the grpcio-tools protoc bundled
# in the project venv. Run from the repo root:
#
#   bash scip/generate_pb2.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PYTHON="${REPO_ROOT}/.venv/bin/python"

echo "Generating scip_pb2.py ..."
"$PYTHON" -m grpc_tools.protoc \
    -I"$SCRIPT_DIR" \
    --python_out="$SCRIPT_DIR" \
    "$SCRIPT_DIR/scip.proto"

echo "Done → scip/scip_pb2.py"
