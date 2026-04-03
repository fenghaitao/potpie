#!/bin/bash
set -e

# Run from project root
SINGULARITY_COMPOSE="$(cd "$(dirname "$0")" && pwd)/singularity-compose/.venv/bin/singularity-compose"
cd "$(dirname "$0")/.."

# Copy .env templates if .env files don't exist
[ -f .env ] || cp .env.template .env
[ -f potpie-ui/.env ] || cp potpie-ui/.env.template potpie-ui/.env

source .env

# Set up Service Account Credentials
export GOOGLE_APPLICATION_CREDENTIALS="./service-account.json"

# Check if the credentials file exists — only warn in production mode.
# In developmentMode GCP credentials are not required.
if [ ! -f "$GOOGLE_APPLICATION_CREDENTIALS" ] && [ "${isDevelopmentMode:-disabled}" != "enabled" ]; then
    echo "Warning: Service Account Credentials file not found at $GOOGLE_APPLICATION_CREDENTIALS"
    echo "Please ensure the service-account.json file is in the current directory if you are working outside developmentMode"
fi

# ── Per-user-per-machine port management ─────────────────────────────────────
# Multiple users may share the same machine, and the same user may VNC into
# multiple machines from a shared NFS home.  Session files are keyed by
# "<user>@<hostname>" so each (user, machine) pair gets its own independent
# set of ports while remaining isolated from other combinations.
#
# Behaviour on start:
#   - Same user, same machine, services already healthy → reuse, skip startup.
#   - Same user, same machine, services dead            → clean up, start fresh.
#   - Same user, different machine                      → independent session.
#
# Session state is managed exclusively by the Discovery Server.
# Its location is recorded in .potpie-sessions/<user>@<host>.discovery.

POTPIE_USER="${USER:-$(id -un)}"
POTPIE_HOST="$(hostname -s 2>/dev/null || hostname)"
SESSION_KEY="${POTPIE_USER}@${POTPIE_HOST}"
SESSION_DIR="${PWD}/.potpie-sessions"
DISCOVERY_FILE="${SESSION_DIR}/${SESSION_KEY}.discovery"
mkdir -p "$SESSION_DIR"

# Parse flags.  --force bypasses the cross-machine conflict guard.
POTPIE_FORCE=0
for _arg in "$@"; do [ "$_arg" = "--force" ] && POTPIE_FORCE=1; done

# ── Cross-machine conflict detection ─────────────────────────────────────────
# .potpie-sessions/ lives inside the repo on shared NFS.  If another
# <user>@<otherhost>.discovery file exists it means this user started the
# backend from this same repo path on a DIFFERENT machine — a conflict because
# all machines share singularity/potpie-data/ (neo4j store_lock, etc.).
#
# Without --force: abort with instructions.
# With    --force: delete the stale discovery file(s) and data locks.
CROSS_MACHINE_DISCOVERYS=()
for _cdf in "${SESSION_DIR}/${POTPIE_USER}@"*.discovery; do
    [ -f "$_cdf" ] || continue
    [ "$_cdf" = "$DISCOVERY_FILE" ] && continue
    CROSS_MACHINE_DISCOVERYS+=("$_cdf")
done

