#!/bin/bash
# Usage: ./up.sh [options]
#   POSTGRES_PORT=5433 ./up.sh
#   REDIS_PORT=6380 SNG_NEO4J_BOLT_PORT=7688 SNG_NEO4J_HTTP_PORT=7475 ./up.sh

SINGULARITY_COMPOSE=/nfs/site/disks/hfeng1_fw_01/coder/singularity-compose/.venv/bin/singularity-compose

cd "$(dirname "$0")"

export POSTGRES_PORT=${POSTGRES_PORT:-5432}
export REDIS_PORT=${REDIS_PORT:-6379}
export SNG_NEO4J_BOLT_PORT=${SNG_NEO4J_BOLT_PORT:-7687}
export SNG_NEO4J_HTTP_PORT=${SNG_NEO4J_HTTP_PORT:-7474}

echo "Starting services:"
echo "  postgres  -> :${POSTGRES_PORT}"
echo "  redis     -> :${REDIS_PORT}"
echo "  neo4j     -> bolt::${SNG_NEO4J_BOLT_PORT}  http::${SNG_NEO4J_HTTP_PORT}"
echo ""

# Clean up stale postgres files if postgres is not actually running
POSTMASTER_PID="$(dirname "$0")/potpie-data/postgres/postmaster.pid"
PG_RUN_DIR="$(dirname "$0")/potpie-data/run/postgresql"
if [ -f "$POSTMASTER_PID" ]; then
    STALE_PID=$(head -1 "$POSTMASTER_PID")
    if ! kill -0 "$STALE_PID" 2>/dev/null; then
        echo "Removing stale postmaster.pid (PID $STALE_PID is not running)"
        rm -f "$POSTMASTER_PID"
        # Also remove stale socket lock files
        rm -f "$PG_RUN_DIR"/.s.PGSQL.*.lock "$PG_RUN_DIR"/.s.PGSQL.*
    fi
fi

$SINGULARITY_COMPOSE up "$@"
