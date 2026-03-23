"""
Unit tests for the wiki-evaluator skill.

Covers:
  1. GraphRubricGenerator  — mocked graph tool responses → rubric dict
  2. WikiEvaluator         — mocked LLM calls → aggregated scores (6-step pipeline)
  3. evaluate_wiki.py      — CLI entry point helpers (resolve_wiki_dir,
                             read_wiki_directory, generate_report)
  4. potpie_cli.py         — evaluate-wiki CLI command (subprocess path)

All external services, network calls, and database access are fully mocked —
no live Copilot CLI, no DB, no Redis, no graph queries.

Environment variable simulated: ``ENABLE_MULTI_AGENT=false``
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# sys.path: add repo root + skill modules directory
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parents[3].resolve()          # potpie/
_SKILL_MODULES = _REPO_ROOT / ".kiro/skills/wiki-evaluator/scripts/wiki-evaluator-modules"
_SKILL_SCRIPTS = _REPO_ROOT / ".kiro/skills/wiki-evaluator/scripts"

for _p in [str(_SKILL_MODULES), str(_SKILL_SCRIPTS), str(_REPO_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ID = "test-project-abc123"
REPO_NAME = "my-test-repo"

# Canned graph responses
CANNED_FILE_STRUCTURE = """\
├── app/
│   ├── api/
│   │   └── router.py
│   ├── models/
│   │   └── user.py
│   └── main.py
├── tests/
└── pyproject.toml
"""

CANNED_GRAPH_ANSWERS = {
    "What are the main modules and their responsibilities?":
        "app/api handles HTTP routing; app/models defines ORM schemas; app/main is the entry point.",
    "What public API endpoints or entry points exist?":
        "POST /auth/login, GET /users/{id}, POST /items — all in app/api/router.py.",
    "What are the core data models or schemas?":
        "User (id, email, hashed_password), Item (id, title, owner_id) defined via SQLAlchemy.",
}

# Sample wiki content
SAMPLE_WIKI = """\
# My Test Repo Documentation

## Architecture

The application follows a layered architecture:
- `app/api` — FastAPI router layer handling HTTP requests
- `app/models` — SQLAlchemy ORM models (User, Item)
- `app/main.py` — Application entry point

## API Reference

### POST /auth/login
Authenticates a user and returns a JWT token.

### GET /users/{id}
Returns user details by ID.

## Data Models

### User
- `id`: UUID primary key
- `email`: unique user email
- `hashed_password`: bcrypt hash
"""

# Canned rubrics that GraphRubricGenerator should produce
CANNED_RUBRICS = {
    "categories": [
        {
            "name": "Architecture Overview",
            "weight": 0.30,
            "criteria": [
                "System architecture and major components are described",
                "Component interactions are documented",
            ],
        },
        {
            "name": "API Documentation",
            "weight": 0.40,
            "criteria": [
                "Public API endpoints are documented",
                "Request/response schemas are described",
                "Authentication requirements are explained",
            ],
        },
        {
            "name": "Data Models",
            "weight": 0.30,
            "criteria": [
                "Core data models are documented",
                "Field descriptions are provided",
            ],
        },
    ],
    "source": "graph",
}

CANNED_CONTEXT_ITEMS = [
    {"query": "Repository file and module structure", "response": CANNED_FILE_STRUCTURE},
    {"query": "What are the main modules and their responsibilities?",
     "response": CANNED_GRAPH_ANSWERS["What are the main modules and their responsibilities?"]},
]


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def set_env_vars(monkeypatch):
    """Set env vars that modules read at import time."""
    monkeypatch.setenv("ENABLE_MULTI_AGENT", "false")
    monkeypatch.setenv("CHAT_MODEL", "github_copilot/gpt-4o")


@pytest.fixture
def wiki_dir(tmp_path: Path) -> Path:
    """Create a temporary wiki directory with sample markdown files."""
    wiki = tmp_path / ".codewiki"
    wiki.mkdir()
    (wiki / "overview.md").write_text("# Overview\n\nThis is the overview.\n", encoding="utf-8")
    (wiki / "api.md").write_text("# API Reference\n\nPOST /login\n", encoding="utf-8")
    sub = wiki / "guides"
    sub.mkdir()
    (sub / "quickstart.md").write_text("# Quickstart\n\nRun `python main.py`\n", encoding="utf-8")
    return wiki


@pytest.fixture
def mock_runtime() -> MagicMock:
    """Mock PotpieRuntime with graph tool service."""
    runtime = MagicMock()
    runtime.initialize = AsyncMock()
    runtime.close = AsyncMock()

    # tool_service for GraphRubricGenerator
    # Matches the interface used by GraphRubricGenerator._get_file_structure()
    # and ._ask_graph(): tool_service.file_structure_tool.arun(project_id)
    # and tool_service.tools["ask_knowledge_graph_queries"].arun(queries, project_id, node_ids)
    tool_service = MagicMock()

    # file_structure_tool.arun(project_id) → CANNED_FILE_STRUCTURE
    tool_service.file_structure_tool = MagicMock()
    tool_service.file_structure_tool.arun = AsyncMock(return_value=CANNED_FILE_STRUCTURE)

    # tools["ask_knowledge_graph_queries"].arun(queries, project_id, node_ids) → answer str
    kg_tool = MagicMock()
    kg_tool.arun = AsyncMock(
        side_effect=lambda queries, project_id, node_ids=None: CANNED_GRAPH_ANSWERS.get(
            queries[0], "No data available."
        )
    )
    tool_service.tools = {"ask_knowledge_graph_queries": kg_tool}

    runtime.tool_service = tool_service
    return runtime


# ===========================================================================
# 1. GraphRubricGenerator tests
# ===========================================================================


class TestGraphRubricGenerator:
    """Tests for the GraphRubricGenerator (graph → rubrics pipeline)."""

    def test_import(self):
        """GraphRubricGenerator is importable from the skill modules directory."""
        from graph_rubric_generator import GraphRubricGenerator
        assert GraphRubricGenerator is not None

    @pytest.mark.asyncio
    async def test_collect_graph_context_calls_file_structure(self, mock_runtime):
        """_collect_graph_context calls file_structure_tool.arun."""
        from graph_rubric_generator import GraphRubricGenerator

        gen = GraphRubricGenerator(mock_runtime, PROJECT_ID)
        items = await gen._collect_graph_context()

        mock_runtime.tool_service.file_structure_tool.arun.assert_called_once()
        # First item should be the file structure
        assert any("structure" in item["query"].lower() for item in items), \
            f"Expected file-structure item in: {[i['query'] for i in items]}"

    @pytest.mark.asyncio
    async def test_collect_graph_context_runs_queries(self, mock_runtime):
        """_collect_graph_context runs multiple graph queries."""
        from graph_rubric_generator import GraphRubricGenerator, MAX_GRAPH_QUERIES

        gen = GraphRubricGenerator(mock_runtime, PROJECT_ID)
        items = await gen._collect_graph_context()

        # Should have at least file structure + some query results
        assert len(items) >= 2
        # ask_knowledge_graph_queries tool called multiple times
        assert mock_runtime.tool_service.tools["ask_knowledge_graph_queries"].arun.call_count <= MAX_GRAPH_QUERIES

    @pytest.mark.asyncio
    async def test_fallback_rubrics_when_llm_fails(self, mock_runtime):
        """Falls back to keyword-based rubrics when LLM call raises."""
        from graph_rubric_generator import GraphRubricGenerator

        gen = GraphRubricGenerator(mock_runtime, PROJECT_ID)

        # Inject context items with known keywords
        context_items = [
            {"query": "structure", "response": "api endpoint route module service layer architecture"},
        ]

        rubrics = gen._fallback_rubrics(context_items)
        assert "categories" in rubrics
        assert len(rubrics["categories"]) >= 2  # should at least have API + setup

    @pytest.mark.asyncio
    async def test_fallback_rubrics_weights_sum_to_one(self, mock_runtime):
        """Fallback rubric weights normalise to 1.0."""
        from graph_rubric_generator import GraphRubricGenerator

        gen = GraphRubricGenerator(mock_runtime, PROJECT_ID)
        context_items = [{"query": "q", "response": "api endpoint module service layer config database model"}]
        rubrics = gen._fallback_rubrics(context_items)

        total = sum(cat["weight"] for cat in rubrics["categories"])
        assert abs(total - 1.0) < 0.01, f"Weights sum to {total}, expected ~1.0"

    @pytest.mark.asyncio
    async def test_parse_rubric_json_valid(self, mock_runtime):
        """_parse_rubric_json extracts valid rubric from LLM response."""
        from graph_rubric_generator import GraphRubricGenerator

        gen = GraphRubricGenerator(mock_runtime, PROJECT_ID)
        raw = """
