#!/bin/bash
export NEO4J_AUTH=neo4j/mysecretpassword
# Neo4j 5+ renamed NEO4JLABS_PLUGINS → NEO4J_PLUGINS; set both for compatibility.
export NEO4J_PLUGINS='["apoc"]'
export NEO4JLABS_PLUGINS='["apoc"]'
export NEO4J_dbms_security_procedures_unrestricted=apoc.*
export NEO4J_dbms_memory_transaction_total_max=0

# Listen on all interfaces at the dynamically allocated ports.
export NEO4J_server_http_listen__address=0.0.0.0:${SNG_NEO4J_HTTP_PORT:-7474}
export NEO4J_server_bolt_listen__address=0.0.0.0:${SNG_NEO4J_BOLT_PORT:-7687}

# Advertised addresses — what clients (including the Neo4j Browser) are told
# to use when connecting.  Using "localhost" so the Browser's "Connection URL"
# pre-fills as bolt://localhost:<port> regardless of the machine hostname.
export NEO4J_server_http_advertised__address="localhost:${SNG_NEO4J_HTTP_PORT:-7474}"
export NEO4J_server_bolt_advertised__address="localhost:${SNG_NEO4J_BOLT_PORT:-7687}"

# Disable inotify file watcher — shared HPC systems quickly exhaust the
# default fs.inotify.max_user_watches=65536 limit across all users/processes.
export NEO4J_dbms_filewatcher_enabled=false
