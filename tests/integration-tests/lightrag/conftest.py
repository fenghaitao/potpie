"""
Local conftest for lightrag integration tests.

Overrides the session-scoped autouse fixtures from tests/conftest.py
(setup_test_database, require_github_tokens) so this folder can run
standalone without a Postgres instance or GitHub tokens.
"""
from __future__ import annotations

import pytest


# ── override parent autouse fixtures ─────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """No-op: lightrag tests don't need a test database."""
    yield


@pytest.fixture(scope="session", autouse=True)
def require_github_tokens():
    """No-op: lightrag tests don't need GitHub tokens."""
    yield