if [ "${#CROSS_MACHINE_DISCOVERYS[@]}" -gt 0 ]; then
    _other_hosts=$(python3 -c "
import json, sys, os
hosts = []
for p in sys.argv[1:]:
    # discovery file is named <user>@<host>.discovery
    base = os.path.basename(p)
    hosts.append(base.split('@', 1)[-1].replace('.discovery', '') if '@' in base else p)
print(', '.join(hosts))
" "${CROSS_MACHINE_DISCOVERYS[@]}" 2>/dev/null || printf '%s ' "${CROSS_MACHINE_DISCOVERYS[@]}")

    if [ "$POTPIE_FORCE" -eq 0 ]; then
        echo ""
        echo "ERROR: Backend services for '${POTPIE_USER}' appear to be"
        echo "       running from this repo on another machine: ${_other_hosts}"
        echo ""
        echo "The shared data directory (singularity/potpie-data/) may be locked"
        echo "by neo4j / postgres on that machine.  Options:"
        echo ""
        echo "  1. SSH to the other machine and stop services there first:"
        echo "       bash singularity/stop.sh"
        echo ""
        echo "  2. Force-start on THIS machine (clears stale locks from dead processes):"
        echo "       bash singularity/start.sh --force"
        echo ""
        exit 1
    fi

    echo "--force: removing stale cross-machine discovery file(s) and data locks..."
    for _cdf in "${CROSS_MACHINE_DISCOVERYS[@]}"; do
        # Best-effort: ask that machine's Discovery Server to clean up
        _cdport=$(python3 -c "import json; print(json.load(open('$_cdf'))['port'])" 2>/dev/null || true)
        [ -n "$_cdport" ] && curl -sf -X DELETE \
            "http://127.0.0.1:${_cdport}/session/${SESSION_KEY}" >/dev/null 2>&1 || true
        rm -f "$_cdf"
        echo "  removed cross-machine discovery file: $_cdf"
    done
    find singularity/potpie-data/neo4j/data -name "store_lock" -delete 2>/dev/null || true
    echo "  neo4j store_lock(s) cleared."
fi

# Probe whether a TCP port is accepting connections on localhost.
_port_open() { (echo >/dev/tcp/127.0.0.1/$1) >/dev/null 2>&1; }

# ── Discovery Server bootstrap ────────────────────────────────────────────────
# The Discovery Server is a lightweight FastAPI process that owns port
# allocation and session lifecycle.  One instance runs per user per machine.
#
# It writes .potpie-sessions/<user>@<host>.discovery: {"port": N, "pid": M}
# All other scripts find it via that file.

# Check if the Discovery Server for this user@machine is alive.
_discovery_running() {
    local dfile="$1"
    [ -f "$dfile" ] || return 1
    local port pid
    port=$(python3 -c "import json; print(json.load(open('$dfile'))['port'])" 2>/dev/null) || return 1
    pid=$(python3  -c "import json; print(json.load(open('$dfile'))['pid'])"  2>/dev/null) || return 1
    kill -0 "$pid" 2>/dev/null || return 1   # PID must exist
    curl -sf "http://127.0.0.1:${port}/health" >/dev/null 2>&1 || return 1
    echo "$port"
}

DISCOVERY_TMP="${SESSION_DIR}/${SESSION_KEY}.discovery.tmp"

if DISCOVERY_PORT=$(_discovery_running "$DISCOVERY_FILE"); then
    echo "Discovery Server already running on port ${DISCOVERY_PORT}."
else
    echo "Starting Discovery Server..."
    rm -f "$DISCOVERY_TMP"
    NEO4J_DATA_PATH="${PWD}/singularity/potpie-data/neo4j/data"
    PYTHONPATH="${PWD}" uv run python -m potpie.discovery \
        --port-file "$DISCOVERY_TMP" \
        --neo4j-data "$NEO4J_DATA_PATH" &
    DISCO_PID=$!

    # Wait up to 10 s for the port file to appear (server writes it at bind time).
    for _i in $(seq 1 20); do
        [ -f "$DISCOVERY_TMP" ] && break
        sleep 0.5
    done
    if [ ! -f "$DISCOVERY_TMP" ]; then
        echo "ERROR: Discovery Server did not start within 10 s."
        exit 1
    fi
    DISCOVERY_PORT=$(cat "$DISCOVERY_TMP")
    rm -f "$DISCOVERY_TMP"

    # Persist discovery metadata so other scripts and CLI can find the server.
    python3 -c "
import json
json.dump({'port': ${DISCOVERY_PORT}, 'pid': ${DISCO_PID}}, open('${DISCOVERY_FILE}', 'w'))
"
    # Wait for the HTTP server to accept connections (max 10 s).
    for _i in $(seq 1 20); do
        curl -sf "http://127.0.0.1:${DISCOVERY_PORT}/health" >/dev/null 2>&1 && break
        sleep 0.5
    done
    echo "Discovery Server started on port ${DISCOVERY_PORT}."
fi

# ── Session creation via Discovery API ───────────────────────────────────────
# POST /session returns a new session (or reuses an existing healthy one) with
# dynamically allocated ports for all backend services.

echo "Requesting session from Discovery Server..."
SESSION_RESPONSE=$(curl -sf -X POST "http://127.0.0.1:${DISCOVERY_PORT}/session" \
    -H "Content-Type: application/json" \
    -d "{\"session_id\": \"${SESSION_KEY}\", \"user\": \"${POTPIE_USER}\", \"host\": \"${POTPIE_HOST}\"}" \
    2>/dev/null) || {
    echo "ERROR: Failed to create session via Discovery Server."
    exit 1
}

# Extract allocated ports from the JSON response.
POSTGRES_PORT=$(python3   -c "import json,sys; d=json.loads(sys.argv[1]); print(d['ports']['postgres'])"   "$SESSION_RESPONSE")
REDIS_PORT=$(python3      -c "import json,sys; d=json.loads(sys.argv[1]); print(d['ports']['redis'])"      "$SESSION_RESPONSE")
SNG_NEO4J_BOLT_PORT=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d['ports']['neo4j_bolt'])" "$SESSION_RESPONSE")
SNG_NEO4J_HTTP_PORT=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d['ports']['neo4j_http'])" "$SESSION_RESPONSE")
API_PORT=$(python3        -c "import json,sys; d=json.loads(sys.argv[1]); print(d['ports']['api'])"        "$SESSION_RESPONSE")
POSTGRES_SERVER=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d['postgres_server'])"    "$SESSION_RESPONSE")
NEO4J_URI=$(python3       -c "import json,sys; d=json.loads(sys.argv[1]); print(d['neo4j_uri'])"          "$SESSION_RESPONSE")
REDIS_URL=$(python3       -c "import json,sys; d=json.loads(sys.argv[1]); print(d['redis_url'])"          "$SESSION_RESPONSE")
REDISPORT="${REDIS_PORT}"

