"""
Local conftest for nl_cypher integration tests.

Overrides the session-scoped autouse fixtures from tests/conftest.py
(setup_test_database, require_github_tokens) so this folder can run
standalone without a Postgres instance or GitHub tokens.

Adds --repo CLI option so the project ID can be resolved by repo name:
    pytest tests/integration-tests/nl_cypher/ -v --repo device-modeling-language
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent.parent


# ── override parent autouse fixtures ─────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """No-op: nl_cypher tests don't need a test database."""
    yield


@pytest.fixture(scope="session", autouse=True)
def require_github_tokens():
    """No-op: nl_cypher tests don't need GitHub tokens."""
    yield


# ── --repo CLI option ─────────────────────────────────────────────────────────

def pytest_addoption(parser):
    parser.addoption(
        "--repo",
        default=None,
        help="Repo name to resolve project ID from (e.g. device-modeling-language). "
             "Takes precedence over NL_CYPHER_PROJECT_ID env var.",
    )


@pytest.fixture(scope="session")
def resolved_project_id(request):
    """
    Resolve project ID from --repo arg or NL_CYPHER_PROJECT_ID env var.
    Skips the session if neither is available.
    """
    repo = request.config.getoption("--repo")
    if repo:
        from dotenv import load_dotenv
        load_dotenv(_ROOT / ".env", override=False)
        return _resolve_by_repo(repo)

    pid = os.environ.get("NL_CYPHER_PROJECT_ID")
    if pid:
        return pid

    pytest.skip(
        "No project specified. Use --repo <name> or set NL_CYPHER_PROJECT_ID."
    )


def _resolve_by_repo(repo_name: str) -> str:
    async def _lookup():
        from potpie.runtime import PotpieRuntime
        runtime = PotpieRuntime.from_env()
        await runtime.initialize()
        try:
            user_id = os.environ.get("POTPIE_USER_ID", "defaultuser")
            projects = await runtime.projects.list(user_id=user_id)
            matches = [p for p in projects if p.repo_name == repo_name]
            if not matches:
                pytest.fail(f"No project found with repo_name='{repo_name}'")
            return matches[0].id
        finally:
            await runtime.close()

    return asyncio.run(_lookup())
