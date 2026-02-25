#!/bin/bash
export NEO4J_AUTH=neo4j/mysecretpassword
export NEO4JLABS_PLUGINS='["apoc"]'
export NEO4J_dbms_security_procedures_unrestricted=apoc.*
export NEO4J_dbms_memory_transaction_total_max=0
export NEO4J_server_http_listen__address=0.0.0.0:${SNG_NEO4J_HTTP_PORT:-7474}
export NEO4J_server_bolt_listen__address=0.0.0.0:${SNG_NEO4J_BOLT_PORT:-7687}
