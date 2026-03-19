#!/bin/bash
export NEO4J_AUTH=neo4j/mysecretpassword
# Neo4j 5+ renamed NEO4JLABS_PLUGINS → NEO4J_PLUGINS; set both for compatibility.
export NEO4J_PLUGINS='["apoc"]'
export NEO4JLABS_PLUGINS='["apoc"]'
export NEO4J_dbms_security_procedures_unrestricted=apoc.*
export NEO4J_dbms_memory_transaction_total_max=0
export NEO4J_server_http_listen__address=0.0.0.0:${SNG_NEO4J_HTTP_PORT:-7474}
export NEO4J_server_bolt_listen__address=0.0.0.0:${SNG_NEO4J_BOLT_PORT:-7687}
