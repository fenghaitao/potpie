"""
Shared runtime helper for potpie skill scripts.

apply_session_ports(repo_root) -- checks whether all backend services are
healthy for the current user+machine pair, starts them via singularity/start.sh
if they are not, then injects the dynamically-allocated ports into os.environ.

Flow:
  1. Probe the Discovery Server.
  2. If it responds and all services are healthy → apply ports, return.
  3. Otherwise → invoke singularity/start.sh (which handles the full
     start-or-reuse logic) and retry once.
  4. If still unhealthy → fall back to .env defaults (non-fatal for skills).

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
    """Check service health, auto-start if needed, inject ports into os.environ."""

    _user = os.environ.get("USER") or os.environ.get("LOGNAME", "")
    if not _user:
        return
    try:
        _host = socket.gethostname().split(".")[0]
    except Exception:
        _host = "localhost"
    _session_key = f"{_user}@{_host}"
    _discovery_file = repo_root / ".potpie-sessions" / f"{_session_key}.discovery"

    # ── helpers ───────────────────────────────────────────────────────────────

    def _http_get(url: str, timeout: int = 5) -> dict | None:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return json.loads(resp.read())
        except Exception:
            return None

    def _port_open(port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                return True
        except OSError:
            return False

    def _get_discovery_port() -> int | None:
        if not _discovery_file.exists():
            return None
        try:
            meta = json.loads(_discovery_file.read_text())
            port = meta.get("port")
            pid  = meta.get("pid")
            if not port or not pid:
                return None
            os.kill(pid, 0)   # raises if PID gone
            return port
        except Exception:
            return None

    def _apply_from_session(s: dict) -> None:
        if s.get("postgres_server"):
            os.environ["POSTGRES_SERVER"] = s["postgres_server"]
        if s.get("neo4j_uri"):
            os.environ["NEO4J_URI"] = s["neo4j_uri"]
        if s.get("redis_url"):
            os.environ["BROKER_URL"] = s["redis_url"]
        ports = s.get("ports") or {}
        if ports.get("redis"):
            os.environ["REDISPORT"] = str(ports["redis"])
            os.environ["REDISHOST"] = "127.0.0.1"

    def _all_healthy(session: dict) -> bool:
        ports = session.get("ports") or {}
        api_port = ports.get("api")
        return (
            _port_open(ports.get("postgres", 0))
            and _port_open(ports.get("redis", 0))
            and _port_open(ports.get("neo4j_bolt", 0))
            and bool(api_port and _http_get(f"http://127.0.0.1:{api_port}/health"))
        )

    def _start_backend() -> None:
        # Never auto-start in CI or test environments — start.sh can hang indefinitely.
        if os.environ.get("CI") or os.environ.get("PYTEST_CURRENT_TEST"):
            print("[potpie] CI/test environment detected — skipping auto-start of backend",
                  file=sys.stderr)
            return
        _sh = repo_root / "singularity" / "start.sh"
        if not _sh.exists():
            print("[potpie] singularity/start.sh not found — cannot auto-start backend",
                  file=sys.stderr)
            return
        print("[potpie] Starting backend services via singularity/start.sh ...",
              file=sys.stderr)
        import subprocess as _sp
        try:
            _sp.run(["bash", str(_sh)], cwd=str(repo_root), timeout=300)
        except _sp.TimeoutExpired:
            print("[potpie] start.sh timed out after 300 s — continuing without backend",
                  file=sys.stderr)

    # ── 1. probe existing session ─────────────────────────────────────────────

    disco_port = _get_discovery_port()
    if disco_port is not None:
        session = _http_get(f"http://127.0.0.1:{disco_port}/session/{_session_key}")
        if session is not None and _all_healthy(session):
            _apply_from_session(session)
            return

    # ── 2. not running or unhealthy → start backend ───────────────────────────

    print("[potpie] Backend not healthy — starting via singularity/start.sh ...",
          file=sys.stderr)
    _start_backend()

    # ── 3. retry once after start ─────────────────────────────────────────────

    disco_port = _get_discovery_port()
    if disco_port is None:
        return  # fall back to .env defaults
    session = _http_get(f"http://127.0.0.1:{disco_port}/session/{_session_key}")
    if session is None:
        return  # fall back to .env defaults

    _apply_from_session(session)