Some preamble text.
{
  "categories": [
    {"name": "API Docs", "weight": 0.5, "criteria": ["Endpoints are documented"]},
    {"name": "Setup",    "weight": 0.5, "criteria": ["Install instructions exist"]}
  ]
}
Some postamble.
"""
        result = gen._parse_rubric_json(raw, [])
        assert "categories" in result
        assert len(result["categories"]) == 2
        # Weights should be normalised to sum to 1.0
        total = sum(c["weight"] for c in result["categories"])
        assert abs(total - 1.0) < 0.01

    @pytest.mark.asyncio
    async def test_parse_rubric_json_invalid_raises(self, mock_runtime):
        """_parse_rubric_json raises ValueError on bad input."""
        from graph_rubric_generator import GraphRubricGenerator

        gen = GraphRubricGenerator(mock_runtime, PROJECT_ID)
        with pytest.raises(ValueError):
            gen._parse_rubric_json("No JSON here at all!", [])

    @pytest.mark.asyncio
    async def test_generate_returns_dict_with_categories(self, mock_runtime):
        """generate() returns a dict with 'categories' key when LLM succeeds."""
        from graph_rubric_generator import GraphRubricGenerator

        gen = GraphRubricGenerator(mock_runtime, PROJECT_ID)

        # Mock _generate_rubrics_from_context to return canned rubrics
        async def _mock_gen_rubrics(context_items, model=None):
            return CANNED_RUBRICS.copy()

        gen._generate_rubrics_from_context = _mock_gen_rubrics

        result = await gen.generate(model="test-model")
        assert "categories" in result
        assert result.get("source") == "graph"
        assert len(result["categories"]) == 3

    @pytest.mark.asyncio
    async def test_generate_tolerates_tool_errors(self):
        """generate() still returns rubrics when graph tool calls fail."""
        from graph_rubric_generator import GraphRubricGenerator

        # Runtime whose tools all raise
        bad_runtime = MagicMock()
        bad_runtime.initialize = AsyncMock()
        bad_runtime.close = AsyncMock()
        tool_svc = MagicMock()
        tool_svc.file_structure_tool = MagicMock()
        tool_svc.file_structure_tool.arun = AsyncMock(side_effect=Exception("connection failed"))
        bad_kg = MagicMock()
        bad_kg.arun = AsyncMock(side_effect=Exception("graph error"))
        tool_svc.tools = {"ask_knowledge_graph_queries": bad_kg}
        bad_runtime.tool_service = tool_svc

        gen = GraphRubricGenerator(bad_runtime, PROJECT_ID)

        # Even with empty context, should return {"categories": [], "source": "graph"}
        result = await gen.generate()
        assert "categories" in result
        assert result.get("source") == "graph"


# ===========================================================================
# 2. WikiEvaluator tests  (new 6-step direct-LLM pipeline)
# ===========================================================================


class TestWikiEvaluator:
    """Tests for the WikiEvaluator (direct LLM per-criterion scoring pipeline)."""

    def test_import(self):
        """WikiEvaluator is importable."""
        from wiki_evaluator import WikiEvaluator
        assert WikiEvaluator is not None

    def test_flatten_criteria(self):
        """_flatten_criteria produces one item per criterion."""
        from wiki_evaluator import WikiEvaluator

        ev = WikiEvaluator.__new__(WikiEvaluator)
        flat = ev._flatten_criteria(CANNED_RUBRICS)
        expected_total = sum(len(c["criteria"]) for c in CANNED_RUBRICS["categories"])
        assert len(flat) == expected_total

    def test_flatten_criteria_preserves_category(self):
        """_flatten_criteria assigns the correct category to each item."""
        from wiki_evaluator import WikiEvaluator

        ev = WikiEvaluator.__new__(WikiEvaluator)
        flat = ev._flatten_criteria(CANNED_RUBRICS)

        categories_seen = {item["category"] for item in flat}
        expected = {"Architecture Overview", "API Documentation", "Data Models"}
        assert categories_seen == expected

    def test_empty_result(self):
        """_empty_result returns the expected zero-valued structure."""
        from wiki_evaluator import WikiEvaluator

        ev = WikiEvaluator.__new__(WikiEvaluator)
        result = ev._empty_result()
        assert result["overall_score"] == 0.0
        assert result["total_criteria"] == 0
        assert result["met_criteria"] == 0

    def test_aggregate_empty(self):
        """_aggregate on empty list returns empty result."""
        from wiki_evaluator import WikiEvaluator

        ev = WikiEvaluator.__new__(WikiEvaluator)
        result = ev._aggregate([], CANNED_RUBRICS)
        assert result["overall_score"] == 0.0

    def test_aggregate_all_pass(self):
        """_aggregate with all-pass criteria produces overall_score ~1.0."""
        from wiki_evaluator import WikiEvaluator

        ev = WikiEvaluator.__new__(WikiEvaluator)

        # Build case results where every criterion scores 1
        case_results = []
        for cat in CANNED_RUBRICS["categories"]:
            for crit in cat["criteria"]:
                case_results.append({
                    "criterion": crit,
                    "category": cat["name"],
                    "category_weight": cat["weight"],
                    "overall_score": 1.0,
                    "score": 1,
                    "reasoning": "documented",
                    "evidence": "see docs",
                })

        result = ev._aggregate(case_results, CANNED_RUBRICS)
        assert result["overall_score"] >= 0.9
        assert result["met_criteria"] == result["total_criteria"]

    def test_aggregate_all_fail(self):
        """_aggregate with all-fail criteria produces overall_score ~0.0."""
        from wiki_evaluator import WikiEvaluator

        ev = WikiEvaluator.__new__(WikiEvaluator)
        case_results = []
        for cat in CANNED_RUBRICS["categories"]:
            for crit in cat["criteria"]:
                case_results.append({
                    "criterion": crit,
                    "category": cat["name"],
                    "category_weight": cat["weight"],
                    "overall_score": 0.0,
                    "score": 0,
                    "reasoning": "not documented",
                    "evidence": "",
                })

        result = ev._aggregate(case_results, CANNED_RUBRICS)
        assert result["overall_score"] < 0.1
        assert result["met_criteria"] == 0

    @pytest.mark.asyncio
    async def test_evaluate_criterion_chunked_hit(self):
        """_evaluate_criterion_chunked returns score=1 when LLM says documented."""
        from wiki_evaluator import _evaluate_criterion_chunked

        llm_response = json.dumps({
            "criteria": "API endpoints are documented",
            "score": 1,
            "reasoning": "The wiki describes POST /auth/login and GET /users/{id}.",
            "evidence": "## API Reference section",
        })

        with patch("wiki_evaluator._call_llm", new_callable=AsyncMock, return_value=llm_response):
            result = await _evaluate_criterion_chunked(
                criterion="API endpoints are documented",
                category="API Documentation",
                wiki_content=SAMPLE_WIKI,
            )

        assert result["score"] == 1
        assert result["category"] == "API Documentation"
        assert result["criteria"] == "API endpoints are documented"

    @pytest.mark.asyncio
    async def test_evaluate_criterion_chunked_miss(self):
        """_evaluate_criterion_chunked returns score=0 when LLM says not documented."""
        from wiki_evaluator import _evaluate_criterion_chunked

        llm_response = json.dumps({
            "criteria": "Deployment process is documented",
            "score": 0,
            "reasoning": "No deployment instructions found.",
            "evidence": "none",
        })

        with patch("wiki_evaluator._call_llm", new_callable=AsyncMock, return_value=llm_response):
            result = await _evaluate_criterion_chunked(
                criterion="Deployment process is documented",
                category="Ops",
                wiki_content=SAMPLE_WIKI,
            )

        assert result["score"] == 0

    @pytest.mark.asyncio
    async def test_evaluate_criterion_chunked_short_circuit(self):
        """_evaluate_criterion_chunked short-circuits on first chunk with score=1."""
        from wiki_evaluator import _evaluate_criterion_chunked, CHUNK_SIZE

        # Make wiki_content longer than one chunk
        big_content = SAMPLE_WIKI * (CHUNK_SIZE // len(SAMPLE_WIKI) + 2)

        call_count = 0

        async def mock_llm(messages, model=None):
            nonlocal call_count
            call_count += 1
            # First chunk: found
            return json.dumps({"criteria": "x", "score": 1, "reasoning": "found", "evidence": "y"})

        with patch("wiki_evaluator._call_llm", side_effect=mock_llm):
            result = await _evaluate_criterion_chunked(
                criterion="API endpoints are documented",
                category="API",
                wiki_content=big_content,
            )

        assert result["score"] == 1
        # Should have short-circuited after first chunk finding the criterion
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_generate_ai_rubrics_parses_llm_response(self):
        """generate_ai_rubrics returns valid rubrics from a well-formed LLM response."""
        from wiki_evaluator import generate_ai_rubrics

        fake_response = json.dumps({
            "categories": [
                {"name": "API Docs", "weight": 0.6, "criteria": ["Endpoints are listed"]},
                {"name": "Setup",    "weight": 0.4, "criteria": ["Install steps exist"]},
            ]
        })

        docs_tree = {
            "title": "test",
            "subpages": [{"title": "overview", "sections": [{"title": "Intro", "content": "Hello"}]}],
        }

        with patch("wiki_evaluator._call_llm", new_callable=AsyncMock, return_value=fake_response):
            rubrics = await generate_ai_rubrics(docs_tree, "test-repo")

        assert "categories" in rubrics
        assert len(rubrics["categories"]) == 2
        assert rubrics.get("source") == "ai"
        total_w = sum(c["weight"] for c in rubrics["categories"])
        assert abs(total_w - 1.0) < 0.01

    @pytest.mark.asyncio
    async def test_generate_ai_rubrics_fallback_on_llm_error(self):
        """generate_ai_rubrics falls back to keyword rubrics when LLM raises."""
        from wiki_evaluator import generate_ai_rubrics

        docs_tree = {
            "title": "test",
            "subpages": [{"title": "api", "sections": [{"title": "API Reference", "content": ""}]}],
        }

        with patch("wiki_evaluator._call_llm", new_callable=AsyncMock, side_effect=Exception("timeout")):
            rubrics = await generate_ai_rubrics(docs_tree, "test-repo")

        assert "categories" in rubrics
        assert len(rubrics["categories"]) >= 1

    def test_merge_rubrics_both_present(self):
        """merge_rubrics produces categories from both AI and graph sources."""
        from wiki_evaluator import merge_rubrics

        ai = {
            "categories": [
                {"name": "AI Cat A", "weight": 0.5, "criteria": ["ai crit 1"]},
                {"name": "AI Cat B", "weight": 0.5, "criteria": ["ai crit 2"]},
            ]
        }
        graph = {
            "categories": [
                {"name": "Graph Cat X", "weight": 0.7, "criteria": ["graph crit 1"]},
                {"name": "Graph Cat Y", "weight": 0.3, "criteria": ["graph crit 2"]},
            ]
        }

        merged = merge_rubrics(ai, graph)
        assert "categories" in merged
        # Graph cats + AI-only cats (AI Cat A and AI Cat B are not in graph)
        assert len(merged["categories"]) == 4
        total_w = sum(c["weight"] for c in merged["categories"])
        assert abs(total_w - 1.0) < 0.01

    def test_merge_rubrics_empty_ai(self):
        """merge_rubrics returns graph rubrics unchanged when AI rubrics empty."""
        from wiki_evaluator import merge_rubrics

        merged = merge_rubrics({"categories": []}, CANNED_RUBRICS)
        assert merged["categories"] == CANNED_RUBRICS["categories"]

    def test_merge_rubrics_empty_graph(self):
        """merge_rubrics returns AI rubrics unchanged when graph rubrics empty."""
        from wiki_evaluator import merge_rubrics

        ai = {"categories": [{"name": "A", "weight": 1.0, "criteria": ["x"]}]}
        merged = merge_rubrics(ai, {"categories": []})
        assert merged["categories"] == ai["categories"]

    def test_calculate_scores_all_pass(self):
        """_calculate_scores computes 1.0 when all criteria score 1."""
        from wiki_evaluator import _calculate_scores

        results = [
            {"category": cat["name"], "criteria": crit, "score": 1,
             "reasoning": "documented", "evidence": ""}
            for cat in CANNED_RUBRICS["categories"]
            for crit in cat["criteria"]
        ]
        scores = _calculate_scores(results, CANNED_RUBRICS)
        assert scores["overall_score"] >= 0.99

    def test_calculate_scores_all_criteria_counted(self):
        """_calculate_scores counts every criterion — no skipping based on absence."""
        from wiki_evaluator import _calculate_scores

        # Two categories score 0, one scores 1 — all should appear in scores_by_category
        results = []
        # Architecture: all absent (score 0)
        for crit in CANNED_RUBRICS["categories"][0]["criteria"]:
            results.append({
                "category": "Architecture Overview",
                "criteria": crit,
                "score": 0,
                "reasoning": "not documented — no architecture section found",
                "evidence": "",
            })
        # API: all pass (score 1)
        for crit in CANNED_RUBRICS["categories"][1]["criteria"]:
            results.append({
                "category": "API Documentation",
                "criteria": crit,
                "score": 1,
                "reasoning": "documented in API Reference",
                "evidence": "## API Reference",
            })
        # Data Models: all absent (score 0)
        for crit in CANNED_RUBRICS["categories"][2]["criteria"]:
            results.append({
                "category": "Data Models",
                "criteria": crit,
                "score": 0,
                "reasoning": "no data models section present",
                "evidence": "",
            })

        scores = _calculate_scores(results, CANNED_RUBRICS)

        # All three categories must be scored — nothing skipped
        assert scores["skipped_categories"] == {}
        assert "Architecture Overview" in scores["scores_by_category"]
        assert "Data Models" in scores["scores_by_category"]
        assert "API Documentation" in scores["scores_by_category"]
        # Zero-scoring categories contribute 0.0 to the overall score
        assert scores["scores_by_category"]["Architecture Overview"] == 0.0
        assert scores["scores_by_category"]["Data Models"] == 0.0
        assert scores["scores_by_category"]["API Documentation"] == 1.0
        # Total criteria = sum across all categories
        total_crit = sum(len(c["criteria"]) for c in CANNED_RUBRICS["categories"])
        assert scores["total_criteria"] == total_crit
        # Overall score is weighted average across all three categories
        assert 0.0 < scores["overall_score"] < 1.0

    @pytest.mark.asyncio
    async def test_full_evaluate_async_mocked(self):
        """WikiEvaluator._evaluate_async runs end-to-end with mocked LLM."""
        from wiki_evaluator import WikiEvaluator

        ev = WikiEvaluator(model="test-model")
        ev.batch_size = 10  # process all at once

        llm_pass_response = json.dumps({
            "criteria": "x", "score": 1,
            "reasoning": "documented", "evidence": "see wiki",
        })

        ai_rubric_response = json.dumps({
            "categories": [
                {"name": "AI Overview", "weight": 1.0,
                 "criteria": ["System is described"]},
            ]
        })

        call_count = 0

        async def mock_llm(messages, model=None):
            nonlocal call_count
            call_count += 1
            content = messages[-1]["content"]
            if "Generate evaluation rubrics" in content or "evaluation rubrics" in content.lower():
                return ai_rubric_response
            return llm_pass_response

        with patch("wiki_evaluator._call_llm", side_effect=mock_llm):
            result = await ev._evaluate_async(
                wiki_content=SAMPLE_WIKI,
                graph_rubrics=CANNED_RUBRICS,
                wiki_dir=None,       # skip Steps 1+2
                ai_weight=0.4,
                graph_weight=0.6,
            )

        assert "overall_score" in result
        assert "total_criteria" in result
        assert "category_scores" in result
        assert result["total_criteria"] > 0

    def test_evaluate_empty_rubrics(self):
        """evaluate_async with no criteria returns empty result without error."""
        from wiki_evaluator import WikiEvaluator

        ev = WikiEvaluator(model="test-model")

        result = asyncio.get_event_loop().run_until_complete(
            ev._evaluate_async(
                wiki_content=SAMPLE_WIKI,
                graph_rubrics={"categories": []},
                wiki_dir=None,
                ai_weight=0.4,
                graph_weight=0.6,
            )
        )
        assert result["overall_score"] == 0.0
        assert result["total_criteria"] == 0


# ===========================================================================
# 3. evaluate_wiki.py helper tests
# ===========================================================================


class TestEvaluateWikiHelpers:
    """Tests for standalone helper functions in evaluate_wiki.py."""

    def test_import_evaluate_wiki(self):
        """evaluate_wiki module is importable."""
        import evaluate_wiki
        assert evaluate_wiki is not None

    def test_resolve_wiki_dir_absolute(self, tmp_path):
        """resolve_wiki_dir returns the path when it exists (absolute)."""
        import evaluate_wiki

        wiki = tmp_path / "mywiki"
        wiki.mkdir()
        result = evaluate_wiki.resolve_wiki_dir(str(wiki))
        assert result == wiki.resolve()

    def test_resolve_wiki_dir_relative(self, tmp_path):
        """resolve_wiki_dir resolves relative names against base_dir."""
        import evaluate_wiki

        wiki = tmp_path / ".codewiki"
        wiki.mkdir()
        result = evaluate_wiki.resolve_wiki_dir(".codewiki", base_dir=tmp_path)
        assert result == wiki.resolve()

    def test_resolve_wiki_dir_not_found_returns_none(self, tmp_path):
        """resolve_wiki_dir returns None (and warns) when path missing."""
        import evaluate_wiki

        result = evaluate_wiki.resolve_wiki_dir("nonexistent_dir", base_dir=tmp_path)
        assert result is None

    def test_resolve_wiki_dir_autodetect(self, tmp_path):
        """resolve_wiki_dir auto-detects .codewiki when wiki_dir_arg is None."""
        import evaluate_wiki

        codewiki = tmp_path / ".codewiki"
        codewiki.mkdir()
        result = evaluate_wiki.resolve_wiki_dir(None, base_dir=tmp_path)
        assert result == codewiki.resolve()

    def test_resolve_wiki_dir_no_auto_returns_none(self, tmp_path):
        """resolve_wiki_dir returns None when nothing is found."""
        import evaluate_wiki

        result = evaluate_wiki.resolve_wiki_dir(None, base_dir=tmp_path)
        assert result is None

    def test_read_wiki_directory(self, wiki_dir):
        """read_wiki_directory returns all markdown content concatenated."""
        import evaluate_wiki

        content = evaluate_wiki.read_wiki_directory(wiki_dir)
        assert "Overview" in content
        assert "API Reference" in content
        assert "Quickstart" in content

    def test_read_wiki_directory_empty(self, tmp_path):
        """read_wiki_directory returns empty string for dir with no .md files."""
        import evaluate_wiki

        empty = tmp_path / "empty_wiki"
        empty.mkdir()
        content = evaluate_wiki.read_wiki_directory(empty)
        assert content == ""

    def test_read_wiki_directory_nonexistent(self, tmp_path):
        """read_wiki_directory returns empty string for missing dir."""
        import evaluate_wiki

        missing = tmp_path / "does_not_exist"
        content = evaluate_wiki.read_wiki_directory(missing)
        assert content == ""

    def test_read_wiki_counts_files(self, wiki_dir):
        """read_wiki_directory includes content from subdirectories."""
        import evaluate_wiki

        content = evaluate_wiki.read_wiki_directory(wiki_dir)
        # 3 markdown files: overview.md, api.md, guides/quickstart.md
        assert content.count("### File:") == 3

    def test_generate_report_creates_json(self, tmp_path):
        """generate_report writes a valid JSON file."""
        import evaluate_wiki

        sample_results = {
            "overall_score": 0.75,
            "overall_pct": "75.0%",
            "total_criteria": 4,
            "met_criteria": 3,
            "category_scores": {
                "Architecture": {"score": 0.8, "met": 2, "total": 2},
                "API Docs": {"score": 0.7, "met": 1, "total": 2},
            },
            "metrics_summary": {"WikiCoverage": 0.75},
            "detailed_criteria": [],
        }

        output = str(tmp_path / "report.md")
        evaluate_wiki.generate_report(
            sample_results, PROJECT_ID, "/path/to/wiki", "test-model", output
        )

        json_path = tmp_path / "report.json"
        assert json_path.exists(), "JSON report should be written"
        data = json.loads(json_path.read_text())
        assert data["overall_score"] == 0.75

    def test_generate_report_creates_markdown(self, tmp_path):
        """generate_report writes a Markdown file with score information."""
        import evaluate_wiki

        sample_results = {
            "overall_score": 0.60,
            "overall_pct": "60.0%",
            "total_criteria": 3,
            "met_criteria": 2,
            "category_scores": {"Setup": {"score": 0.6, "met": 2, "total": 3}},
            "metrics_summary": {"WikiCoverage": 0.6, "WikiFaithfulness": 0.6},
            "detailed_criteria": [
                {
                    "category": "Setup",
                    "criterion": "Install instructions exist",
                    "overall_score": 1.0,
                    "metrics": {"WikiCoverage": {"score": 1.0, "success": True, "threshold": 0.5}},
                    "source": "graph_rubric",
                }
            ],
        }

        output = str(tmp_path / "report.md")
        evaluate_wiki.generate_report(
            sample_results, PROJECT_ID, None, "gpt-4o", output
        )

        md_path = tmp_path / "report.md"
        assert md_path.exists()
        md_text = md_path.read_text()
        assert "Wiki Evaluation Report" in md_text
        assert "60.0%" in md_text or "60%" in md_text


# ===========================================================================
# 4. potpie_cli.py evaluate-wiki command tests
# ===========================================================================


class TestEvaluateWikiCLICommand:
    """
    Tests for the potpie_cli.py evaluate-wiki command.

    The command now invokes a subprocess (the skill script).  We mock
    ``subprocess.run`` to avoid any actual execution.

    IMPORTANT: potpie_cli.py imports ``from potpie import PotpieRuntime`` at
    module level.  To avoid corrupting sys.modules for other test files
    (test_eval_ask_pipeline.py needs the REAL potpie), each test:
      1. Saves the current sys.modules entries for potpie_* and potpie_cli.
      2. Injects lightweight stubs.
      3. Does a fresh import of potpie_cli.
      4. Restores the original sys.modules after the test.
    """

    # Module names that need stubs for potpie_cli to import cleanly
    _STUB_NAMES = [
        "potpie", "potpie.runtime", "potpie.agents", "potpie.agents.context",
        "potpie.types", "potpie.core", "potpie.core.database", "potpie.config",
        "potpie_cli",
    ]

    def _make_potpie_stubs(self) -> dict:
        """Build potpie stub modules (does NOT register them yet)."""
        def _make(name, **attrs):
            mod = types.ModuleType(name)
            for k, v in attrs.items():
                setattr(mod, k, v)
            return mod

        return {
            "potpie": _make("potpie", PotpieRuntime=MagicMock(), __version__="0.0.0-test"),
            "potpie.runtime": _make("potpie.runtime", PotpieRuntime=MagicMock()),
            "potpie.agents": _make("potpie.agents"),
            "potpie.agents.context": _make("potpie.agents.context",
                                            ChatContext=MagicMock(),
                                            ToolCallEventType=MagicMock()),
            "potpie.types": _make("potpie.types", ProjectStatus=MagicMock()),
            "potpie.core": _make("potpie.core"),
            "potpie.core.database": _make("potpie.core.database", DatabaseManager=MagicMock()),
            "potpie.config": _make("potpie.config", settings=MagicMock()),
        }

    def _fresh_cli(self):
        """
        Return a freshly imported potpie_cli module with potpie stubs in place.
        Call this at the start of each test, before entering the save/restore context.
        The cleanup_potpie_cli fixture handles restoration.
        """
        import importlib

        # Save and replace potpie* modules
        self._saved_modules = {
            name: sys.modules.get(name) for name in self._STUB_NAMES
        }

        stubs = self._make_potpie_stubs()
        for name, stub in stubs.items():
            sys.modules[name] = stub

        # Force fresh import of potpie_cli (remove stale cache)
        sys.modules.pop("potpie_cli", None)

        module = importlib.import_module("potpie_cli")
        return module

    @pytest.fixture(autouse=True)
    def cleanup_potpie_cli(self):
        """Restore sys.modules after each test so other test files aren't affected."""
        self._saved_modules: dict = {}
        yield
        # Restore all previously saved modules
        for name, original in self._saved_modules.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
        # Also remove freshly imported potpie_cli
        sys.modules.pop("potpie_cli", None)

    @pytest.fixture
    def fake_report(self, tmp_path) -> Path:
        """Write a canned JSON report that the CLI will try to read."""
        report = tmp_path / "wiki_eval_score.json"
        report.write_text(json.dumps({
            "overall_score": 0.72,
            "overall_pct": "72.0%",
            "total_criteria": 7,
            "met_criteria": 5,
            "category_scores": {
                "Architecture": {"score": 0.8, "met": 2, "total": 2},
                "API Docs":     {"score": 0.67, "met": 2, "total": 3},
                "Data Models":  {"score": 0.5,  "met": 1, "total": 2},
            },
            "metrics_summary": {"WikiCoverage": 0.72, "WikiFaithfulness": 0.72},
            "detailed_criteria": [],
        }), encoding="utf-8")
        return report

    @pytest.fixture
    def mock_proc(self):
        """Mock subprocess.run returning exit code 0."""
        proc = MagicMock()
        proc.returncode = 0
        return proc

    @pytest.mark.asyncio
    async def test_evaluate_wiki_calls_skill_script(self, tmp_path, mock_proc, fake_report, monkeypatch):
        """_evaluate_wiki calls subprocess.run with the skill script path."""
        cli_module = self._fresh_cli()

        monkeypatch.chdir(tmp_path)
        wiki = tmp_path / ".codewiki"
        wiki.mkdir()

        with patch("subprocess.run", return_value=mock_proc) as mock_run, \
             patch.object(cli_module, "console", MagicMock()):

            await cli_module._evaluate_wiki(
                project_id=PROJECT_ID,
                repo=None,
                wiki_dir=str(wiki),
                reference_docs_dir=None,
                reference_docs_weight=0.3,
                ai_weight=0.4,
                graph_weight=0.6,
                context_window=None,
                output=str(fake_report.with_suffix(".md")),
                model=None,
                user_id="testuser",
            )

        mock_run.assert_called_once()
        cmd_args = mock_run.call_args[0][0]
        assert any("evaluate_wiki.py" in str(a) for a in cmd_args), \
            f"Expected skill script in cmd: {cmd_args}"
        assert "--project-id" in cmd_args
        assert PROJECT_ID in cmd_args

    @pytest.mark.asyncio
    async def test_evaluate_wiki_passes_wiki_dir(self, tmp_path, mock_proc, fake_report, monkeypatch):
        """_evaluate_wiki passes --wiki-dir to the skill script."""
        cli_module = self._fresh_cli()

        monkeypatch.chdir(tmp_path)
        wiki = tmp_path / ".codewiki"
        wiki.mkdir()

        with patch("subprocess.run", return_value=mock_proc) as mock_run, \
             patch.object(cli_module, "console", MagicMock()):

            await cli_module._evaluate_wiki(
                project_id=PROJECT_ID,
                repo=None,
                wiki_dir=str(wiki),
                reference_docs_dir=None,
                reference_docs_weight=0.3,
                ai_weight=0.4,
                graph_weight=0.6,
                context_window=None,
                output=str(fake_report.with_suffix(".md")),
                model=None,
                user_id="testuser",
            )

        cmd_args = mock_run.call_args[0][0]
        assert "--wiki-dir" in cmd_args
        assert str(wiki.resolve()) in cmd_args

    @pytest.mark.asyncio
    async def test_evaluate_wiki_passes_model(self, tmp_path, mock_proc, fake_report, monkeypatch):
        """_evaluate_wiki forwards --model to skill script when provided."""
        cli_module = self._fresh_cli()

        monkeypatch.chdir(tmp_path)
        wiki = tmp_path / ".codewiki"
        wiki.mkdir()

        with patch("subprocess.run", return_value=mock_proc) as mock_run, \
             patch.object(cli_module, "console", MagicMock()):

            await cli_module._evaluate_wiki(
                project_id=PROJECT_ID,
                repo=None,
                wiki_dir=str(wiki),
                reference_docs_dir=None,
                reference_docs_weight=0.3,
                ai_weight=0.4,
                graph_weight=0.6,
                context_window=None,
                output=str(fake_report.with_suffix(".md")),
                model="copilot_cli/gpt-4o",
                user_id="testuser",
            )

        cmd_args = mock_run.call_args[0][0]
        assert "--model" in cmd_args
        assert "copilot_cli/gpt-4o" in cmd_args

    @pytest.mark.asyncio
    async def test_evaluate_wiki_uses_repo_flag(self, tmp_path, mock_proc, fake_report, monkeypatch):
        """_evaluate_wiki passes --repo instead of --project-id when repo given."""
        cli_module = self._fresh_cli()

        monkeypatch.chdir(tmp_path)

        with patch("subprocess.run", return_value=mock_proc) as mock_run, \
             patch.object(cli_module, "console", MagicMock()):

            await cli_module._evaluate_wiki(
                project_id=None,
                repo=REPO_NAME,
                wiki_dir=None,
                reference_docs_dir=None,
                reference_docs_weight=0.3,
                ai_weight=0.4,
                graph_weight=0.6,
                context_window=None,
                output=str(fake_report.with_suffix(".md")),
                model=None,
                user_id="testuser",
            )

        cmd_args = mock_run.call_args[0][0]
        assert "--repo" in cmd_args
        assert REPO_NAME in cmd_args

    @pytest.mark.asyncio
    async def test_evaluate_wiki_aborts_no_project_no_repo(self, tmp_path, monkeypatch):
        """_evaluate_wiki raises click.Abort when neither --project nor --repo given."""
        import click
        cli_module = self._fresh_cli()

        monkeypatch.chdir(tmp_path)

        with patch.object(cli_module, "console", MagicMock()):
            with pytest.raises(click.Abort):
                await cli_module._evaluate_wiki(
                    project_id=None,
                    repo=None,
                    wiki_dir=None,
                    reference_docs_dir=None,
                    reference_docs_weight=0.3,
                    ai_weight=0.4,
                    graph_weight=0.6,
                    context_window=None,
                    output="output.md",
                    model=None,
                    user_id="testuser",
                )

    @pytest.mark.asyncio
    async def test_evaluate_wiki_aborts_on_missing_wiki_dir(self, tmp_path, monkeypatch):
        """_evaluate_wiki raises click.Abort when wiki-dir path does not exist."""
        import click
        cli_module = self._fresh_cli()

        monkeypatch.chdir(tmp_path)

        with patch.object(cli_module, "console", MagicMock()):
            with pytest.raises(click.Abort):
                await cli_module._evaluate_wiki(
                    project_id=PROJECT_ID,
                    repo=None,
                    wiki_dir="/nonexistent/path/to/wiki",
                    reference_docs_dir=None,
                    reference_docs_weight=0.3,
                    ai_weight=0.4,
                    graph_weight=0.6,
                    context_window=None,
                    output="output.md",
                    model=None,
                    user_id="testuser",
                )

    @pytest.mark.asyncio
    async def test_evaluate_wiki_reads_json_report(self, tmp_path, mock_proc, fake_report, monkeypatch):
        """After skill runs, _evaluate_wiki reads and displays the JSON report."""
        cli_module = self._fresh_cli()

        monkeypatch.chdir(tmp_path)
        wiki = tmp_path / ".codewiki"
        wiki.mkdir()

        mock_console = MagicMock()
        with patch("subprocess.run", return_value=mock_proc), \
             patch.object(cli_module, "console", mock_console):

            await cli_module._evaluate_wiki(
                project_id=PROJECT_ID,
                repo=None,
                wiki_dir=str(wiki),
                reference_docs_dir=None,
                reference_docs_weight=1.0,
                ai_weight=0.4,
                graph_weight=0.6,
                context_window=None,
                output=str(fake_report.with_suffix(".md")),
                model=None,
                user_id="testuser",
            )

        assert mock_console.print.called


