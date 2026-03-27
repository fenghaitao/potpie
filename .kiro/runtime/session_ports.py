"""
Shared runtime helper for potpie skill scripts.

apply_session_ports(repo_root) -- ensures the backend services (postgres, redis,
neo4j, gunicorn API) are running for the current user+machine pair, then
injects their dynamically-allocated ports into os.environ so skill scripts
connect to the right instance.

Queries the Discovery Server REST API which tracks all port allocations and
session state.  If the server is not running, invokes singularity/start.sh to
start it, then retries.  Falls back to .env defaults if start.sh fails.

Copyright 2025-2026 Intel Corporation
Licensed under the Apache License, Version 2.0
"""

from __future__ import annotations

import json
import os
import socket
import sys
import urllib.request
from pathlib import Path


def apply_session_ports(repo_root: Path) -> None:
    """Ensure backend is running and inject its port assignments into os.environ."""

    _user = os.environ.get("USER") or os.environ.get("LOGNAME", "")
    if not _user:
        return
    try:
        _host = socket.gethostname().split(".")[0]
    except Exception:
        _host = "localhost"
    _session_key = f"{_user}@{_host}"
    _discovery_file = repo_root / ".potpie-sessions" / f"{_session_key}.discovery"

    # -- Helpers --------------------------------------------------------------

    def _http_get(url: str) -> dict | None:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                return json.loads(resp.read())
        except Exception:
            return None

    def _apply_from_session(s: dict) -> None:
        if s.get("postgres_server"):
            os.environ["POSTGRES_SERVER"] = s["postgres_server"]
        if s.get("neo4j_uri"):
            os.environ["NEO4J_URI"] = s["neo4j_uri"]
        if s.get("redis_url"):
            os.environ["REDIS_URL"] = s["redis_url"]
        redis_port = (s.get("ports") or {}).get("redis")
        if redis_port:
            os.environ["REDISPORT"] = str(redis_port)

    def _start_backend() -> None:
        _sh = repo_root / "singularity" / "start.sh"
        if not _sh.exists():
            print("[potpie] singularity/start.sh not found -- cannot auto-start backend",
                  file=sys.stderr)
            return
        print("[potpie] Starting backend services via singularity/start.sh ...",
              file=sys.stderr)
        import subprocess as _sp
        _sp.run(["bash", str(_sh)], cwd=str(repo_root))

    def _get_discovery_port() -> int | None:
        if not _discovery_file.exists():
            return None
        try:
            meta = json.loads(_discovery_file.read_text())
            port = meta.get("port")
            pid  = meta.get("pid")
            if not port or not pid:
                return None
            os.kill(pid, 0)  # raises if PID gone
            return port
        except Exception:
            return None

    # -- Query Discovery Server -----------------------------------------------

    port = _get_discovery_port()
    if port is None:
        print("[potpie] Discovery Server not running -- starting backend...", file=sys.stderr)
        _start_backend()
        port = _get_discovery_port()

    if port is None:
        return  # fall back to .env defaults

    session = _http_get(f"http://127.0.0.1:{port}/session/{_session_key}")
    if session is None:
        print("[potpie] Session not found in Discovery Server -- starting backend...",
              file=sys.stderr)
        _start_backend()
        port = _get_discovery_port()
        if port is None:
            return
        session = _http_get(f"http://127.0.0.1:{port}/session/{_session_key}")

    if session is None:
        return  # fall back to .env defaults

    _apply_from_session(session)
