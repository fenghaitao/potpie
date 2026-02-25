#!/bin/bash
SINGULARITY_COMPOSE=/nfs/site/disks/hfeng1_fw_01/coder/singularity-compose/.venv/bin/singularity-compose

cd "$(dirname "$0")"

$SINGULARITY_COMPOSE down "$@"