echo "Allocated ports for ${SESSION_KEY}:"
echo "  postgres:    ${POSTGRES_PORT}"
echo "  redis:       ${REDIS_PORT}"
echo "  neo4j bolt:  ${SNG_NEO4J_BOLT_PORT}"
echo "  neo4j http:  ${SNG_NEO4J_HTTP_PORT}"
echo "  api:         ${API_PORT}"

# ── Update .env with the allocated ports ─────────────────────────────────────
# This runs for BOTH the "reuse" and "fresh start" paths so that any tool or
# script that reads .env directly (e.g. potpie_cli.py via load_dotenv) always
# sees the correct, current port numbers without needing to query the Discovery
# Server itself.
_dotenv_set() {
    local key="$1" value="$2" file=".env"
    if grep -q "^${key}=" "$file" 2>/dev/null; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$file"
    else
        printf '%s=%s\n' "$key" "$value" >> "$file"
    fi
}
[ -f .env ] || cp .env.template .env
_dotenv_set "POSTGRES_SERVER"  "${POSTGRES_SERVER}"
_dotenv_set "NEO4J_URI"        "${NEO4J_URI}"
_dotenv_set "NEO4J_HTTP_PORT"  "${SNG_NEO4J_HTTP_PORT}"
_dotenv_set "REDISHOST"        "127.0.0.1"
_dotenv_set "REDISPORT"        "${REDIS_PORT}"
_dotenv_set "BROKER_URL"       "${REDIS_URL}"
_dotenv_set "API_PORT"         "${API_PORT}"
_dotenv_set "API_URL"          "http://localhost:${API_PORT}"
echo "[start.sh] .env updated with dynamically allocated ports."