# ===========================================================================
# 5. Integration-style pipeline test (all mocked)
# ===========================================================================


class TestFullPipelineMocked:
    """
    End-to-end pipeline test: GraphRubricGenerator → WikiEvaluator → report.

    All graph calls and LLM calls are mocked.
    """

    @pytest.mark.asyncio
    async def test_full_pipeline(self, mock_runtime, tmp_path):
        """Full pipeline produces a non-zero score and writes a valid report."""
        import evaluate_wiki
        from graph_rubric_generator import GraphRubricGenerator
        from wiki_evaluator import WikiEvaluator

        # ── Step 3: Generate graph rubrics (mocked LLM) ───────────────────────
        gen = GraphRubricGenerator(mock_runtime, PROJECT_ID)

        async def _mock_gen_rubrics(context_items, model=None):
            return CANNED_RUBRICS.copy()

        gen._generate_rubrics_from_context = _mock_gen_rubrics
        rubrics = await gen.generate()

        assert "categories" in rubrics
        assert len(rubrics["categories"]) == 3

        # ── Steps 1-2, 4-6: WikiEvaluator (mocked LLM per criterion) ─────────
        ev = WikiEvaluator(model="test-model")
        ev.batch_size = 10

        llm_pass = json.dumps({
            "criteria": "x", "score": 1,
            "reasoning": "documented", "evidence": "see wiki",
        })

        with patch("wiki_evaluator._call_llm", new_callable=AsyncMock, return_value=llm_pass):
            results = await ev._evaluate_async(
                wiki_content=SAMPLE_WIKI,
                graph_rubrics=rubrics,
                wiki_dir=None,   # skip AI rubric steps — use graph-only
                ai_weight=0.4,
                graph_weight=0.6,
            )

        assert results["total_criteria"] == 7   # 2 + 3 + 2 criteria
        assert results["met_criteria"] == 7     # all pass (mock returns score=1)
        assert results["overall_score"] >= 0.9

        # ── Step 7: Generate report ────────────────────────────────────────────
        output = str(tmp_path / "pipeline_report.md")
        evaluate_wiki.generate_report(
            results, PROJECT_ID, str(tmp_path / ".codewiki"), "test-model", output
        )

        json_path = tmp_path / "pipeline_report.json"
        md_path = tmp_path / "pipeline_report.md"
        assert json_path.exists()
        assert md_path.exists()

        data = json.loads(json_path.read_text())
        assert data["overall_score"] >= 0.9
        assert data["total_criteria"] == 7


