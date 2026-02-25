#!/bin/bash
set -e

# Run from project root
cd "$(dirname "$0")/.."

echo "Stopping Potpie services..."

# Kill the FastAPI (gunicorn) and Celery processes
echo "Stopping FastAPI and Celery processes..."
pkill -f "gunicorn" || true
pkill -f "celery" || true

# Stop Singularity services
echo "Stopping Singularity services..."
bash singularity/down.sh

echo "All Potpie services have been stopped successfully!"