# ── Update potpie-ui/.env so the UI frontend points to the correct API port ──
# IMPORTANT: NEXT_PUBLIC_* vars in Next.js are compiled into the client-side
# bundle when the dev server starts — they are NOT re-read on each page request.
# Changing .env only takes effect after the Next.js dev server is restarted.
# start.sh handles this restart automatically in the fresh-start path below.
if [ -f "potpie-ui/.env" ]; then
    _dotenv_ui_set() {
        local key="$1" value="$2" file="potpie-ui/.env"
        if grep -q "^${key}=" "$file" 2>/dev/null; then
            sed -i "s|^${key}=.*|${key}=${value}|" "$file"
        else
            printf '%s=%s\n' "$key" "$value" >> "$file"
        fi
    }
    _dotenv_ui_set "NEXT_PUBLIC_BASE_URL"              "http://localhost:${API_PORT}"
    _dotenv_ui_set "NEXT_PUBLIC_CONVERSATION_BASE_URL" "http://localhost:${API_PORT}"
    _dotenv_ui_set "NEXT_PUBLIC_SUBSCRIPTION_BASE_URL" "http://localhost:${API_PORT}"
    echo "[start.sh] potpie-ui/.env updated: API URLs → http://localhost:${API_PORT}"
fi

# ── Check if session is already healthy (reuse) ───────────────────────────────
# The Discovery Server returns existing ports when the session is still alive.
# Verify the services actually respond before skipping the full startup.
if _port_open "$POSTGRES_PORT" && _port_open "$REDIS_PORT" && \
   _port_open "$SNG_NEO4J_BOLT_PORT" && \
   curl -sf "http://localhost:${API_PORT}/health" >/dev/null 2>&1; then
    echo "Potpie backend for ${SESSION_KEY} is already running and healthy — reusing."
    export POSTGRES_SERVER NEO4J_URI REDISPORT REDIS_URL API_PORT
    echo "Potpie is running!"
    exit 0
fi

# Services are not responding → start fresh.
# Clean up any stale processes recorded in the Discovery Server.
_disco_cleanup() {
    # Fetch current PIDs from Discovery Server and kill them
    local pids_json
    pids_json=$(curl -sf "http://127.0.0.1:${DISCOVERY_PORT}/session/${SESSION_KEY}" \
        2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); [print(p) for p in d.get('pids',{}).values()]" 2>/dev/null) || true
    for _pid in $pids_json; do
        kill "$_pid" 2>/dev/null || true
    done
}
_disco_cleanup
bash singularity/down.sh 2>/dev/null || true
find singularity/potpie-data/neo4j/data -name "store_lock" -delete 2>/dev/null || true

# Export port numbers so up.sh and the container env scripts pick them up.
export POSTGRES_PORT REDIS_PORT SNG_NEO4J_BOLT_PORT SNG_NEO4J_HTTP_PORT API_PORT
export POSTGRES_SERVER NEO4J_URI REDISPORT REDIS_URL

echo "Starting Singularity services..."
bash singularity/up.sh

# Fallback: explicitly start services if singularity-compose background: true did not launch them.
# These are idempotent - safe to uncomment if services fail to start automatically.
# echo "Starting postgres..."
# singularity exec instance://postgres1 pg_ctl -D /var/lib/postgresql/data -l /var/lib/postgresql/data/postgres.log start 2>&1 || true
# echo "Starting redis..."
# singularity exec instance://redis1 redis-cli ping 2>/dev/null | grep -q PONG || \
#   singularity exec instance://redis1 redis-server /data/redis-runtime.conf --daemonize yes 2>&1 || true
# Neo4j 2026+ starts automatically via the container image's own entrypoint
# (docker-entrypoint.sh → neo4j console) when the Singularity instance starts.
# Do NOT call 'neo4j start' explicitly — it would create a second neo4j process
# and fail with a store_lock conflict against the already-running instance.
#
# Application-level vars (NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD) are
# already unset in up.sh before singularity-compose starts the instance, so
# they don't leak into neo4j.conf.  Nothing to do here; just wait below.
echo "Neo4j starting via container entrypoint (waiting for bolt port)..."

# Wait for postgres to be ready
echo "Waiting for postgres to be ready..."
until SINGULARITYENV_PGPORT="${POSTGRES_PORT}" singularity exec instance://postgres1 psql -h /var/run/postgresql -p "${POSTGRES_PORT}" -U postgres -c "SELECT 1" postgres >/dev/null 2>&1; do
  echo "Postgres is unavailable - sleeping"
  sleep 2
done