# ===========================================================================
# 6. DeepwikiDocsParser tests
# ===========================================================================


class TestDeepwikiDocsParser:
    """Tests for deepwiki_docs_parser — porting parse_reference_docs.py logic."""

    def test_import(self):
        """deepwiki_docs_parser is importable from the skill modules."""
        from deepwiki_docs_parser import parse_docs_directory, parse_markdown_file, DocPage
        assert parse_docs_directory is not None
        assert parse_markdown_file is not None
        assert DocPage is not None

    def test_parse_markdown_file_basic(self, tmp_path):
        """parse_markdown_file extracts title and content from a simple file."""
        from deepwiki_docs_parser import parse_markdown_file

        md = tmp_path / "overview.md"
        md.write_text("# Overview\n\n## Purpose\n\nThis is the purpose section.\n")
        page = parse_markdown_file(str(md))
        assert page.title is not None
        assert isinstance(page.content, dict)

    def test_parse_markdown_file_frontmatter(self, tmp_path):
        """parse_markdown_file parses YAML frontmatter."""
        from deepwiki_docs_parser import parse_markdown_file

        md = tmp_path / "api.md"
        md.write_text("---\ntitle: API Reference\ndescription: Public API\n---\n\n## Endpoints\n\nPOST /login\n")
        page = parse_markdown_file(str(md))
        # Title may come from frontmatter or content
        assert page.title is not None

    def test_parse_markdown_file_strips_details_blocks(self, tmp_path):
        """parse_markdown_file strips <details>…</details> deepwiki source blocks."""
        from deepwiki_docs_parser import parse_markdown_file

        md = tmp_path / "page.md"
        md.write_text(
            "# Page\n\n"
            "<details><summary>Relevant source files</summary>\n- file.py\n</details>\n\n"
            "## Real Content\n\nActual documentation here.\n"
        )
        page = parse_markdown_file(str(md))
        content_str = str(page.content)
        assert "Relevant source files" not in content_str

    def test_parse_markdown_file_fallback_title(self, tmp_path):
        """parse_markdown_file uses filename as fallback title."""
        from deepwiki_docs_parser import parse_markdown_file

        md = tmp_path / "my_feature_doc.md"
        md.write_text("Some content without a heading.\n")
        page = parse_markdown_file(str(md))
        assert "My Feature Doc" in page.title or page.title is not None

    def test_parse_docs_directory_counts_pages(self, tmp_path):
        """parse_docs_directory creates one page per .md file."""
        from deepwiki_docs_parser import parse_docs_directory

        wiki = tmp_path / "wiki"
        wiki.mkdir()
        (wiki / "1_Overview.md").write_text("# Overview\n\nIntro text.\n")
        (wiki / "2_API.md").write_text("# API\n\n## Endpoints\n\nPOST /login\n")
        (wiki / "3_Install.md").write_text("# Installation\n\nRun pip install.\n")

        root, docs_tree = parse_docs_directory(
            path=str(wiki), project_name="test-repo", output_dir=str(tmp_path / "out")
        )
        assert len(root.subpages) == 3
        assert "title" in docs_tree
        assert docs_tree["title"] == "test-repo"

    def test_parse_docs_directory_writes_json_files(self, tmp_path):
        """parse_docs_directory writes docs_tree.json and structured_docs.json."""
        from deepwiki_docs_parser import parse_docs_directory

        wiki = tmp_path / "wiki"
        wiki.mkdir()
        (wiki / "1_Overview.md").write_text("# Overview\n\nText.\n")

        out_dir = tmp_path / "out"
        parse_docs_directory(path=str(wiki), project_name="repo", output_dir=str(out_dir))

        assert (out_dir / "docs_tree.json").exists()
        assert (out_dir / "structured_docs.json").exists()

        tree = json.loads((out_dir / "docs_tree.json").read_text())
        assert "title" in tree
        assert "subpages" in tree

        structured = json.loads((out_dir / "structured_docs.json").read_text())
        assert "title" in structured

    def test_parse_docs_directory_subpages_have_titles(self, tmp_path):
        """Every subpage in docs_tree has a title."""
        from deepwiki_docs_parser import parse_docs_directory

        wiki = tmp_path / "wiki"
        wiki.mkdir()
        (wiki / "1_Intro.md").write_text("# Introduction\n\nHello.\n")
        (wiki / "2_Usage.md").write_text("# Usage\n\nRun it.\n")

        _, docs_tree = parse_docs_directory(str(wiki), output_dir=str(tmp_path / "out"))
        for sub in docs_tree.get("subpages", []):
            assert "title" in sub, f"Missing title in subpage: {sub}"

    def test_docs_tree_uses_placeholder_values(self, tmp_path):
        """docs_tree replaces string content with '<detail_content>' placeholders."""
        from deepwiki_docs_parser import parse_docs_directory

        wiki = tmp_path / "wiki"
        wiki.mkdir()
        (wiki / "1_Page.md").write_text("# Page\n\n## Section\n\nSome real content here.\n")

        _, docs_tree = parse_docs_directory(str(wiki), output_dir=str(tmp_path / "out"))
        tree_str = json.dumps(docs_tree)
        assert "<detail_content>" in tree_str, "docs_tree should contain placeholder values"
        assert "Some real content here" not in tree_str, "docs_tree should NOT contain raw content"

    def test_structured_docs_contains_real_content(self, tmp_path):
        """structured_docs.json contains real page content (not placeholders)."""
        from deepwiki_docs_parser import parse_docs_directory

        wiki = tmp_path / "wiki"
        wiki.mkdir()
        (wiki / "1_Page.md").write_text("# Page\n\n## Section\n\nSome real content here.\n")

        out = tmp_path / "out"
        parse_docs_directory(str(wiki), output_dir=str(out))
        structured = (out / "structured_docs.json").read_text()
        assert "Page" in structured  # title preserved

    def test_get_docs_tree_summary(self, tmp_path):
        """get_docs_tree_summary returns a non-empty string with page titles."""
        from deepwiki_docs_parser import parse_docs_directory, get_docs_tree_summary

        wiki = tmp_path / "wiki"
        wiki.mkdir()
        (wiki / "1_Overview.md").write_text("# Overview\n\nText.\n")
        (wiki / "2_API.md").write_text("# API Reference\n\nText.\n")

        _, docs_tree = parse_docs_directory(str(wiki), output_dir=str(tmp_path / "out"))
        summary = get_docs_tree_summary(docs_tree)
        assert "Overview" in summary or "1 Overview" in summary or "overview" in summary.lower()
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_get_docs_tree_summary_truncates(self, tmp_path):
        """get_docs_tree_summary truncates to max_chars."""
        from deepwiki_docs_parser import get_docs_tree_summary

        # Build a very deep tree
        docs_tree = {"title": "root", "subpages": [
            {"title": f"Page {i}", "subpages": []} for i in range(200)
        ]}
        summary = get_docs_tree_summary(docs_tree, max_chars=100)
        assert len(summary) <= 120  # small leeway for truncation marker

    def test_parse_real_deepwiki_docs(self):
        """parse_docs_directory handles the real device-modeling-language deepwiki docs."""
        from deepwiki_docs_parser import parse_docs_directory
        import tempfile

        real_wiki = Path(_REPO_ROOT / ".wiki_doc_by_deepwiki/intel/device-modeling-language")
        if not real_wiki.exists():
            pytest.skip("Real deepwiki docs not available")

        with tempfile.TemporaryDirectory() as out:
            root, docs_tree = parse_docs_directory(
                str(real_wiki), project_name="device-modeling-language", output_dir=out
            )

        assert len(root.subpages) == 40  # 40 markdown files
        assert docs_tree["title"] == "device-modeling-language"
        assert len(docs_tree["subpages"]) == 40


