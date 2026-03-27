"""
Pydantic models for the Discovery Server REST API.

All timestamps are UTC ISO-8601 strings on the wire.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict

from pydantic import BaseModel, Field


# ── Port / service descriptors ────────────────────────────────────────────────


class PortAllocation(BaseModel):
    """Ports allocated for a single session's backend services."""

    postgres: int = Field(..., description="PostgreSQL port")
    redis: int = Field(..., description="Redis port")
    neo4j_bolt: int = Field(..., description="Neo4j Bolt protocol port")
    neo4j_http: int = Field(..., description="Neo4j HTTP browser port")
    api: int = Field(..., description="FastAPI / Gunicorn port")


class ServiceEndpoints(BaseModel):
    """Human-readable <host>:<port> strings for each backend service."""

    postgres: str
    redis: str
    neo4j_bolt: str
    neo4j_http: str
    api: str


# ── Full session descriptor ───────────────────────────────────────────────────


class SessionInfo(BaseModel):
    """Complete session state (returned by GET /session/{session_id})."""

    session_id: str
    user: str
    host: str
    ports: PortAllocation
    services: ServiceEndpoints
    pids: Dict[str, int] = Field(default_factory=dict)
    started_at: datetime
    last_heartbeat: datetime
    expires_at: datetime

    # Connection strings (convenience for clients)
    postgres_server: str = ""
    neo4j_uri: str = ""
    redis_url: str = ""


# ── Request / response bodies ─────────────────────────────────────────────────


class CreateSessionRequest(BaseModel):
    """Body of POST /session."""

    session_id: str = Field(..., description="Stable key, e.g. 'user@hostname'")
    user: str
    host: str
    # Optional: caller may suggest preferred starting ports; server may ignore.
    preferred_postgres_port: int = 5432
    preferred_redis_port: int = 6379
    preferred_neo4j_bolt_port: int = 7687
    preferred_neo4j_http_port: int = 7474
    preferred_api_port: int = 8001


class CreateSessionResponse(BaseModel):
    """Body of 201 response from POST /session."""

    session_id: str
    ports: PortAllocation
    services: ServiceEndpoints
    # Convenience connection strings
    postgres_server: str
    neo4j_uri: str
    redis_url: str


class RegisterPidsRequest(BaseModel):
    """Body of POST /session/{session_id}/register — associates process PIDs."""

    pids: Dict[str, int] = Field(
        ...,
        description=(
            "Map of process name → PID, e.g. "
            '{"gunicorn": 1234, "celery": 5678, "heartbeat": 9012}'
        ),
    )


class HeartbeatResponse(BaseModel):
    """Body of POST /session/{session_id}/heartbeat response."""

    ok: bool
    expires_at: datetime


class HealthResponse(BaseModel):
    """Body of GET /health response."""

    status: str
    active_sessions: int
    discovery_pid: int
