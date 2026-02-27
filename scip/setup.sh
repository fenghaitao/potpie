#!/usr/bin/env bash
# scip/setup.sh — set up everything needed to generate and explore a SCIP index.
#
# Run from the repo root:
#   bash scip/setup.sh
#
# What this does:
#   1. Checks prerequisites (Node.js, npm, uv / venv Python)
#   2. Installs scip-python (Node.js CLI) globally via npm
#   3. Installs grpcio-tools into the project venv via uv
#   4. Generates scip/scip_pb2.py from scip.proto
#   5. Generates index.scip for the full app/ directory
#   6. Runs read_scip.py to verify the index
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="${REPO_ROOT}/.venv/bin/python"

cd "$REPO_ROOT"

# ── helpers ──────────────────────────────────────────────────────────────────

info()  { echo "[setup] $*"; }
warn()  { echo "[setup] WARNING: $*" >&2; }
die()   { echo "[setup] ERROR: $*" >&2; exit 1; }

require_cmd() {
    command -v "$1" &>/dev/null || die "'$1' not found. $2"
}

# ── 1. Prerequisites ─────────────────────────────────────────────────────────

info "Checking prerequisites..."

require_cmd node  "Install Node.js from https://nodejs.org (v16+ required)."
require_cmd npm   "npm should ship with Node.js."

NODE_MAJOR=$(node --version | sed 's/v\([0-9]*\).*/\1/')
if [ "$NODE_MAJOR" -lt 16 ]; then
    die "Node.js v16+ required (found $(node --version))."
fi
info "Node.js $(node --version) — OK"

# Prefer uv, fall back to the venv python directly
if command -v uv &>/dev/null; then
    INSTALLER="uv pip install"
    info "uv found at $(command -v uv)"
elif [ -x "$VENV_PYTHON" ]; then
    INSTALLER="$VENV_PYTHON -m pip install"
    warn "uv not found; falling back to pip inside .venv"
else
    die "Neither 'uv' nor '.venv/bin/python' found. Create the venv first (e.g. 'uv venv' or 'python -m venv .venv')."
fi

if [ ! -x "$VENV_PYTHON" ]; then
    die ".venv/bin/python not found. Run 'uv venv' or 'python -m venv .venv' first."
fi
info "Python $($VENV_PYTHON --version) — OK"

# ── 2. Install scip-python ────────────────────────────────────────────────────

if command -v scip-python &>/dev/null; then
    info "scip-python already installed: $(scip-python --version 2>&1 | head -1)"
else
    info "Installing @sourcegraph/scip-python via npm..."
    npm install -g @sourcegraph/scip-python
    info "scip-python installed: $(scip-python --version 2>&1 | head -1)"
fi

# ── 3. Install grpcio-tools into the venv ────────────────────────────────────

info "Installing grpcio-tools into the venv..."
$INSTALLER grpcio-tools
info "grpcio-tools — OK"

# ── 4. Generate scip_pb2.py ───────────────────────────────────────────────────

info "Generating scip/scip_pb2.py from scip.proto..."
bash "$SCRIPT_DIR/generate_pb2.sh"
info "scip/scip_pb2.py — OK"

# ── 5. Generate index.scip ────────────────────────────────────────────────────

info "Indexing app/ with scip-python (this takes ~2-3 min for the full repo)..."
scip-python index app --project-name potpie --output index.scip
INDEX_SIZE=$(du -sh index.scip 2>/dev/null | cut -f1)
info "index.scip generated (${INDEX_SIZE})"

# ── 6. Verify with read_scip.py ───────────────────────────────────────────────

info "Running read_scip.py to verify the index..."
echo ""
"$VENV_PYTHON" "$SCRIPT_DIR/read_scip.py" index.scip
echo ""
info "Setup complete."
info ""
info "To re-index after code changes:"
info "  scip-python index app --project-name potpie --output index.scip"
info ""
info "To explore the index:"
info "  .venv/bin/python scip/read_scip.py index.scip"