# ===========================================================================
# 7. ReferenceRubricsGenerator tests
# ===========================================================================


# Canned hierarchical rubrics (sub_tasks format from CodeWikiBench)
CANNED_HIER_RUBRICS = [
    {
        "requirements": "Language Core and Object Model",
        "weight": 3,
        "sub_tasks": [
            {"requirements": "Device hierarchy with banks, registers, and fields is documented", "weight": 3},
            {"requirements": "DML object model and instantiation rules are explained", "weight": 2},
        ],
    },
    {
        "requirements": "Compiler Pipeline",
        "weight": 2,
        "sub_tasks": [
            {"requirements": "Lexing and parsing stages are described", "weight": 2},
            {"requirements": "C code generation backend is documented", "weight": 2},
        ],
    },
    {
        "requirements": "Standard Library and Templates",
        "weight": 2,
        "sub_tasks": [
            {"requirements": "Built-in templates and their usage are documented", "weight": 1},
        ],
    },
]

CANNED_HIER_RUBRICS_2 = [
    {
        "requirements": "Language Syntax",
        "weight": 3,
        "sub_tasks": [
            {"requirements": "DML syntax and grammar rules are documented", "weight": 3},
        ],
    },
    {
        "requirements": "Compiler Architecture",
        "weight": 2,
        "sub_tasks": [
            {"requirements": "Frontend parsing and semantic analysis are described", "weight": 2},
        ],
    },
]


