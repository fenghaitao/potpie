#!/bin/bash
export REDIS_PORT=${REDIS_PORT:-6379}
# Write a minimal runtime config so the port can be overridden via REDIS_PORT env var
printf "port %s\n" "$REDIS_PORT" > /data/redis-runtime.conf
