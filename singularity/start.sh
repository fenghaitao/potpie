#!/bin/bash
set -e

# Run from project root
SINGULARITY_COMPOSE="$(cd "$(dirname "$0")" && pwd)/singularity-compose/.venv/bin/singularity-compose"
cd "$(dirname "$0")/.."

source .env

# Set up Service Account Credentials
export GOOGLE_APPLICATION_CREDENTIALS="./service-account.json"

# Check if the credentials file exists
if [ ! -f "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
    echo "Warning: Service Account Credentials file not found at $GOOGLE_APPLICATION_CREDENTIALS"
    echo "Please ensure the service-account.json file is in the current directory if you are working outside developmentMode"
fi

echo "Starting Singularity services..."
bash singularity/up.sh

# Fallback: explicitly start services if singularity-compose background: true did not launch them.
# These are idempotent - safe to uncomment if services fail to start automatically.
# echo "Starting postgres..."
# singularity exec instance://postgres1 pg_ctl -D /var/lib/postgresql/data -l /var/lib/postgresql/data/postgres.log start 2>&1 || true
# echo "Starting redis..."
# singularity exec instance://redis1 redis-cli ping 2>/dev/null | grep -q PONG || \
#   singularity exec instance://redis1 redis-server /data/redis-runtime.conf --daemonize yes 2>&1 || true
# echo "Starting neo4j..."
# singularity exec instance://neo4j1 neo4j start 2>&1 || true

# Wait for postgres to be ready
echo "Waiting for postgres to be ready..."
until singularity exec instance://postgres1 psql -h /var/run/postgresql -U postgres -c "SELECT 1" postgres >/dev/null 2>&1; do
  echo "Postgres is unavailable - sleeping"
  sleep 2
done

# Wait for redis to be ready
echo "Waiting for redis to be ready..."
until singularity exec instance://redis1 redis-cli ping 2>/dev/null | grep -q PONG; do
  echo "Redis is unavailable - sleeping"
  sleep 2
done
echo "Redis is up"

echo "Postgres is up - applying database migrations"

# Restore .gitignore placeholder now that initdb has completed
git checkout -- singularity/potpie-data/postgres/.gitignore 2>/dev/null || true

# Create momentum database if it doesn't exist
echo "Ensuring database exists..."
singularity exec instance://postgres1 psql -h /var/run/postgresql -U postgres -tc \
  "SELECT 1 FROM pg_database WHERE datname = 'momentum'" 2>/dev/null | grep -q 1 || \
  singularity exec instance://postgres1 psql -h /var/run/postgresql -U postgres -c "CREATE DATABASE momentum" 2>/dev/null

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

echo "Starting momentum application..."
gunicorn --worker-class uvicorn.workers.UvicornWorker --workers 1 --timeout 1800 --bind 0.0.0.0:8001 --log-level debug app.main:app &

# Wait for neo4j bolt port to be ready
echo "Waiting for neo4j to be ready..."
NEO4J_PASSWORD="${NEO4J_PASSWORD:-mysecretpassword}"
until singularity exec instance://neo4j1 cypher-shell -u neo4j -p "${NEO4J_PASSWORD}" "RETURN 1" >/dev/null 2>&1; do
  echo "Neo4j is unavailable - sleeping"
  sleep 5
done
echo "Neo4j is up"

echo "Starting Celery worker..."
celery -A app.celery.celery_app worker --loglevel=debug -Q "${CELERY_QUEUE_NAME}_process_repository,${CELERY_QUEUE_NAME}_agent_tasks" -E --concurrency=1 --pool=solo &

echo "Potpie is running!"