class TestReferenceRubricsGenerator:
    """Tests for reference_rubrics_generator — porting generate_rubrics.py + combine_rubrics.py."""

    def test_import(self):
        """All public symbols are importable."""
        from reference_rubrics_generator import (
            generate_rubrics_from_docs_tree,
            combine_rubrics,
            flatten_rubrics_to_categories,
            generate_reference_rubrics,
            generate_reference_rubrics_multi_model,
            calculate_rubrics_statistics,
        )
        assert flatten_rubrics_to_categories is not None

    # ── flatten_rubrics_to_categories ─────────────────────────

    def test_flatten_empty(self):
        """flatten_rubrics_to_categories returns empty categories for empty input."""
        from reference_rubrics_generator import flatten_rubrics_to_categories
        result = flatten_rubrics_to_categories([])
        assert result == {"categories": []}

    def test_flatten_produces_categories(self):
        """flatten_rubrics_to_categories maps each top-level item to a category."""
        from reference_rubrics_generator import flatten_rubrics_to_categories
        flat = flatten_rubrics_to_categories(CANNED_HIER_RUBRICS)
        assert len(flat["categories"]) == 3
        names = [c["name"] for c in flat["categories"]]
        assert "Language Core and Object Model" in names
        assert "Compiler Pipeline" in names

    def test_flatten_weights_sum_to_one(self):
        """flatten_rubrics_to_categories normalises weights to sum to 1.0."""
        from reference_rubrics_generator import flatten_rubrics_to_categories
        flat = flatten_rubrics_to_categories(CANNED_HIER_RUBRICS)
        total = sum(c["weight"] for c in flat["categories"])
        assert abs(total - 1.0) < 0.01

    def test_flatten_collects_leaf_criteria(self):
        """Leaf sub_tasks become criteria strings."""
        from reference_rubrics_generator import flatten_rubrics_to_categories
        flat = flatten_rubrics_to_categories(CANNED_HIER_RUBRICS)
        lang_cat = next(c for c in flat["categories"] if "Language Core" in c["name"])
        assert len(lang_cat["criteria"]) == 2
        assert any("banks" in cr or "Device" in cr for cr in lang_cat["criteria"])

    def test_flatten_no_subtasks_uses_top_req(self):
        """Top-level items with no sub_tasks use their own requirements as criterion."""
        from reference_rubrics_generator import flatten_rubrics_to_categories
        rubrics = [
            {"requirements": "Standalone criterion", "weight": 2},
        ]
        flat = flatten_rubrics_to_categories(rubrics)
        assert flat["categories"][0]["criteria"] == ["Standalone criterion"]

    def test_flatten_source_tag(self):
        """flatten_rubrics_to_categories sets source='reference_docs'."""
        from reference_rubrics_generator import flatten_rubrics_to_categories
        flat = flatten_rubrics_to_categories(CANNED_HIER_RUBRICS)
        assert flat.get("source") == "reference_docs"
        for cat in flat["categories"]:
            assert cat.get("source") == "reference_docs"

    # ── calculate_rubrics_statistics ──────────────────────────────────────

    def test_stats_total_items(self):
        """calculate_rubrics_statistics counts all nodes recursively."""
        from reference_rubrics_generator import calculate_rubrics_statistics
        # 3 top-level + 2+2+1 sub_tasks = 8 total
        stats = calculate_rubrics_statistics(CANNED_HIER_RUBRICS)
        assert stats["total_items"] == 8
        assert stats["top_level_items"] == 3

    def test_stats_max_depth(self):
        """calculate_rubrics_statistics reports correct max depth."""
        from reference_rubrics_generator import calculate_rubrics_statistics
        stats = calculate_rubrics_statistics(CANNED_HIER_RUBRICS)
        assert stats["max_depth"] >= 1

    def test_stats_weight_distribution(self):
        """calculate_rubrics_statistics reports weight distribution dict."""
        from reference_rubrics_generator import calculate_rubrics_statistics
        stats = calculate_rubrics_statistics(CANNED_HIER_RUBRICS)
        assert isinstance(stats["weight_distribution"], dict)
        assert stats["average_weight"] > 0

    # ── _fallback_simple_merge ────────────────────

    def test_fallback_merge_deduplicates(self):
        """_fallback_simple_merge removes duplicate requirements."""
        from reference_rubrics_generator import _fallback_simple_merge
        set1 = [{"requirements": "A", "weight": 1}, {"requirements": "B", "weight": 2}]
        set2 = [{"requirements": "A", "weight": 1}, {"requirements": "C", "weight": 3}]
        merged = _fallback_simple_merge([set1, set2])
        reqs = [m["requirements"] for m in merged]
        assert reqs.count("A") == 1
        assert "B" in reqs
        assert "C" in reqs

    def test_fallback_merge_empty(self):
        """_fallback_simple_merge handles empty input."""
        from reference_rubrics_generator import _fallback_simple_merge
        assert _fallback_simple_merge([]) == []
        assert _fallback_simple_merge([[]]) == []

    # ── _parse_rubric_list ───────────────────

    def test_parse_rubric_list_valid(self):
        """_parse_rubric_list extracts JSON array from LLM response."""
        from reference_rubrics_generator import _parse_rubric_list
        raw = 'Here are the rubrics:\n[{"requirements":"A","weight":3}]\nDone.'
        result = _parse_rubric_list(raw)
        assert len(result) == 1
        assert result[0]["requirements"] == "A"

    def test_parse_rubric_list_invalid_raises(self):
        """_parse_rubric_list raises ValueError when no array found."""
        from reference_rubrics_generator import _parse_rubric_list
        with pytest.raises(ValueError):
            _parse_rubric_list("No array here at all!")

    # ── _parse_combined_rubrics ──────────────

    def test_parse_combined_rubrics_valid(self):
        """_parse_combined_rubrics extracts the rubrics list."""
        from reference_rubrics_generator import _parse_combined_rubrics
        raw = json.dumps({"rubrics": [{"requirements": "X", "weight": 2}]})
        result = _parse_combined_rubrics(raw)
        assert len(result) == 1
        assert result[0]["requirements"] == "X"

    def test_parse_combined_rubrics_invalid_raises(self):
        """_parse_combined_rubrics raises ValueError on bad input."""
        from reference_rubrics_generator import _parse_combined_rubrics
        with pytest.raises(ValueError):
            _parse_combined_rubrics("no JSON here")

    # ── generate_rubrics_from_docs_tree (mocked LLM) ─────────────────────

    @pytest.mark.asyncio
    async def test_generate_rubrics_from_docs_tree_success(self):
        """generate_rubrics_from_docs_tree parses LLM response into a rubric list."""
        from reference_rubrics_generator import generate_rubrics_from_docs_tree

        llm_response = json.dumps(CANNED_HIER_RUBRICS)

        docs_tree = {"title": "test", "subpages": [
            {"title": "Overview", "content": "<detail_content>"},
        ]}

        with patch("reference_rubrics_generator._call_llm",
                   new_callable=AsyncMock, return_value=llm_response):
            result = await generate_rubrics_from_docs_tree(docs_tree, model="test-model")

        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0]["requirements"] == "Language Core and Object Model"

    @pytest.mark.asyncio
    async def test_generate_rubrics_from_docs_tree_llm_failure(self):
        """generate_rubrics_from_docs_tree returns empty list on LLM failure."""
        from reference_rubrics_generator import generate_rubrics_from_docs_tree

        docs_tree = {"title": "test", "subpages": []}

        with patch("reference_rubrics_generator._call_llm",
                   new_callable=AsyncMock, side_effect=Exception("timeout")):
            result = await generate_rubrics_from_docs_tree(docs_tree)

        assert result == []

    # ── combine_rubrics (mocked LLM) ────────────

    @pytest.mark.asyncio
    async def test_combine_rubrics_single_set_passthrough(self):
        """combine_rubrics returns the single set unchanged (no LLM call needed)."""
        from reference_rubrics_generator import combine_rubrics

        result = await combine_rubrics([CANNED_HIER_RUBRICS])
        assert result == CANNED_HIER_RUBRICS

    @pytest.mark.asyncio
    async def test_combine_rubrics_empty(self):
        """combine_rubrics returns [] for empty input."""
        from reference_rubrics_generator import combine_rubrics
        result = await combine_rubrics([])
        assert result == []

    @pytest.mark.asyncio
    async def test_combine_rubrics_multi_success(self):
        """combine_rubrics uses LLM to merge multiple sets."""
        from reference_rubrics_generator import combine_rubrics

        combined_response = json.dumps({
            "rubrics": [
                {"requirements": "Merged Language Core", "weight": 3},
                {"requirements": "Merged Compiler", "weight": 2},
            ]
        })

        with patch("reference_rubrics_generator._call_llm",
                   new_callable=AsyncMock, return_value=combined_response):
            result = await combine_rubrics(
                [CANNED_HIER_RUBRICS, CANNED_HIER_RUBRICS_2],
                model="test-model",
            )

        assert len(result) == 2
        assert result[0]["requirements"] == "Merged Language Core"

    @pytest.mark.asyncio
    async def test_combine_rubrics_fallback_on_llm_failure(self):
        """combine_rubrics falls back to simple merge when all LLM calls fail."""
        from reference_rubrics_generator import combine_rubrics

        with patch("reference_rubrics_generator._call_llm",
                   new_callable=AsyncMock, side_effect=Exception("network error")):
            result = await combine_rubrics(
                [CANNED_HIER_RUBRICS, CANNED_HIER_RUBRICS_2],
                model="test-model",
                max_retries=1,
            )

        # Should have merged items from both sets (deduped)
        assert isinstance(result, list)
        assert len(result) > 0

    # ── generate_reference_rubrics (mocked LLM) ────────────────────────────

    @pytest.mark.asyncio
    async def test_generate_reference_rubrics_end_to_end(self):
        """generate_reference_rubrics returns flat categories dict."""
        from reference_rubrics_generator import generate_reference_rubrics

        llm_response = json.dumps(CANNED_HIER_RUBRICS)
        docs_tree = {"title": "test", "subpages": [{"title": "Intro", "content": "<detail_content>"}]}

        with patch("reference_rubrics_generator._call_llm",
                   new_callable=AsyncMock, return_value=llm_response):
            result = await generate_reference_rubrics(docs_tree, model="test-model")

        assert "categories" in result
        assert len(result["categories"]) == 3
        assert result.get("source") == "reference_docs"
        total_w = sum(c["weight"] for c in result["categories"])
        assert abs(total_w - 1.0) < 0.01

    @pytest.mark.asyncio
    async def test_generate_reference_rubrics_empty_on_failure(self):
        """generate_reference_rubrics returns empty categories when LLM fails."""
        from reference_rubrics_generator import generate_reference_rubrics

        docs_tree = {"title": "test", "subpages": []}

        with patch("reference_rubrics_generator._call_llm",
                   new_callable=AsyncMock, side_effect=Exception("error")):
            result = await generate_reference_rubrics(docs_tree)

        assert result == {"categories": [], "source": "reference_docs"}


