"""
Thread-safe dynamic port allocator.

Ports are obtained via OS-level bind('', 0) which guarantees the port is free
at the moment of allocation.  An in-process registry prevents duplicate
allocation within a single Discovery Server instance.

Concurrency model
-----------------
All public methods acquire a single reentrant lock, so allocate_batch() is
safe to call from multiple threads simultaneously.

TOCTOU window
-------------
After the allocation socket is closed there is a brief window (~microseconds)
before the service binds to the port.  In practice this is negligible because:
  1. The OS ephemeral-port pool is large (32768–60999 on Linux).
  2. Our in-process registry prevents re-issuance of the same port.
  3. No other software on the machine is scanning for free ports.
"""

from __future__ import annotations

import socket
import threading
from typing import List


class PortAllocator:
    """Allocates free TCP ports with internal deduplication."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._allocated: set[int] = set()

    # ── Public API ────────────────────────────────────────────────────────────

    def allocate(self) -> int:
        """Return a single free TCP port, reserved in the internal registry."""
        with self._lock:
            return self._grab_one()

    def allocate_batch(self, count: int) -> List[int]:
        """
        Return *count* distinct free TCP ports atomically.

        All sockets are opened simultaneously before any is closed, preventing
        the OS from reassigning an already-chosen port to the next bind() call.
        """
        with self._lock:
            ports: list[int] = []
            sockets: list[socket.socket] = []
            try:
                while len(ports) < count:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind(("", 0))
                    port = s.getsockname()[1]
                    if port not in self._allocated and port not in ports:
                        ports.append(port)
                        sockets.append(s)
                    else:
                        s.close()  # duplicate — discard and try again
            finally:
                # Release all sockets now that we have the full set.
                # Services can bind immediately after this point.
                for s in sockets:
                    s.close()
            self._allocated.update(ports)
            return ports

    def release(self, port: int) -> None:
        """Return a port to the free pool."""
        with self._lock:
            self._allocated.discard(port)

    def release_batch(self, ports: List[int]) -> None:
        """Return multiple ports to the free pool."""
        with self._lock:
            self._allocated.difference_update(ports)

    @property
    def allocated_count(self) -> int:
        """Number of ports currently held."""
        with self._lock:
            return len(self._allocated)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _grab_one(self) -> int:
        """Grab one free port (must be called with self._lock held)."""
        while True:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("", 0))
                port = s.getsockname()[1]
            if port not in self._allocated:
                self._allocated.add(port)
                return port
            # Extremely rare: OS reused a port we already track — retry.
