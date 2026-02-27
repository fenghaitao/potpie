#!/bin/bash
SINGULARITY_COMPOSE="$(cd "$(dirname "$0")" && pwd)/singularity-compose/.venv/bin/singularity-compose"

cd "$(dirname "$0")"

$SINGULARITY_COMPOSE down "$@"
