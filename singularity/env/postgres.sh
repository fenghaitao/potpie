#!/bin/bash
export POSTGRES_USER=postgres
export POSTGRES_PASSWORD=mysecretpassword
export POSTGRES_DB=momentum
export PGDATA=/var/lib/postgresql/data
export PGPORT=${POSTGRES_PORT:-5432}