# Wait for redis to be ready
echo "Waiting for redis to be ready..."
until singularity exec instance://redis1 redis-cli -p "${REDIS_PORT}" ping 2>/dev/null | grep -q PONG; do
  echo "Redis is unavailable - sleeping"
  sleep 2
done
echo "Redis is up"

echo "Postgres is up - applying database migrations"

# Create momentum database if it doesn't exist
echo "Ensuring database exists..."
singularity exec instance://postgres1 psql -h /var/run/postgresql -p "${POSTGRES_PORT}" -U postgres -tc \
  "SELECT 1 FROM pg_database WHERE datname = 'momentum'" 2>/dev/null | grep -q 1 || \
  singularity exec instance://postgres1 psql -h /var/run/postgresql -p "${POSTGRES_PORT}" -U postgres -c "CREATE DATABASE momentum" 2>/dev/null

# Disable GSSAPI/Kerberos in postgres connection (not supported on this host)
if [ -n "$POSTGRES_SERVER" ] && [[ "$POSTGRES_SERVER" != *"gssencmode"* ]]; then
    if [[ "$POSTGRES_SERVER" == *"?"* ]]; then
        export POSTGRES_SERVER="${POSTGRES_SERVER}&gssencmode=disable"
    else
        export POSTGRES_SERVER="${POSTGRES_SERVER}?gssencmode=disable"
    fi
fi

# Ensure uv is available
if ! command -v uv >/dev/null 2>&1; then
    echo "Error: uv command not found. Install uv from https://docs.astral.sh/uv/getting-started/ before running this script."
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    uv venv
fi

# Synchronize and create the managed virtual environment if needed
echo "Syncing Python environment with uv..."
if ! uv sync; then
  echo "Error: Failed to synchronize Python dependencies"
  exit 1
fi

# Install CLI dependencies (click, rich, pyyaml)
echo "Installing CLI dependencies..."
uv pip install --group cli

# Install gVisor (optional, for command isolation)
echo "Installing gVisor (optional, for command isolation)..."
if python scripts/install_gvisor.py 2>/dev/null; then
  echo "gVisor installed successfully"
else
  echo "Note: gVisor installation skipped or failed (this is optional)"
fi

# Apply database migrations within the uv-managed environment
source .venv/bin/activate

alembic upgrade heads

# Wait for neo4j to be ready BEFORE starting the application.
# The app requires neo4j at startup; starting gunicorn before neo4j is ready
# causes startup errors and the extension to never see a healthy API.
#
# Phase 1: fast TCP check until the bolt port opens (no JVM spawn per tick).
# Phase 2: cypher-shell auth check once the port accepts connections.
echo "Waiting for neo4j to be ready..."
NEO4J_BOLT_PORT="${SNG_NEO4J_BOLT_PORT:-7687}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-mysecretpassword}"
until (echo >/dev/tcp/127.0.0.1/${NEO4J_BOLT_PORT}) >/dev/null 2>&1; do
  echo "Neo4j is unavailable - sleeping"
  sleep 3
done
# Port is open — now verify auth is accepted (bolt handshake can still lag)
NEO4J_WAIT_MAX=300  # seconds (APOC plugin loading can take 2-3 min)
NEO4J_WAITED=0
until singularity exec instance://neo4j1 cypher-shell --uri "bolt://localhost:${NEO4J_BOLT_PORT}" -u neo4j -p "${NEO4J_PASSWORD}" "RETURN 1" >/dev/null 2>&1; do
  echo "Neo4j port open but auth not ready - sleeping"
  sleep 3
  NEO4J_WAITED=$((NEO4J_WAITED + 3))
  if [ "$NEO4J_WAITED" -ge "$NEO4J_WAIT_MAX" ]; then
    echo "ERROR: Neo4j did not become ready after ${NEO4J_WAIT_MAX}s."
    echo "Check Neo4j logs with: singularity exec instance://neo4j1 cat /var/lib/neo4j/logs/neo4j.log"
    exit 1
  fi
done
echo "Neo4j is up"

