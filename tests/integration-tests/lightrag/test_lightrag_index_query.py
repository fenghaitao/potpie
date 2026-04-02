"""
Integration test: index a local repo with LightRAG, then query it.

Steps:
  1. Run `spec-graph index --repo dmlc-md/`  (indexes DML_1.4_Specification.md)
  2. Run `spec-graph query "Tell me about dmlc"`
  3. Assert the answer is substantive

Usage (from potpie/ root):
    .venv/bin/pytest tests/integration-tests/lightrag/ -v

    # standalone (no pytest):
    .venv/bin/python tests/integration-tests/lightrag/test_lightrag_index_query.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent.parent
_SKILL_DIR = _ROOT / ".github" / "skills" / "lightrag-apps"
_REPO_DIR = Path(__file__).parent / "dmlc-md"

pytestmark = pytest.mark.lightrag_live


# ── helpers ───────────────────────────────────────────────────────────────────

def _uv_run(skill_dir: Path, *args, timeout: int = 300) -> subprocess.CompletedProcess:
    """Run a spec-graph sub-command via uv inside the skill's virtual environment."""
    cmd = ["uv", "run", "--directory", str(skill_dir), "spec-graph", *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _extract_query_answer(stdout: str) -> str:
    """Return the text that follows the QUERY RESULT section header."""
    return stdout.split("QUERY RESULT")[-1].strip().lstrip("=").strip()


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def skill_dir():
    if not _SKILL_DIR.exists():
        pytest.skip(f"lightrag-apps skill not found at: {_SKILL_DIR}")
    return _SKILL_DIR


@pytest.fixture(scope="module")
def repo_dir():
    if not _REPO_DIR.exists():
        pytest.skip(f"Test repo not found at: {_REPO_DIR}")
    return _REPO_DIR


@pytest.fixture(scope="module")
def graph_dir(tmp_path_factory, skill_dir, repo_dir):
    """
    Index dmlc-md/ into a temporary graph directory and return that path.
    The index is built once per test module (scope='module').
    """
    working_dir = tmp_path_factory.mktemp("lightrag-graph")

    result = _uv_run(
        skill_dir,
        "index",
        "--repo", str(repo_dir),
        "--working-dir", str(working_dir),
    )

    assert result.returncode == 0, (
        f"spec-graph index failed (exit {result.returncode}).\n"
        f"  stdout: {result.stdout[:600]}\n"
        f"  stderr: {result.stderr[:600]}"
    )
    assert "Indexing complete" in result.stdout or "indexed" in result.stdout.lower(), (
        f"Indexing output looks unexpected.\n  stdout: {result.stdout[:600]}"
    )

    return working_dir


# ── test ──────────────────────────────────────────────────────────────────────

def test_index_then_query_dmlc(graph_dir, skill_dir):
    """Index dmlc-md/ and ask 'Tell me about dmlc'; expect a substantive answer."""
    query = "Tell me about dmlc"

    result = _uv_run(
        skill_dir,
        "query",
        "-s", str(graph_dir),
        "--mode", "hybrid",
        query,
    )

    assert result.returncode == 0, (
        f"spec-graph query failed (exit {result.returncode}).\n"
        f"  stderr: {result.stderr[:500]!r}"
    )
    assert "QUERY RESULT" in result.stdout, (
        f"Expected 'QUERY RESULT' marker in output.\n"
        f"  stdout: {result.stdout[:500]!r}"
    )

    answer = _extract_query_answer(result.stdout)
    assert len(answer) >= 50, (
        f"Query result looks too short (< 50 chars).\n  answer: {answer!r}"
    )

    # The answer should mention DML at least once (case-insensitive)
    assert "dml" in answer.lower(), (
        f"Answer does not mention DML.\n  answer: {answer[:500]!r}"
    )

    print(f"\n[test_index_then_query_dmlc] answer ({len(answer)} chars):\n{answer[:400]}")


# ── standalone entry point ────────────────────────────────────────────────────

if __name__ == "__main__":
    if not _SKILL_DIR.exists():
        print(f"[ERROR] lightrag-apps skill not found at: {_SKILL_DIR}", file=sys.stderr)
        sys.exit(1)
    if not _REPO_DIR.exists():
        print(f"[ERROR] Test repo not found at: {_REPO_DIR}", file=sys.stderr)
        sys.exit(1)

    import tempfile

    with tempfile.TemporaryDirectory(prefix="lightrag-graph-") as tmp:
        working_dir = Path(tmp)
        print(f"\n{'='*60}\n  LightRAG index+query  repo={_REPO_DIR}\n{'='*60}\n")

        # Step 1: index
        print(f"[1/2] Indexing {_REPO_DIR} ...")
        r = _uv_run(_SKILL_DIR, "index", "--repo", str(_REPO_DIR), "--working-dir", str(working_dir))
        if r.returncode != 0:
            print(f"  ✗ FAIL — exit {r.returncode}\n{r.stderr[:400]}")
            sys.exit(1)
        print(f"  ✓ Index OK\n{r.stdout[-300:]}")

        # Step 2: query
        query = "Tell me about dmlc"
        print(f"[2/2] Querying: {query!r} ...")
        r = _uv_run(_SKILL_DIR, "query", "-s", str(working_dir), "--mode", "hybrid", query)
        if r.returncode != 0:
            print(f"  ✗ FAIL — exit {r.returncode}\n{r.stderr[:400]}")
            sys.exit(1)

        answer = _extract_query_answer(r.stdout)
        if len(answer) < 50 or "dml" not in answer.lower():
            print(f"  ✗ FAIL — answer too short or off-topic: {answer[:300]!r}")
            sys.exit(1)

        print(f"  ✓ PASS\n  answer ({len(answer)} chars):\n{answer[:400]}")
        print(f"\n{'='*60}\n  1 passed\n{'='*60}\n")