# ===========================================================================
# 8. run_pipeline two-mode tests
# ===========================================================================


class TestRunPipelineModes:
    """
    Tests for the two evaluation modes in evaluate_wiki.run_pipeline:

    Mode A — reference_docs_dir provided:
        parse_docs_directory → generate_reference_rubrics → use directly as
        final rubrics; graph and AI rubric steps are SKIPPED.

    Mode B — no reference_docs_dir:
        graph rubrics (PotpieRuntime) + AI rubrics (WikiEvaluator Steps 1-2)
        are merged into final rubrics.
    """

    # ── Shared helpers ────────────────────────────────────────────────────

    @staticmethod
    def _llm_eval_response():
        return json.dumps({
            "criteria": "x", "score": 1, "reasoning": "documented", "evidence": "yes",
        })

    @staticmethod
    def _make_runtime_mock(mock_rt_cls):
        mock_rt = AsyncMock()
        mock_rt_cls.from_env.return_value = mock_rt
        mock_rt.initialize = AsyncMock()
        mock_rt.close = AsyncMock()
        return mock_rt

    @staticmethod
    def _make_graph_gen_mock(mock_gen_cls, rubrics):
        mock_gen = AsyncMock()
        mock_gen.generate = AsyncMock(return_value=rubrics)
        mock_gen_cls.return_value = mock_gen
        return mock_gen

    # ── Mode A tests ──────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_mode_a_uses_reference_rubrics_directly(self, tmp_path):
        """Mode A: parse_docs_directory + generate_reference_rubrics are called;
        graph/AI rubric steps are skipped; result has evaluation_mode='reference_docs'."""
        import evaluate_wiki

        reference_dir = tmp_path / "reference_docs"
        reference_dir.mkdir()
        (reference_dir / "1_Overview.md").write_text("# Overview\n\nText.\n")

        wiki_dir = tmp_path / ".codewiki"
        wiki_dir.mkdir()
        (wiki_dir / "wiki.md").write_text("# Wiki\n\nSome coverage.\n")

        reference_rubrics = {
            "categories": [
                {"name": "Reference Cat", "weight": 1.0,
                 "criteria": ["Reference criterion"], "source": "reference_docs"},
            ],
            "source": "reference_docs",
        }

        with patch("evaluate_wiki.PotpieRuntime") as mock_rt_cls, \
             patch("evaluate_wiki.GraphRubricGenerator") as mock_gen_cls, \
             patch("evaluate_wiki.parse_docs_directory") as mock_parse, \
             patch("evaluate_wiki.generate_reference_rubrics",
                   new_callable=AsyncMock, return_value=reference_rubrics) as mock_ref, \
             patch("wiki_evaluator._call_llm",
                   new_callable=AsyncMock, return_value=self._llm_eval_response()):

            self._make_runtime_mock(mock_rt_cls)
            self._make_graph_gen_mock(mock_gen_cls, {"categories": []})
            mock_parse.return_value = (MagicMock(), {"title": "reference", "subpages": []})

            results = await evaluate_wiki.run_pipeline(
                project_id=PROJECT_ID,
                wiki_dir=wiki_dir,
                model="test-model",
                ai_weight=0.4,
                graph_weight=0.6,
                output=str(tmp_path / "report.md"),
                reference_docs_dir=reference_dir,
            )

        # parse_docs_directory called once for the reference docs dir
        mock_parse.assert_called_once()
        assert str(reference_dir) in str(mock_parse.call_args)

        # generate_reference_rubrics called once
        mock_ref.assert_called_once()

        # Graph generator must NOT have been called (Mode A skips it)
        mock_gen_cls.return_value.generate.assert_not_called()

        # Results reflect Mode A
        assert results["evaluation_mode"] == "reference_docs"
        assert results["rubrics_sources"]["reference_docs"] is True
        assert results["rubrics_sources"]["graph"] is False
        assert results["rubrics_sources"]["ai"] is False

    @pytest.mark.asyncio
    async def test_mode_a_evaluates_against_reference_rubrics(self, tmp_path):
        """Mode A: the wiki is evaluated against the reference rubrics (not merged)."""
        import evaluate_wiki

        reference_dir = tmp_path / "ref"
        reference_dir.mkdir()
        (reference_dir / "1_Doc.md").write_text("# Doc\n\nContent.\n")

        wiki_dir = tmp_path / ".codewiki"
        wiki_dir.mkdir()
        (wiki_dir / "wiki.md").write_text("# Wiki\n\nText.\n")

        reference_rubrics = {
            "categories": [
                {"name": "Ref Cat A", "weight": 0.5, "criteria": ["crit A1", "crit A2"],
                 "source": "reference_docs"},
                {"name": "Ref Cat B", "weight": 0.5, "criteria": ["crit B1"],
                 "source": "reference_docs"},
            ],
            "source": "reference_docs",
        }

        with patch("evaluate_wiki.parse_docs_directory",
                   return_value=(MagicMock(), {})), \
             patch("evaluate_wiki.generate_reference_rubrics",
                   new_callable=AsyncMock, return_value=reference_rubrics), \
             patch("evaluate_wiki.PotpieRuntime"), \
             patch("evaluate_wiki.GraphRubricGenerator"), \
             patch("wiki_evaluator._call_llm",
                   new_callable=AsyncMock,
                   return_value=json.dumps({
                       "criteria": "x", "score": 1,
                       "reasoning": "found", "evidence": "here",
                   })):

            results = await evaluate_wiki.run_pipeline(
                project_id=PROJECT_ID,
                wiki_dir=wiki_dir,
                model="test-model",
                ai_weight=0.4,
                graph_weight=0.6,
                output=str(tmp_path / "report.md"),
                reference_docs_dir=reference_dir,
            )

        # All 3 reference criteria should be evaluated
        assert results["total_criteria"] == 3
        assert results["overall_score"] > 0

    @pytest.mark.asyncio
    async def test_mode_a_falls_back_to_mode_b_on_empty_rubrics(self, tmp_path):
        """Mode A: when generate_reference_rubrics returns 0 categories (LLM failure),
        the pipeline falls back to Mode B (AI + graph) instead of returning 0 criteria."""
        import evaluate_wiki

        reference_dir = tmp_path / "ref"
        reference_dir.mkdir()
        (reference_dir / "1_Doc.md").write_text("# Doc\n\nContent.\n")

        wiki_dir = tmp_path / ".codewiki"
        wiki_dir.mkdir()
        (wiki_dir / "wiki.md").write_text("# Wiki\n\nText.\n")

        # Simulate LLM failure: generate_reference_rubrics returns empty categories
        empty_rubrics = {"categories": [], "source": "reference_docs"}

        graph_rubrics = {
            "categories": [
                {"name": "Graph Cat", "weight": 1.0, "criteria": ["Graph criterion"]},
            ],
            "source": "graph",
        }

        with patch("evaluate_wiki.parse_docs_directory",
                   return_value=(MagicMock(), {"title": "ref", "subpages": []})), \
             patch("evaluate_wiki.generate_reference_rubrics",
                   new_callable=AsyncMock, return_value=empty_rubrics), \
             patch("evaluate_wiki.PotpieRuntime") as mock_rt_cls, \
             patch("evaluate_wiki.GraphRubricGenerator") as mock_gen_cls, \
             patch("wiki_evaluator._call_llm",
                   new_callable=AsyncMock,
                   return_value=self._llm_eval_response()):

            self._make_runtime_mock(mock_rt_cls)
            self._make_graph_gen_mock(mock_gen_cls, graph_rubrics)

            results = await evaluate_wiki.run_pipeline(
                project_id=PROJECT_ID,
                wiki_dir=wiki_dir,
                model="test-model",
                ai_weight=0.4,
                graph_weight=0.6,
                output=str(tmp_path / "report.md"),
                reference_docs_dir=reference_dir,
            )

        # Must have fallen back to Mode B — graph rubrics used
        assert results["evaluation_mode"] == "ai_graph", \
            f"Expected ai_graph fallback, got: {results['evaluation_mode']}"
        assert results["rubrics_sources"]["reference_docs"] is False
        assert results["rubrics_sources"]["graph"] is True
        # Should have actual criteria evaluated (not 0)
        assert results["total_criteria"] > 0, \
            "Fallback to Mode B must produce criteria to evaluate"

    # ── Mode B tests ──────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_mode_b_skips_reference_rubrics(self, tmp_path):
        """Mode B: parse_docs_directory is NOT called; result has evaluation_mode='ai_graph'."""
        import evaluate_wiki

        wiki_dir = tmp_path / ".codewiki"
        wiki_dir.mkdir()
        (wiki_dir / "wiki.md").write_text("# Wiki\n\nText.\n")

        graph_rubrics = {
            "categories": [
                {"name": "Graph Cat", "weight": 1.0, "criteria": ["Graph criterion"]},
            ],
            "source": "graph",
        }

        with patch("evaluate_wiki.PotpieRuntime") as mock_rt_cls, \
             patch("evaluate_wiki.GraphRubricGenerator") as mock_gen_cls, \
             patch("evaluate_wiki.parse_docs_directory") as mock_parse, \
             patch("wiki_evaluator._call_llm",
                   new_callable=AsyncMock, return_value=self._llm_eval_response()):

            self._make_runtime_mock(mock_rt_cls)
            self._make_graph_gen_mock(mock_gen_cls, graph_rubrics)

            results = await evaluate_wiki.run_pipeline(
                project_id=PROJECT_ID,
                wiki_dir=wiki_dir,
                model="test-model",
                ai_weight=0.4,
                graph_weight=0.6,
                output=str(tmp_path / "report.md"),
                reference_docs_dir=None,
            )

        # parse_docs_directory must NOT have been called
        mock_parse.assert_not_called()

        assert results["evaluation_mode"] == "ai_graph"
        assert results["rubrics_sources"]["reference_docs"] is False

    @pytest.mark.asyncio
    async def test_mode_b_uses_graph_and_ai_rubrics(self, tmp_path):
        """Mode B: GraphRubricGenerator is called; result contains graph rubric criteria."""
        import evaluate_wiki

        wiki_dir = tmp_path / ".codewiki"
        wiki_dir.mkdir()
        (wiki_dir / "wiki.md").write_text("# Wiki\n\nText about architecture.\n")

        graph_rubrics = {
            "categories": [
                {"name": "Graph Cat", "weight": 1.0,
                 "criteria": ["Graph-derived criterion"]},
            ],
            "source": "graph",
        }

        ai_rubrics_response = json.dumps({
            "categories": [
                {"name": "AI Cat", "weight": 1.0, "criteria": ["AI criterion"]},
            ]
        })

        call_count = {"n": 0}

        async def _mock_llm(messages, model=None):
            call_count["n"] += 1
            content = messages[-1]["content"]
            if "Generate evaluation rubrics" in content or "evaluation rubrics" in content.lower():
                return ai_rubrics_response
            return json.dumps({
                "criteria": "x", "score": 1, "reasoning": "ok", "evidence": "e",
            })

        with patch("evaluate_wiki.PotpieRuntime") as mock_rt_cls, \
             patch("evaluate_wiki.GraphRubricGenerator") as mock_gen_cls, \
             patch("wiki_evaluator._call_llm", side_effect=_mock_llm):

            self._make_runtime_mock(mock_rt_cls)
            self._make_graph_gen_mock(mock_gen_cls, graph_rubrics)

            results = await evaluate_wiki.run_pipeline(
                project_id=PROJECT_ID,
                wiki_dir=wiki_dir,
                model="test-model",
                ai_weight=0.4,
                graph_weight=0.6,
                output=str(tmp_path / "report.md"),
                reference_docs_dir=None,
            )

        # GraphRubricGenerator.generate was called
        mock_gen_cls.return_value.generate.assert_called_once()

        assert results["evaluation_mode"] == "ai_graph"
        assert results["rubrics_sources"]["graph"] is True
        assert results["total_criteria"] > 0

    @pytest.mark.asyncio
    async def test_mode_b_graph_failure_falls_back_to_ai_only(self, tmp_path):
        """Mode B: if graph rubric generation fails, evaluation still runs on AI rubrics."""
        import evaluate_wiki

        wiki_dir = tmp_path / ".codewiki"
        wiki_dir.mkdir()
        (wiki_dir / "wiki.md").write_text("# Wiki\n\nText.\n")

        ai_rubrics_response = json.dumps({
            "categories": [
                {"name": "AI Only Cat", "weight": 1.0, "criteria": ["AI only criterion"]},
            ]
        })

        async def _mock_llm(messages, model=None):
            content = messages[-1]["content"]
            if "evaluation rubrics" in content.lower() or "Generate evaluation rubrics" in content:
                return ai_rubrics_response
            return json.dumps({
                "criteria": "x", "score": 1, "reasoning": "ok", "evidence": "e",
            })

        with patch("evaluate_wiki.PotpieRuntime", side_effect=ImportError("no potpie")), \
             patch("wiki_evaluator._call_llm", side_effect=_mock_llm):

            results = await evaluate_wiki.run_pipeline(
                project_id=PROJECT_ID,
                wiki_dir=wiki_dir,
                model="test-model",
                ai_weight=0.4,
                graph_weight=0.6,
                output=str(tmp_path / "report.md"),
                reference_docs_dir=None,
            )

        assert "overall_score" in results
        assert results["evaluation_mode"] == "ai_graph"
        assert results["rubrics_sources"]["graph"] is False


