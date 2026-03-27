"""
Lightweight synchronous client for the Potpie Discovery Server.

No third-party dependencies — uses only stdlib urllib so it can be imported
before any virtualenv is activated (e.g. from potpie_cli.py's bootstrap code).

Typical usage
-------------
from potpie.discovery.client import DiscoveryClient

client = DiscoveryClient.find(repo_root=Path("/path/to/repo"))
if client:
    info = client.get_session("user@host")
    if info:
        os.environ["POSTGRES_SERVER"] = info["postgres_server"]
        ...
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional


# ── Discovery-server locator ──────────────────────────────────────────────────

def _read_discovery_file(repo_root: Path, session_key: str) -> Optional[dict]:
    """
    Read the per-user-per-machine discovery metadata file.

    File path: <repo>/.potpie-sessions/<user>@<host>.discovery
    Content:   {"port": <int>, "pid": <int>}
    """
    disco_file = repo_root / ".potpie-sessions" / f"{session_key}.discovery"
    if not disco_file.exists():
        return None
    try:
        return json.loads(disco_file.read_text())
    except Exception:
        return None


def _discovery_alive(port: int, pid: int) -> bool:
    """Return True if the Discovery Server process is running and healthy."""
    # Check PID first (fast path)
    try:
        os.kill(pid, 0)  # signal 0 = existence check
    except (ProcessLookupError, PermissionError):
        return False  # PID gone

    # Then check HTTP health
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/health", timeout=3
        ) as resp:
            return resp.status == 200
    except Exception:
        return False


# ── Client ────────────────────────────────────────────────────────────────────


class DiscoveryClient:
    """
    Thin HTTP wrapper around the Discovery Server REST API.

    All methods return plain dicts (parsed JSON) or None on errors so that
    callers can be written without exception handling.
    """

    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def find(cls, repo_root: Path, session_key: Optional[str] = None) -> Optional["DiscoveryClient"]:
        """
        Locate the Discovery Server for the current user@host and return a
        client pointed at it.  Returns None if not running.
        """
        if session_key is None:
            user = os.environ.get("USER") or os.environ.get("LOGNAME", "")
            try:
                host = socket.gethostname().split(".")[0]
            except Exception:
                host = "localhost"
            session_key = f"{user}@{host}"

        meta = _read_discovery_file(repo_root, session_key)
        if meta is None:
            return None

        port = meta.get("port")
        pid = meta.get("pid")
        if not port or not pid:
            return None

        if not _discovery_alive(port, pid):
            return None

        return cls(f"http://127.0.0.1:{port}")

    # ── API methods ───────────────────────────────────────────────────────────

    def health(self) -> Optional[dict]:
        return self._get("/health")

    def list_sessions(self) -> Optional[list]:
        return self._get("/sessions")  # type: ignore[return-value]

    def get_session(self, session_id: str) -> Optional[dict]:
        return self._get(f"/session/{session_id}")

    def create_session(self, session_id: str, user: str, host: str) -> Optional[dict]:
        body = json.dumps(
            {"session_id": session_id, "user": user, "host": host}
        ).encode()
        return self._post("/session", body)

    def register_pids(self, session_id: str, pids: dict) -> Optional[dict]:
        body = json.dumps({"pids": pids}).encode()
        return self._post(f"/session/{session_id}/register", body)

    def heartbeat(self, session_id: str) -> Optional[dict]:
        return self._post(f"/session/{session_id}/heartbeat", b"")

    def delete_session(self, session_id: str) -> Optional[dict]:
        return self._delete(f"/session/{session_id}")

    # ── HTTP helpers (no third-party dependencies) ────────────────────────────

    def _get(self, path: str) -> Optional[dict]:
        try:
            with urllib.request.urlopen(
                urllib.request.Request(
                    f"{self._base}{path}",
                    headers={"Accept": "application/json"},
                ),
                timeout=5,
            ) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise
        except Exception:
            return None

    def _post(self, path: str, body: bytes) -> Optional[dict]:
        try:
            req = urllib.request.Request(
                f"{self._base}{path}",
                data=body or b"{}",
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise
        except Exception:
            return None

    def _delete(self, path: str) -> Optional[dict]:
        try:
            req = urllib.request.Request(
                f"{self._base}{path}", method="DELETE"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise
        except Exception:
            return None
