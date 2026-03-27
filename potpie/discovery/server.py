"""
Potpie Discovery Server — FastAPI application.

Run directly:
    python -m potpie.discovery [options]

Or import and embed:
    from potpie.discovery.server import create_app
    app = create_app()

CLI options (see main() / __main__.py):
    --host          Bind address (default: 127.0.0.1)
    --port          Specific port to bind (default: auto-select 8765-8775)
    --port-file     Write the bound port number to this file on startup
    --neo4j-data    Path to Neo4j data directory (for store_lock cleanup)
    --ttl           Session TTL in seconds (default: 3600)
"""

from __future__ import annotations

import logging
import os
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .models import (
    CreateSessionRequest,
    CreateSessionResponse,
    HeartbeatResponse,
    HealthResponse,
    RegisterPidsRequest,
    SessionInfo,
)
from .port_allocator import PortAllocator
from .session_manager import SessionManager

logger = logging.getLogger(__name__)


# ── App factory ───────────────────────────────────────────────────────────────


def create_app(
    neo4j_data_path: Optional[str] = None,
    ttl_seconds: int = 3600,
) -> FastAPI:
    """
    Build and return the FastAPI Discovery Server application.

    Parameters
    ----------
    neo4j_data_path:
        Absolute path to the Neo4j *data* directory (the one containing
        ``databases/store_lock``).  When provided, expired sessions will
        automatically remove a stale store_lock.
    ttl_seconds:
        How long (in seconds) a session lives without a heartbeat before
        the cleanup loop terminates its processes and releases its ports.
    """
    port_allocator = PortAllocator()
    session_manager = SessionManager(
        port_allocator=port_allocator,
        neo4j_data_path=neo4j_data_path,
        ttl_seconds=ttl_seconds,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, Any]:
        logger.info("Discovery Server starting up")
        yield
        logger.info("Discovery Server shutting down — terminating all sessions")
        session_manager.shutdown()

    app = FastAPI(
        title="Potpie Discovery Server",
        description=(
            "Central session registry and dynamic port allocator for Potpie "
            "backend services (Postgres, Redis, Neo4j, API)."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    # ── Health ────────────────────────────────────────────────────────────────

    @app.get("/health", response_model=HealthResponse, tags=["meta"])
    def health() -> HealthResponse:
        """Liveness probe — always returns 200 when the server is up."""
        return HealthResponse(
            status="ok",
            active_sessions=session_manager.active_count,
            discovery_pid=os.getpid(),
        )

    # ── Session CRUD ─────────────────────────────────────────────────────────

    @app.get("/sessions", response_model=List[SessionInfo], tags=["session"])
    def list_sessions() -> List[SessionInfo]:
        """List all active sessions."""
        return session_manager.list_sessions()

    @app.post(
        "/session",
        response_model=CreateSessionResponse,
        status_code=201,
        tags=["session"],
    )
    def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
        """
        Create a new session (or reuse an existing healthy one).

        The Discovery Server allocates free ports for all backend services and
        returns them to the caller.  If a non-expired session for
        *session_id* already exists, its ports are returned unchanged and its
        heartbeat is refreshed — allowing idempotent calls from start.sh.
        """
        try:
            session = session_manager.create_session(
                session_id=req.session_id,
                user=req.user,
                host=req.host,
                preferred_ports={
                    "postgres": req.preferred_postgres_port,
                    "redis": req.preferred_redis_port,
                    "neo4j_bolt": req.preferred_neo4j_bolt_port,
                    "neo4j_http": req.preferred_neo4j_http_port,
                    "api": req.preferred_api_port,
                },
            )
        except Exception as exc:
            logger.exception("Failed to create session %s", req.session_id)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return CreateSessionResponse(
            session_id=session.session_id,
            ports=session.ports,
            services=session.services,
            postgres_server=session.postgres_server,
            neo4j_uri=session.neo4j_uri,
            redis_url=session.redis_url,
        )

    @app.get(
        "/session/{session_id}",
        response_model=SessionInfo,
        tags=["session"],
    )
    def get_session(session_id: str) -> SessionInfo:
        """Retrieve full session info including ports and registered PIDs."""
        session = session_manager.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
        return session.to_info()

    @app.post(
        "/session/{session_id}/register",
        tags=["session"],
    )
    def register_pids(session_id: str, req: RegisterPidsRequest) -> dict:
        """
        Associate OS process PIDs with a session.

        Called by start.sh after Gunicorn and Celery are launched so the
        cleanup mechanism can SIGTERM them on TTL expiry.
        """
        ok = session_manager.register_pids(session_id, req.pids)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
        return {"ok": True}

    @app.post(
        "/session/{session_id}/heartbeat",
        response_model=HeartbeatResponse,
        tags=["session"],
    )
    def heartbeat(session_id: str) -> HeartbeatResponse:
        """
        Reset the session TTL countdown.

        Should be called every 30 s by the heartbeat loop started in
        singularity/start.sh.  Returns the new expiry timestamp.
        """
        expires_at = session_manager.heartbeat(session_id)
        if expires_at is None:
            raise HTTPException(
                status_code=404,
                detail=f"Session '{session_id}' not found — session may have expired",
            )
        return HeartbeatResponse(ok=True, expires_at=expires_at)

    @app.delete("/session/{session_id}", tags=["session"])
    def delete_session(session_id: str) -> dict:
        """
        Terminate a session immediately.

        Kills all registered processes (Gunicorn, Celery, heartbeat loop),
        releases their ports, and removes the Neo4j store_lock if present.
        Called by singularity/stop.sh during a clean shutdown.
        """
        ok = session_manager.delete_session(session_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
        return {"ok": True}

    return app


# ── Port finder for the Discovery Server itself ───────────────────────────────


def find_free_discovery_port(start: int = 8765, end: int = 8775) -> int:
    """
    Find a free port for the Discovery Server in the preferred range.

    Tries each port in [start, end] in order; returns the first that can be
    bound.  Raises RuntimeError if every port in the range is occupied.
    """
    for port in range(start, end + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
    raise RuntimeError(
        f"No free port found in range {start}–{end} for the Discovery Server. "
        "Try a different range with --port."
    )


# ── Entrypoint (also invoked by __main__.py) ──────────────────────────────────


def main() -> None:
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(
        description="Potpie Discovery Server — session registry and port manager"
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Network interface to bind (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=0,
        help="Port to listen on (default: auto-select from 8765–8775)",
    )
    parser.add_argument(
        "--port-file", default=None,
        help="Write the bound port number to this path (signals readiness to start.sh)",
    )
    parser.add_argument(
        "--neo4j-data", default=None,
        help=(
            "Absolute path to the Neo4j data directory "
            "(e.g. singularity/potpie-data/neo4j/data). "
            "Used to clean up store_lock on session expiry."
        ),
    )
    parser.add_argument(
        "--ttl", type=int, default=3600,
        help="Session time-to-live in seconds (default: 3600)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s",
    )

    # Determine port
    port: int
    if args.port:
        port = args.port
    else:
        try:
            port = find_free_discovery_port()
        except RuntimeError as exc:
            logger.error("%s", exc)
            raise SystemExit(1) from exc

    neo4j_data = args.neo4j_data or os.environ.get("NEO4J_DATA_PATH")
    app = create_app(neo4j_data_path=neo4j_data, ttl_seconds=args.ttl)

    # Write port to file BEFORE uvicorn starts so the shell can read it
    # immediately and begin waiting for /health.
    if args.port_file:
        Path(args.port_file).parent.mkdir(parents=True, exist_ok=True)
        Path(args.port_file).write_text(str(port))
        logger.info("Wrote bound port %d to %s", port, args.port_file)

    logger.info("Starting Discovery Server on %s:%d (TTL=%ds)", args.host, port, args.ttl)
    uvicorn.run(app, host=args.host, port=port, log_level="warning")