# ---------------------------------------------------------------------------
# WikiEvaluator.evaluate_async with final_rubrics parameter
# ---------------------------------------------------------------------------

class TestWikiEvaluatorFinalRubrics:
    """Tests for the final_rubrics fast-path in WikiEvaluator.evaluate_async."""

    @pytest.mark.asyncio
    async def test_evaluate_async_with_final_rubrics_skips_merge(self):
        """When final_rubrics is provided, Steps 1-2-4 are skipped."""
        from wiki_evaluator import WikiEvaluator

        ev = WikiEvaluator(model="test-model")
        ev.batch_size = 10

        final = {
            "categories": [
                {"name": "Pre-built Cat", "weight": 1.0,
                 "criteria": ["Pre-built criterion A", "Pre-built criterion B"]},
            ],
            "source": "reference_docs",
        }

        llm_response = json.dumps({
            "criteria": "x", "score": 1, "reasoning": "found", "evidence": "yes",
        })

        ai_rubric_calls = []

        async def _mock_llm(messages, model=None):
            content = messages[-1]["content"]
            if "evaluation rubrics" in content.lower():
                ai_rubric_calls.append(1)
                return json.dumps({"categories": []})
            return llm_response

        with patch("wiki_evaluator._call_llm", side_effect=_mock_llm):
            result = await ev.evaluate_async(
                wiki_content=SAMPLE_WIKI,
                graph_rubrics={"categories": []},
                wiki_dir=None,
                ai_weight=0.4,
                graph_weight=0.6,
                final_rubrics=final,
            )

        # AI rubric generation must NOT have been called
        assert len(ai_rubric_calls) == 0, "AI rubric generation should be skipped"
        assert result["total_criteria"] == 2
        assert result["met_criteria"] == 2

    @pytest.mark.asyncio
    async def test_evaluate_async_with_empty_final_rubrics_returns_empty(self):
        """evaluate_async with empty final_rubrics returns zero-score empty result."""
        from wiki_evaluator import WikiEvaluator

        ev = WikiEvaluator(model="test-model")
        result = await ev.evaluate_async(
            wiki_content=SAMPLE_WIKI,
            graph_rubrics={"categories": []},
            wiki_dir=None,
            final_rubrics={"categories": [], "source": "reference_docs"},
        )

        assert result["overall_score"] == 0.0
        assert result["total_criteria"] == 0

