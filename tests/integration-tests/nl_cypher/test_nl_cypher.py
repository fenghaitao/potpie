"""
Integration test: NL → Cypher → real Neo4j.

Uses github_copilot/gpt-4o via LiteLLMModel (no DB / ProviderService needed).

Usage (from potpie/ root):
    # by repo name:
    .venv/bin/pytest tests/integration-tests/nl_cypher/ -v --repo device-modeling-language

    # by project UUID:
    NL_CYPHER_PROJECT_ID=<uuid> .venv/bin/pytest tests/integration-tests/nl_cypher/ -v

    # standalone (no pytest):
    .venv/bin/python tests/integration-tests/nl_cypher/test_nl_cypher.py --repo device-modeling-language
    .venv/bin/python tests/integration-tests/nl_cypher/test_nl_cypher.py --project-id <uuid>
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_ROOT))

# ── NL questions ──────────────────────────────────────────────────────────────

NL_QUERIES = [
    ("count_functions",  "How many functions are in this project?"),
    ("list_files",       "List all the files in this project."),
    ("main_entry_calls", "What functions does the main entry point call?"),
    ("list_classes",     "List all classes in this project."),
    ("fn_references",    "Which functions reference other functions?"),
]

pytestmark = pytest.mark.neo4j_live


# ── shared setup helpers ──────────────────────────────────────────────────────

def _make_cypher_generator():
    """Build a CypherGenerator with LiteLLMModel injected — no DB needed."""
    from pydantic_ai import Agent
    from pydantic_ai_skills import SkillsToolset
    from pydantic_ai_skills.directory import SkillsDirectory
    from app.modules.intelligence.provider.cypher_generator import CypherGenerator
    from app.modules.intelligence.provider.litellm_model import LiteLLMModel

    extra_headers: dict = {}
    raw = os.environ.get("LLM_EXTRA_HEADERS", "")
    if raw:
        try:
            extra_headers = json.loads(raw)
        except Exception:
            pass

    model = LiteLLMModel("github_copilot/gpt-4o", extra_headers)

    skills_dir = SkillsDirectory(path=str(_ROOT / ".kiro" / "skills"))
    toolset = SkillsToolset(directories=[skills_dir])

    gen = object.__new__(CypherGenerator)
    gen._toolset = toolset
    gen._agent = Agent(
        model=model,
        instructions="You are a Neo4j Cypher expert. Use the nl-cypher skill.",
        toolsets=[toolset],
    )

    @gen._agent.instructions
    async def add_skill_instructions(ctx) -> str | None:
        return await toolset.get_instructions(ctx)

    return gen


def _make_neo4j_driver():
    from neo4j import GraphDatabase
    return GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    )


def _execute(driver, cypher: str, project_id: str) -> list[dict]:
    with driver.session() as session:
        result = session.run(cypher, project_id=project_id)
        return [dict(r) for r in result]


# ── pytest fixtures ───────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def neo4j_driver():
    """Real Neo4j driver — skips if env vars are absent."""
    if not all(os.environ.get(k) for k in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD")):
        pytest.skip("NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD not set")
    driver = _make_neo4j_driver()
    yield driver
    driver.close()


@pytest.fixture(scope="module")
def project_id(resolved_project_id):
    return resolved_project_id


@pytest.fixture(scope="module")
def cypher_generator():
    return _make_cypher_generator()


# ── tests ─────────────────────────────────────────────────────────────────────

# Queries that must return at least one result for any non-empty project
_MUST_HAVE_RESULTS = {"count_functions", "list_files", "list_classes", "fn_references"}


@pytest.mark.asyncio
@pytest.mark.parametrize("label,nl_query", NL_QUERIES)
async def test_nl_to_cypher_and_execute(label, nl_query, cypher_generator, neo4j_driver, project_id):
    """Each NL query must produce valid Cypher that executes without error and returns data."""
    cypher = await cypher_generator.generate(nl_query)

    assert "MATCH" in cypher.upper(), f"[{label}] No MATCH in generated Cypher: {cypher!r}"
    assert "$project_id" in cypher, f"[{label}] Missing $project_id in Cypher: {cypher!r}"

    rows = _execute(neo4j_driver, cypher, project_id)
    assert isinstance(rows, list)

    if label in _MUST_HAVE_RESULTS:
        assert len(rows) > 0, f"[{label}] Expected results but got none. Cypher: {cypher!r}"

    print(f"\n[{label}] rows={len(rows)}  cypher={cypher!r}")


# ── standalone entry point ────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import asyncio

    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env", override=False)

    parser = argparse.ArgumentParser(description="NL→Cypher integration test")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--repo", help="Repo name to resolve project ID from")
    group.add_argument("--project-id", help="Neo4j project UUID")
    args = parser.parse_args()

    async def _resolve_repo(repo_name: str) -> str:
        from potpie.runtime import PotpieRuntime
        runtime = PotpieRuntime.from_env()
        await runtime.initialize()
        try:
            user_id = os.environ.get("POTPIE_USER_ID", "defaultuser")
            projects = await runtime.projects.list(user_id=user_id)
            matches = [p for p in projects if p.repo_name == repo_name]
            if not matches:
                print(f"[ERROR] No project found with repo_name='{repo_name}'", file=sys.stderr)
                sys.exit(1)
            return matches[0].id
        finally:
            await runtime.close()

    if args.project_id:
        pid = args.project_id
    elif args.repo:
        pid = asyncio.run(_resolve_repo(args.repo))
    else:
        pid = os.environ.get("NL_CYPHER_PROJECT_ID")
        if not pid:
            parser.error("Provide --repo, --project-id, or set NL_CYPHER_PROJECT_ID")

    gen = _make_cypher_generator()
    driver = _make_neo4j_driver()

    async def run():
        passed = failed = 0
        print(f"\n{'='*60}\n  NL→Cypher  project={pid}\n{'='*60}\n")
        for label, nl_query in NL_QUERIES:
            print(f"[{label}] {nl_query!r}")
            try:
                cypher = await gen.generate(nl_query)
                rows = _execute(driver, cypher, pid)
                runnable = cypher.replace("$project_id", f'"{pid}"')
                print(f"  cypher : {cypher}")
                print(f"  neo4j  : {runnable}")
                print(f"  rows   : {len(rows)}" + (f"  sample={rows[0]}" if rows else ""))
                print(f"  ✓ PASS\n")
                passed += 1
            except Exception as e:
                print(f"  ✗ FAIL — {e}\n")
                failed += 1
        driver.close()
        print(f"{'='*60}\n  {passed} passed, {failed} failed\n{'='*60}\n")
        if failed:
            sys.exit(1)

    asyncio.run(run())
