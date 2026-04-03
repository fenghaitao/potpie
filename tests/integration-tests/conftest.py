"""
Conftest for integration tests.

Overrides the heavy session-scoped fixtures from the parent tests/conftest.py
(which imports app.main and sets up a test database) so that integration tests
can run without a database and without leaving background threads that prevent
pytest from exiting cleanly.
"""

import os
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """No-op override: integration tests drive the backend via CLI, not directly."""
    yield


@pytest.fixture(scope="session")
def potpie_cli_runner():
    """Provides a callable to run potpie_cli commands within integration tests."""
    cli_script_path = Path(__file__).parent.parent.parent / "potpie_cli.py"

    def run_cli(*args, check=True, cwd=None):
        import subprocess

        cmd = [sys.executable, str(cli_script_path), *args]
        print(f'Running CLI command: {" ".join(cmd)}  (cwd={cwd})', flush=True)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
            cwd=cwd,
        )
        return result

    return run_cli


def pytest_sessionfinish(session, exitstatus):
    """Force-exit to prevent background threads (Redis/Socket.IO from app imports)
    from keeping the process alive after the integration test session ends."""
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(int(exitstatus))