echo "Starting momentum application..."
gunicorn --worker-class uvicorn.workers.UvicornWorker --workers 1 --timeout 1800 --bind 0.0.0.0:${API_PORT} --log-level debug app.main:app &
GUNICORN_PID=$!

echo "Starting Celery worker..."
celery -A app.celery.celery_app worker --loglevel=debug -Q "${CELERY_QUEUE_NAME}_process_repository,${CELERY_QUEUE_NAME}_agent_tasks" -E --concurrency=1 --pool=solo &
CELERY_PID=$!

# ── Register PIDs with Discovery Server ───────────────────────────────────────
# Now that Gunicorn and Celery are running the Discovery Server can track them
# for automatic cleanup on TTL expiry.

# Start heartbeat loop in background (sends POST /heartbeat every 30 s).
# The loop exits automatically when the Discovery Server stops responding.
(while true; do
    sleep 30
    curl -sf -X POST \
        "http://127.0.0.1:${DISCOVERY_PORT}/session/${SESSION_KEY}/heartbeat" \
        >/dev/null 2>&1 || break
done) &
HEARTBEAT_PID=$!

curl -sf -X POST "http://127.0.0.1:${DISCOVERY_PORT}/session/${SESSION_KEY}/register" \
    -H "Content-Type: application/json" \
    -d "{\"pids\": {\"gunicorn\": ${GUNICORN_PID}, \"celery\": ${CELERY_PID}, \"heartbeat\": ${HEARTBEAT_PID}}}" \
    >/dev/null 2>&1 || echo "Warning: could not register PIDs with Discovery Server (non-fatal)"

# Poll the API health endpoint until the server is accepting requests.
# Only then do we print "Potpie is running!" and exit with 0, so the VS Code
# extension's runScript promise resolves and the tree switches to 'ready'.
echo "Waiting for API to be healthy..."
API_WAIT_MAX=120
API_WAITED=0
until curl -sf http://localhost:${API_PORT}/health >/dev/null 2>&1; do
  sleep 2
  API_WAITED=$((API_WAITED + 2))
  if [ "$API_WAITED" -ge "$API_WAIT_MAX" ]; then
    echo "ERROR: API did not become healthy after ${API_WAIT_MAX}s."
    exit 1
  fi
done

echo "Potpie is running!"

# ── (Re)start the Next.js UI dev server ────────────────────────────────────
# NEXT_PUBLIC_* vars are baked into the client bundle at server startup time.
# Because the API port just changed (fresh start), the running dev server (if
# any) still has the old port in its bundle.  Kill it and start a new one so
# the browser picks up the correct API URLs immediately.
if [ -d "potpie-ui" ]; then
    UI_PID_FILE="${SESSION_DIR}/${SESSION_KEY}.ui.pid"
    UI_LOG_FILE="${SESSION_DIR}/ui-dev.log"

    # Kill any previously tracked UI dev server.
    if [ -f "$UI_PID_FILE" ]; then
        _old_ui_pid=$(cat "$UI_PID_FILE" 2>/dev/null || true)
        if [ -n "$_old_ui_pid" ] && kill -0 "$_old_ui_pid" 2>/dev/null; then
            kill "$_old_ui_pid" 2>/dev/null || true
            echo "[start.sh] Stopped previous Next.js UI dev server (PID ${_old_ui_pid})."
        fi
        rm -f "$UI_PID_FILE"
    fi

    # Detect package manager.
    if command -v pnpm >/dev/null 2>&1; then
        _UI_PM="pnpm"
    elif command -v npm >/dev/null 2>&1; then
        _UI_PM="npm"
    else
        echo "[start.sh] Warning: pnpm/npm not found — skipping UI dev server start."
        _UI_PM=""
    fi

    if [ -n "$_UI_PM" ]; then
        (cd potpie-ui && $_UI_PM run dev >> "$UI_LOG_FILE" 2>&1) &
        _UI_PID=$!
        echo "$_UI_PID" > "$UI_PID_FILE"
        echo "[start.sh] Next.js UI dev server started (PID ${_UI_PID})."
        echo "  UI logs : $UI_LOG_FILE"
        echo "  Open    : http://localhost:3000"
    fi
fi
