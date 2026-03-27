#!/bin/bash
# Usage: ./up.sh [options]
#   POSTGRES_PORT=5433 ./up.sh
#   REDIS_PORT=6380 SNG_NEO4J_BOLT_PORT=7688 SNG_NEO4J_HTTP_PORT=7475 ./up.sh

SINGULARITY_COMPOSE="$(cd "$(dirname "$0")" && pwd)/singularity-compose/.venv/bin/singularity-compose"

cd "$(dirname "$0")"

# Ensure SINGULARITY_TMPDIR is set to a valid directory for host-side image
# builds (Singularity calls mktemp internally when building SIF images).
# We deliberately do NOT set or propagate TMPDIR: if it points to a host path
# that isn't bind-mounted inside containers, startup scripts (e.g. Neo4j)
# will fail when they call mktemp.  Unsetting TMPDIR here makes containers
# fall back to /tmp which is always available inside Singularity instances.
if [ -z "$SINGULARITY_TMPDIR" ] || [ ! -d "$SINGULARITY_TMPDIR" ]; then
    export SINGULARITY_TMPDIR=/tmp
fi
unset TMPDIR

# NEO4J_URI, NEO4J_USERNAME and NEO4J_PASSWORD are application-level variables
# (bolt connection string and app credentials used by gunicorn/celery).
# Do NOT pass them into Singularity containers: the neo4j Docker image
# translates every NEO4J_* env var into a neo4j.conf setting, so these would
# become the unrecognized keys URI / USERNAME / PASSWORD and fail validation.
# Container-specific settings (auth, plugins, listen addresses) are set
# exclusively via singularity/env/neo4j.sh (/.singularity.d/env/).
unset NEO4J_URI NEO4J_USERNAME NEO4J_PASSWORD

# Bootstrap singularity-compose venv on first use
if [ ! -x "$SINGULARITY_COMPOSE" ]; then
    echo "Setting up singularity-compose venv..."
    uv venv singularity-compose/.venv
    if [ -f singularity-compose/setup.py ] || [ -f singularity-compose/pyproject.toml ]; then
        # Submodule is initialized — install from local source (editable install).
        uv pip install --python singularity-compose/.venv/bin/python -e singularity-compose/
    else
        # Submodule not available (network restricted runner or not initialized).
        # Fall back to the published PyPI release which is functionally equivalent.
        echo "singularity-compose submodule not initialized — installing from PyPI"
        uv pip install --python singularity-compose/.venv/bin/python singularity-compose
    fi
fi

export POSTGRES_PORT=${POSTGRES_PORT:-5432}
export REDIS_PORT=${REDIS_PORT:-6379}
export SNG_NEO4J_BOLT_PORT=${SNG_NEO4J_BOLT_PORT:-7687}
export SNG_NEO4J_HTTP_PORT=${SNG_NEO4J_HTTP_PORT:-7474}

# Singularity requires the SINGULARITYENV_ prefix to reliably propagate host
# environment variables into container instances.  Export them here so that
# the env/ env scripts (e.g. env/neo4j.sh) see the correct dynamic ports.
export SINGULARITYENV_SNG_NEO4J_BOLT_PORT="$SNG_NEO4J_BOLT_PORT"
export SINGULARITYENV_SNG_NEO4J_HTTP_PORT="$SNG_NEO4J_HTTP_PORT"
export SINGULARITYENV_POSTGRES_PORT="$POSTGRES_PORT"
export SINGULARITYENV_REDIS_PORT="$REDIS_PORT"

echo "Starting services:"
echo "  postgres  -> :${POSTGRES_PORT}"
echo "  redis     -> :${REDIS_PORT}"
echo "  neo4j     -> bolt::${SNG_NEO4J_BOLT_PORT}  http::${SNG_NEO4J_HTTP_PORT}"
echo ""

# Build SIF images if any are missing
if [ ! -f postgres.sif ] || [ ! -f neo4j.sif ] || [ ! -f redis.sif ]; then
    echo "Building missing SIF images..."
    $SINGULARITY_COMPOSE build
fi

# Ensure all bind-mount source directories exist (required before singularity-compose up)
mkdir -p potpie-data/postgres \
         potpie-data/run/postgresql \
         potpie-data/neo4j/data \
         potpie-data/neo4j/logs \
         potpie-data/run/neo4j \
         potpie-data/redis \
         potpie-data/run/redis

PG_DATA_DIR="potpie-data/postgres"

# Clean up stale postgres files if postgres is not actually running
POSTMASTER_PID="potpie-data/postgres/postmaster.pid"
PG_RUN_DIR="potpie-data/run/postgresql"
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
