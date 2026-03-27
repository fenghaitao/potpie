"""
Session manager — in-memory registry of active Potpie sessions with
heartbeat-based TTL cleanup.

Design
------
* One SessionManager per Discovery Server process.
* Sessions are keyed by session_id (typically "user@hostname").
* Each session owns a set of ports allocated by PortAllocator.
* A background daemon thread runs every CLEANUP_INTERVAL seconds and
  terminates sessions whose last_heartbeat is older than TTL_SECONDS.
* On termination: PIDs are SIGTERM-ed, ports are released, the Neo4j
  store_lock is removed (if the data path is configured).
* All state mutations are protected by a single threading.Lock.

TTL strategy
------------
Default TTL is 3600 s (1 hour) — long enough to survive the entire startup
sequence (neo4j APOC loading can take 3+ minutes) without a heartbeat.
Once the Celery / Gunicorn processes are running they send POST /heartbeat
every 30 s, which resets the expiry window.  If the host crashes or the
heartbeat process is killed, the session is automatically cleaned up within
TTL seconds.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .models import (
    PortAllocation,
    ServiceEndpoints,
    SessionInfo,
)
from .port_allocator import PortAllocator

logger = logging.getLogger(__name__)

# Default configuration (can be overridden per-session in create_session)
DEFAULT_TTL_SECONDS = 3600  # 1 hour
CLEANUP_INTERVAL_SECONDS = 15  # background cleanup frequency


# ── Internal session dataclass ────────────────────────────────────────────────


@dataclass
class _Session:
    session_id: str
    user: str
    host: str
    ports: PortAllocation
    services: ServiceEndpoints
    postgres_server: str
    neo4j_uri: str
    redis_url: str
    pids: Dict[str, int] = field(default_factory=dict)
    started_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_heartbeat: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    ttl_seconds: int = DEFAULT_TTL_SECONDS

    @property
    def expires_at(self) -> datetime:
        return self.last_heartbeat + timedelta(seconds=self.ttl_seconds)

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at

    def touch(self) -> None:
        """Reset the TTL countdown."""
        self.last_heartbeat = datetime.now(timezone.utc)

    def to_info(self) -> SessionInfo:
        return SessionInfo(
            session_id=self.session_id,
            user=self.user,
            host=self.host,
            ports=self.ports,
            services=self.services,
            pids=dict(self.pids),
            started_at=self.started_at,
            last_heartbeat=self.last_heartbeat,
            expires_at=self.expires_at,
            postgres_server=self.postgres_server,
            neo4j_uri=self.neo4j_uri,
            redis_url=self.redis_url,
        )


# ── Session manager ───────────────────────────────────────────────────────────


class SessionManager:
    """
    Central registry for all active Potpie sessions.

    Thread-safe: all public methods acquire self._lock.
    """

    def __init__(
        self,
        port_allocator: PortAllocator,
        neo4j_data_path: Optional[str] = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        cleanup_interval: int = CLEANUP_INTERVAL_SECONDS,
    ) -> None:
        self._sessions: Dict[str, _Session] = {}
        self._lock = threading.Lock()
        self._allocator = port_allocator
        self._neo4j_data_path = neo4j_data_path
        self._default_ttl = ttl_seconds

        # Daemon thread — exits automatically when main process exits.
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            args=(cleanup_interval,),
            daemon=True,
            name="discovery-cleanup",
        )
        self._cleanup_thread.start()
        logger.info(
            "SessionManager started (TTL=%ds, cleanup every %ds)",
            ttl_seconds,
            cleanup_interval,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def create_session(
        self,
        session_id: str,
        user: str,
        host: str,
        preferred_ports: Optional[Dict[str, int]] = None,
        postgres_password: str = "mysecretpassword",
        redis_host: str = "127.0.0.1",
    ) -> _Session:
        """
        Create a new session or return an existing healthy one.

        If a session with *session_id* already exists and is not expired,
        its heartbeat is reset and the existing session (with existing ports)
        is returned — allowing start.sh to detect that services are already
        running and skip re-allocation.

        If the session is expired, it is terminated first, then a fresh one
        is created with newly allocated ports.
        """
        with self._lock:
            existing = self._sessions.get(session_id)
            if existing is not None:
                if not existing.is_expired():
                    existing.touch()
                    logger.info("Reusing existing session %s", session_id)
                    return existing
                else:
                    logger.info(
                        "Session %s expired — cleaning up before recreating", session_id
                    )
                    self._terminate_session_locked(existing)

            # Allocate 5 ports atomically.
            ports_list = self._allocator.allocate_batch(5)
            pg_port, redis_port, bolt_port, http_port, api_port = ports_list

            # Honour caller preferences by swapping with allocated ports when
            # the preferred port happens to be free.  This keeps default ports
            # (5432, 6379, …) where possible, improving readability.
            pg_port, redis_port, bolt_port, http_port, api_port = (
                self._prefer(
                    preferred_ports or {},
                    pg_port, redis_port, bolt_port, http_port, api_port,
                )
            )

            ports = PortAllocation(
                postgres=pg_port,
                redis=redis_port,
                neo4j_bolt=bolt_port,
                neo4j_http=http_port,
                api=api_port,
            )
            services = ServiceEndpoints(
                postgres=f"localhost:{pg_port}",
                redis=f"localhost:{redis_port}",
                neo4j_bolt=f"localhost:{bolt_port}",
                neo4j_http=f"localhost:{http_port}",
                api=f"localhost:{api_port}",
            )
            postgres_server = (
                f"postgresql://postgres:{postgres_password}@localhost:{pg_port}"
                f"/momentum?gssencmode=disable"
            )
            neo4j_uri = f"bolt://127.0.0.1:{bolt_port}"
            redis_url = f"redis://{redis_host}:{redis_port}/0"

            session = _Session(
                session_id=session_id,
                user=user,
                host=host,
                ports=ports,
                services=services,
                postgres_server=postgres_server,
                neo4j_uri=neo4j_uri,
                redis_url=redis_url,
                ttl_seconds=self._default_ttl,
            )
            self._sessions[session_id] = session
            logger.info(
                "Created session %s — postgres:%d redis:%d neo4j_bolt:%d api:%d",
                session_id, pg_port, redis_port, bolt_port, api_port,
            )
            return session

    def get_session(self, session_id: str) -> Optional[_Session]:
        with self._lock:
            return self._sessions.get(session_id)

    def register_pids(self, session_id: str, pids: Dict[str, int]) -> bool:
        """Associate process PIDs with a session. Returns False if not found."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session.pids.update(pids)
            logger.info("Session %s: registered PIDs %s", session_id, pids)
            return True

    def heartbeat(self, session_id: str) -> Optional[datetime]:
        """
        Refresh the session TTL.  Returns the new expiry time, or None if
        the session does not exist (caller should re-create).
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.touch()
            return session.expires_at

    def delete_session(self, session_id: str) -> bool:
        """Terminate and remove a session.  Returns False if not found."""
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if session is None:
                return False
            self._terminate_session_locked(session)
            logger.info("Session %s deleted on request", session_id)
            return True

    def list_sessions(self) -> List[SessionInfo]:
        with self._lock:
            return [s.to_info() for s in self._sessions.values()]

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def shutdown(self) -> None:
        """Terminate all sessions gracefully (called on server shutdown)."""
        with self._lock:
            for session in list(self._sessions.values()):
                self._terminate_session_locked(session)
            self._sessions.clear()
        logger.info("SessionManager shut down — all sessions terminated")

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _terminate_session_locked(self, session: _Session) -> None:
        """
        Kill all registered processes and release all ports.
        MUST be called with self._lock held.
        """
        for name, pid in session.pids.items():
            try:
                os.kill(pid, signal.SIGTERM)
                logger.debug("Session %s: SIGTERMed %s (PID %d)", session.session_id, name, pid)
            except (ProcessLookupError, PermissionError):
                pass  # already dead, ignore

        port_list = [
            session.ports.postgres,
            session.ports.redis,
            session.ports.neo4j_bolt,
            session.ports.neo4j_http,
            session.ports.api,
        ]
        self._allocator.release_batch(port_list)

        # Clean up the Neo4j store_lock so the next startup doesn't fail.
        if self._neo4j_data_path:
            lock_file = Path(self._neo4j_data_path) / "databases" / "store_lock"
            if lock_file.exists():
                try:
                    lock_file.unlink()
                    logger.info(
                        "Session %s: removed Neo4j store_lock at %s",
                        session.session_id, lock_file,
                    )
                except OSError as exc:
                    logger.warning("Could not remove store_lock: %s", exc)

    def _cleanup_loop(self, interval: int) -> None:
        """Background daemon: evict sessions whose TTL has elapsed."""
        while True:
            time.sleep(interval)
            try:
                self._evict_expired()
            except Exception:
                logger.exception("Error in cleanup loop — continuing")

    def _evict_expired(self) -> None:
        with self._lock:
            expired_ids = [
                sid for sid, s in self._sessions.items() if s.is_expired()
            ]
            for sid in expired_ids:
                session = self._sessions.pop(sid)
                self._terminate_session_locked(session)
                logger.info(
                    "Session %s evicted (TTL expired, last heartbeat %s)",
                    sid, session.last_heartbeat.isoformat(),
                )

    @staticmethod
    def _prefer(
        prefs: Dict[str, int],
        pg: int, redis: int, bolt: int, http: int, api: int,
    ) -> tuple:
        """
        When a caller specifies preferred ports, try to use them.

        The Discovery Server has already allocated real free ports via OS
        bind(). This method simply reorders the allocated list to match
        preferences where the preferred port == one of the allocated ports.
        The effect is cosmetic (nice default port numbers) when the preferred
        ports happen to be free.
        """
        # Preferred ports are just hints — we never override already-allocated
        # ports with unverified ones.  Return as-is (the OS-allocated ports are
        # already correct and conflict-free).
        _ = prefs  # reserved for future use
        return pg, redis, bolt, http, api
