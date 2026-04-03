#!/bin/bash
set -e

# Run from project root
cd "$(dirname "$0")/.."

POTPIE_USER="${USER:-$(id -un)}"
POTPIE_HOST="$(hostname -s 2>/dev/null || hostname)"
SESSION_KEY="${POTPIE_USER}@${POTPIE_HOST}"
SESSION_DIR="${PWD}/.potpie-sessions"
DISCOVERY_FILE="${SESSION_DIR}/${SESSION_KEY}.discovery"

# Parse flags.
POTPIE_FORCE=0
for _arg in "$@"; do [ "$_arg" = "--force" ] && POTPIE_FORCE=1; done

# ── Helper: find Discovery Server port for this user@machine ─────────────────
_get_discovery_port() {
    local dfile="$1"
    [ -f "$dfile" ] || return 1
    python3 -c "import json; print(json.load(open('$dfile'))['port'])" 2>/dev/null
}

# ── Helper: delete session via Discovery API, fall back to JSON file ──────────
_delete_session_via_api() {
    local session_id="$1"
    local dfile="$2"
    local port
    if port=$(_get_discovery_port "$dfile"); then
        if curl -sf -X DELETE \
            "http://127.0.0.1:${port}/session/${session_id}" \
            >/dev/null 2>&1; then
            echo "  session '${session_id}' terminated via Discovery Server."
            return 0
        fi
    fi
    return 1  # caller falls back to direct PID kill from JSON file
}

# ── Helper: stop Discovery Server if it has no more sessions ─────────────────
_maybe_stop_discovery() {
    local dfile="$1"
    [ -f "$dfile" ] || return 0
    local port remaining pid
    port=$(python3  -c "import json; print(json.load(open('$dfile'))['port'])" 2>/dev/null) || return 0
    pid=$(python3   -c "import json; print(json.load(open('$dfile'))['pid'])"  2>/dev/null) || return 0

    remaining=$(curl -sf "http://127.0.0.1:${port}/sessions" 2>/dev/null | \
        python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "1")
    if [ "${remaining}" = "0" ]; then
        echo "No remaining sessions — stopping Discovery Server (PID ${pid})..."
        kill "$pid" 2>/dev/null || true
        rm -f "$dfile"
    else
        echo "Discovery Server has ${remaining} remaining session(s) — leaving it running."
    fi
}

if [ "$POTPIE_FORCE" -eq 1 ]; then
    # --force: clean up ALL sessions for this user in this repo.
    echo "Force-stopping ALL Potpie sessions for '${POTPIE_USER}' in this repo..."

    # Try Discovery Server first; it terminates all PIDs cleanly.
    if DISCOVERY_PORT=$(_get_discovery_port "$DISCOVERY_FILE" 2>/dev/null); then
        ALL_SESSIONS=$(curl -sf "http://127.0.0.1:${DISCOVERY_PORT}/sessions" 2>/dev/null | \
            python3 -c "
import json, sys
sessions = json.load(sys.stdin)
user = '${POTPIE_USER}'
for s in sessions:
    if s.get('user') == user:
        print(s['session_id'])
" 2>/dev/null || true)
        for _sid in $ALL_SESSIONS; do
            curl -sf -X DELETE "http://127.0.0.1:${DISCOVERY_PORT}/session/${_sid}" >/dev/null 2>&1 \
                && echo "  terminated session '${_sid}' via Discovery Server." || true
        done
        # Stop Discovery Server.
        DISCO_PID=$(python3 -c "import json; print(json.load(open('$DISCOVERY_FILE'))['pid'])" 2>/dev/null || true)
        [ -n "$DISCO_PID" ] && kill "$DISCO_PID" 2>/dev/null || true
        rm -f "$DISCOVERY_FILE"
        echo "  Discovery Server stopped."
    fi

    echo "Stopping Singularity services on this machine..."
    bash singularity/down.sh

    echo "Removing neo4j store_lock file(s)..."
    find singularity/potpie-data/neo4j/data -name "store_lock" -delete 2>/dev/null \
        && echo "  store_lock(s) removed." || echo "  no store_lock files found."

    # Kill any tracked UI dev servers for this user in any session.
    for _ui_pid_file in "${SESSION_DIR}/"*".ui.pid"; do
        [ -f "$_ui_pid_file" ] || continue
        _ui_pid=$(cat "$_ui_pid_file" 2>/dev/null || true)
        if [ -n "$_ui_pid" ] && kill -0 "$_ui_pid" 2>/dev/null; then
            kill "$_ui_pid" 2>/dev/null || true
            echo "  Stopped Next.js UI dev server (PID ${_ui_pid}) from ${_ui_pid_file}."
        fi
        rm -f "$_ui_pid_file"
    done

    echo "Force-stop complete for '${POTPIE_USER}' in this repo."
    exit 0
fi

echo "Stopping Potpie services for ${SESSION_KEY}..."

# ── Terminate via Discovery API ──────────────────────────────────────────────
echo "Terminating session via Discovery Server..."
if ! _delete_session_via_api "$SESSION_KEY" "$DISCOVERY_FILE"; then
    echo "  Discovery Server unavailable — session may already be gone."
fi

# Stop Discovery Server if this was the last session.
_maybe_stop_discovery "$DISCOVERY_FILE"

# Stop Singularity services.  Singularity instances are scoped to the current
# user by the OS, so 'down' only affects this user's instances on this machine.
echo "Stopping Singularity services..."
bash singularity/down.sh

# ── Stop the Next.js UI dev server if we started it ─────────────────────────
UI_PID_FILE="${SESSION_DIR}/${SESSION_KEY}.ui.pid"
if [ -f "$UI_PID_FILE" ]; then
    _ui_pid=$(cat "$UI_PID_FILE" 2>/dev/null || true)
    if [ -n "$_ui_pid" ] && kill -0 "$_ui_pid" 2>/dev/null; then
        kill "$_ui_pid" 2>/dev/null || true
        echo "Stopped Next.js UI dev server (PID ${_ui_pid})."
    fi
    rm -f "$UI_PID_FILE"
fi

echo "All Potpie services for ${SESSION_KEY} have been stopped successfully!"
