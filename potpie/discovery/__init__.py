"""
Potpie Discovery Server — central session and port management.

The Discovery Server is a lightweight FastAPI process (one per user per machine)
that owns the port registry for all backend services (Postgres, Redis, Neo4j, API)
and tracks session lifecycle with heartbeat-based TTL cleanup.

Usage (from singularity/start.sh):
    python -m potpie.discovery --port-file /tmp/discovery.port &

Usage (from client code):
    from potpie.discovery.client import DiscoveryClient
    client = DiscoveryClient.from_session_dir(repo_root)
    info = client.get_session("user@host")
"""

from .server import create_app, find_free_discovery_port
from .session_manager import SessionManager
from .port_allocator import PortAllocator

__all__ = [
    "create_app",
    "find_free_discovery_port",
    "SessionManager",
    "PortAllocator",
]
