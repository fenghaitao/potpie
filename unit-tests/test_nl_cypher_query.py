"""
Unit tests for the NL→Cypher query feature.

Covers:
  1. CypherGenerator.generate() — happy path, markdown fence stripping,
     missing-MATCH rejection, semicolon appending
  2. NLCypherQueryTool.arun() — happy path, Cypher generation failure,
     Neo4j execution failure, result formatting
  3. get_nl_cypher_query_tool() — returns a StructuredTool with correct metadata
  4. Registry / ToolService wiring — tool key present, allow-list membership

All tests are fully mocked — no live LLM, Neo4j, or DB required.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub out heavy app.core.database before any app import
# ---------------------------------------------------------------------------

def _stub_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


if "app.core.database" not in sys.modules:
    _stub_module(
        "app.core.database",
        engine=MagicMock(),
        SessionLocal=MagicMock(),
        Base=MagicMock(),
        get_db=MagicMock(),
        async_engine=MagicMock(),
        AsyncSessionLocal=MagicMock(),
    )

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db() -> MagicMock:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = None
    return db


def _make_pydantic_model_mock() -> MagicMock:
    """A fake pydantic-ai Model that ProviderService.get_pydantic_model() returns."""
    return MagicMock(name="FakePydanticModel")


def _make_agent_result(text: str) -> MagicMock:
    result = MagicMock()
    result.output = text
    return result


# ---------------------------------------------------------------------------
# 1. CypherGenerator
# ---------------------------------------------------------------------------

class TestCypherGenerator:
    """Tests for CypherGenerator.generate().

    CypherGenerator does a lazy import of ProviderService inside __init__,
    so we patch it at the source module rather than at the cypher_generator module.
    We bypass __init__ entirely by constructing the object and injecting a mock
    _agent directly — this is the cleanest approach.
    """

    def _make_generator(self, agent_output: str) -> "CypherGenerator":
        """Build a CypherGenerator with a pre-injected mock pydantic-ai Agent."""
        from app.modules.intelligence.provider.cypher_generator import CypherGenerator

        # Bypass __init__ (which calls ProviderService) by using object.__new__
        gen = object.__new__(CypherGenerator)

        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(return_value=_make_agent_result(agent_output))
        gen._agent = mock_agent
        return gen

    @pytest.mark.asyncio
    async def test_happy_path_returns_cypher(self):
        cypher_raw = "MATCH (f:FUNCTION {repoId: $project_id}) RETURN f.name AS name LIMIT 50"
        gen = self._make_generator(cypher_raw)
        result = await gen.generate("List all functions")
        assert "MATCH" in result
        assert result.endswith(";")

    @pytest.mark.asyncio
    async def test_appends_semicolon_when_missing(self):
        cypher_raw = "MATCH (n {repoId: $project_id}) RETURN n.name AS name LIMIT 50"
        gen = self._make_generator(cypher_raw)
        result = await gen.generate("show nodes")
        assert result.endswith(";")

    @pytest.mark.asyncio
    async def test_does_not_double_semicolon(self):
        cypher_raw = "MATCH (n {repoId: $project_id}) RETURN n.name AS name LIMIT 50;"
        gen = self._make_generator(cypher_raw)
        result = await gen.generate("show nodes")
        assert result.count(";") == 1

    @pytest.mark.asyncio
    async def test_strips_markdown_cypher_fence(self):
        fenced = "```cypher\nMATCH (n {repoId: $project_id}) RETURN n.name AS name LIMIT 50\n```"
        gen = self._make_generator(fenced)
        result = await gen.generate("show nodes")
        assert "```" not in result
        assert "MATCH" in result

    @pytest.mark.asyncio
    async def test_strips_plain_markdown_fence(self):
        fenced = "```\nMATCH (n {repoId: $project_id}) RETURN n.name AS name LIMIT 50\n```"
        gen = self._make_generator(fenced)
        result = await gen.generate("show nodes")
        assert "```" not in result
        assert "MATCH" in result

    @pytest.mark.asyncio
    async def test_raises_value_error_when_no_match_keyword(self):
        gen = self._make_generator("I cannot generate a Cypher query for that.")
        with pytest.raises(ValueError, match="valid Cypher"):
            await gen.generate("something weird")

    @pytest.mark.asyncio
    async def test_project_id_param_placeholder_preserved(self):
        cypher_raw = (
            "MATCH (f:FUNCTION {repoId: $project_id})-[:REFERENCES]->(g:FUNCTION) "
            "RETURN f.name AS caller, g.name AS callee LIMIT 50"
        )
        gen = self._make_generator(cypher_raw)
        result = await gen.generate("What does UserService call?")
        assert "$project_id" in result


# ---------------------------------------------------------------------------
# 2. NLCypherQueryTool.arun()
# ---------------------------------------------------------------------------

class TestNLCypherQueryTool:
    """Tests for NLCypherQueryTool.arun()."""

    def _make_tool(
        self,
        cypher_output: str | None = None,
        cypher_raises: Exception | None = None,
        neo4j_rows: list | None = None,
        neo4j_raises: Exception | None = None,
    ):
        """
        Build an NLCypherQueryTool with:
          - CypherGenerator mocked to return *cypher_output* or raise *cypher_raises*
          - Neo4j driver mocked to return *neo4j_rows* or raise *neo4j_raises*
        """
        from app.modules.intelligence.tools.kg_based_tools.nl_cypher_query_tool import (
            NLCypherQueryTool,
        )

        db = _make_db()

        # Mock CypherGenerator
        mock_gen = AsyncMock()
        if cypher_raises:
            mock_gen.generate = AsyncMock(side_effect=cypher_raises)
        else:
            mock_gen.generate = AsyncMock(return_value=cypher_output or "MATCH (n) RETURN n;")

        # Mock Neo4j driver
        mock_driver = MagicMock()
        mock_session_ctx = MagicMock()
        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        if neo4j_raises:
            mock_session.run.side_effect = neo4j_raises
        else:
            # Build lightweight record objects that dict() can consume.
            # neo4j Record supports dict() via keys()/values(); we replicate that.
            class _FakeRecord(dict):
                """dict subclass so dict(record) == record itself."""
                pass

            mock_records = [_FakeRecord(row) for row in (neo4j_rows or [])]
            mock_session.run.return_value = mock_records

        with (
            patch(
                "app.modules.intelligence.tools.kg_based_tools.nl_cypher_query_tool.CypherGenerator"
            ) as MockGen,
            patch(
                "app.modules.intelligence.tools.kg_based_tools.nl_cypher_query_tool.GraphDatabase"
            ) as MockGDB,
            patch(
                "app.modules.intelligence.tools.kg_based_tools.nl_cypher_query_tool.config_provider"
            ) as MockCfg,
        ):
            MockGen.return_value = mock_gen
            MockGDB.driver.return_value = mock_driver
            MockCfg.get_neo4j_config.return_value = {
                "uri": "bolt://localhost:7687",
                "username": "neo4j",
                "password": "test",
            }
            tool = NLCypherQueryTool(db, "user-1")
            tool._cypher_gen = mock_gen
            tool._driver = mock_driver

        return tool

    @pytest.mark.asyncio
    async def test_happy_path_returns_results(self):
        rows = [{"name": "login", "file_path": "app/auth.py"}]
        tool = self._make_tool(
            cypher_output="MATCH (f:FUNCTION {repoId: $project_id}) RETURN f.name AS name, f.file_path AS file_path LIMIT 50;",
            neo4j_rows=rows,
        )
        result = await tool.arun(project_id="proj-123", query="List all functions")

        assert "error" not in result
        assert result["count"] == 1
        assert "MATCH" in result["cypher_used"]
        assert result["results"][0]["name"] == "login"

    @pytest.mark.asyncio
    async def test_cypher_generation_failure_returns_error(self):
        tool = self._make_tool(
            cypher_raises=ValueError("LLM did not produce a valid Cypher query")
        )
        result = await tool.arun(project_id="proj-123", query="gibberish ???")

        assert "error" in result
        assert result["count"] == 0
        assert result["results"] == []
        assert "Cypher" in result["error"]

    @pytest.mark.asyncio
    async def test_neo4j_execution_failure_returns_error(self):
        tool = self._make_tool(
            cypher_output="MATCH (n {repoId: $project_id}) RETURN n.name AS name LIMIT 50;",
            neo4j_raises=RuntimeError("Neo4j connection refused"),
        )
        result = await tool.arun(project_id="proj-123", query="list nodes")

        assert "error" in result
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_empty_result_set(self):
        tool = self._make_tool(
            cypher_output="MATCH (f:FUNCTION {repoId: $project_id}) WHERE f.name = 'nonexistent' RETURN f.name AS name LIMIT 50;",
            neo4j_rows=[],
        )
        result = await tool.arun(project_id="proj-123", query="find nonexistent function")

        assert "error" not in result
        assert result["count"] == 0
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_cypher_used_is_returned_on_success(self):
        expected_cypher = (
            "MATCH (f:FUNCTION {repoId: $project_id})-[:REFERENCES]->(g:FUNCTION) "
            "RETURN f.name AS caller, g.name AS callee LIMIT 50;"
        )
        tool = self._make_tool(cypher_output=expected_cypher, neo4j_rows=[])
        result = await tool.arun(project_id="proj-123", query="call graph")

        assert result["cypher_used"] == expected_cypher

    @pytest.mark.asyncio
    async def test_cypher_used_is_returned_on_db_error(self):
        """Even when Neo4j fails, cypher_used should be in the response for debugging."""
        expected_cypher = "MATCH (n {repoId: $project_id}) RETURN n.name AS name LIMIT 50;"
        tool = self._make_tool(
            cypher_output=expected_cypher,
            neo4j_raises=RuntimeError("timeout"),
        )
        result = await tool.arun(project_id="proj-123", query="list nodes")

        assert result["cypher_used"] == expected_cypher

    @pytest.mark.asyncio
    async def test_multiple_rows_returned(self):
        rows = [
            {"name": "login", "file_path": "app/auth.py"},
            {"name": "logout", "file_path": "app/auth.py"},
            {"name": "register", "file_path": "app/auth.py"},
        ]
        tool = self._make_tool(
            cypher_output="MATCH (f:FUNCTION {repoId: $project_id}) RETURN f.name AS name, f.file_path AS file_path LIMIT 50;",
            neo4j_rows=rows,
        )
        result = await tool.arun(project_id="proj-123", query="list auth functions")

        assert result["count"] == 3
        names = [r["name"] for r in result["results"]]
        assert "login" in names
        assert "logout" in names


# ---------------------------------------------------------------------------
# 3. get_nl_cypher_query_tool() factory
# ---------------------------------------------------------------------------

class TestGetNLCypherQueryToolFactory:
    def test_returns_structured_tool(self):
        from langchain_core.tools import StructuredTool
        from app.modules.intelligence.tools.kg_based_tools.nl_cypher_query_tool import (
            get_nl_cypher_query_tool,
        )

        db = _make_db()
        with (
            patch(
                "app.modules.intelligence.tools.kg_based_tools.nl_cypher_query_tool.CypherGenerator"
            ),
            patch(
                "app.modules.intelligence.tools.kg_based_tools.nl_cypher_query_tool.GraphDatabase"
            ),
            patch(
                "app.modules.intelligence.tools.kg_based_tools.nl_cypher_query_tool.config_provider"
            ) as MockCfg,
        ):
            MockCfg.get_neo4j_config.return_value = {
                "uri": "bolt://localhost:7687",
                "username": "neo4j",
                "password": "test",
            }
            tool = get_nl_cypher_query_tool(db, "user-1")

        assert isinstance(tool, StructuredTool)

    def test_tool_has_correct_name(self):
        from app.modules.intelligence.tools.kg_based_tools.nl_cypher_query_tool import (
            get_nl_cypher_query_tool,
        )

        db = _make_db()
        with (
            patch(
                "app.modules.intelligence.tools.kg_based_tools.nl_cypher_query_tool.CypherGenerator"
            ),
            patch(
                "app.modules.intelligence.tools.kg_based_tools.nl_cypher_query_tool.GraphDatabase"
            ),
            patch(
                "app.modules.intelligence.tools.kg_based_tools.nl_cypher_query_tool.config_provider"
            ) as MockCfg,
        ):
            MockCfg.get_neo4j_config.return_value = {
                "uri": "bolt://localhost:7687",
                "username": "neo4j",
                "password": "test",
            }
            tool = get_nl_cypher_query_tool(db, "user-1")

        assert tool.name == "Query Code Graph with Natural Language"

    def test_tool_args_schema_has_project_id_and_query(self):
        from app.modules.intelligence.tools.kg_based_tools.nl_cypher_query_tool import (
            get_nl_cypher_query_tool,
            NLCypherQueryInput,
        )

        db = _make_db()
        with (
            patch(
                "app.modules.intelligence.tools.kg_based_tools.nl_cypher_query_tool.CypherGenerator"
            ),
            patch(
                "app.modules.intelligence.tools.kg_based_tools.nl_cypher_query_tool.GraphDatabase"
            ),
            patch(
                "app.modules.intelligence.tools.kg_based_tools.nl_cypher_query_tool.config_provider"
            ) as MockCfg,
        ):
            MockCfg.get_neo4j_config.return_value = {
                "uri": "bolt://localhost:7687",
                "username": "neo4j",
                "password": "test",
            }
            tool = get_nl_cypher_query_tool(db, "user-1")

        schema = tool.args_schema
        assert schema is NLCypherQueryInput
        fields = schema.model_fields
        assert "project_id" in fields
        assert "query" in fields


# ---------------------------------------------------------------------------
# 4. Registry / ToolService wiring
# ---------------------------------------------------------------------------

class TestRegistryWiring:
    def test_nl_cypher_query_in_tool_definitions(self):
        from app.modules.intelligence.tools.registry.definitions import TOOL_DEFINITIONS

        assert "nl_cypher_query" in TOOL_DEFINITIONS

    def test_nl_cypher_query_metadata(self):
        from app.modules.intelligence.tools.registry.definitions import TOOL_DEFINITIONS

        defn = TOOL_DEFINITIONS["nl_cypher_query"]
        assert defn["tier"] == "high"
        assert defn["category"] == "knowledge_graph"
        assert defn.get("read_only") is True

    def test_nl_cypher_query_in_code_gen_allow_list(self):
        from app.modules.intelligence.tools.registry.definitions import CODE_GEN_BASE_TOOLS

        assert "nl_cypher_query" in CODE_GEN_BASE_TOOLS

    def test_nl_cypher_query_in_execute_allow_list(self):
        from app.modules.intelligence.tools.registry.definitions import EXECUTE_TOOLS

        assert "nl_cypher_query" in EXECUTE_TOOLS

    def test_tool_service_initializes_nl_cypher_query(self):
        """ToolService._initialize_tools() must include 'nl_cypher_query' key."""
        from app.modules.intelligence.tools.tool_service import ToolService

        _TS = "app.modules.intelligence.tools.tool_service"

        # All symbols ToolService imports at module level that need stubbing.
        # Return None for optional tools (bash, apply, git, web, code_provider)
        # so the conditional blocks are skipped cleanly.
        patches = {
            f"{_TS}.get_nl_cypher_query_tool": MagicMock(return_value=MagicMock(name="nl_cypher_tool")),
            f"{_TS}.get_ask_knowledge_graph_queries_tool": MagicMock(),
            f"{_TS}.get_code_from_node_id_tool": MagicMock(),
            f"{_TS}.get_code_from_multiple_node_ids_tool": MagicMock(),
            f"{_TS}.GetCodeFromMultipleNodeIdsTool": MagicMock(),
            f"{_TS}.GetCodeGraphFromNodeIdTool": MagicMock(),
            f"{_TS}.GetCodeFileStructureTool": MagicMock(),
            f"{_TS}.ProviderService": MagicMock(),
            f"{_TS}.get_code_from_probable_node_name_tool": MagicMock(),
            f"{_TS}.get_nodes_from_tags_tool": MagicMock(),
            f"{_TS}.get_code_graph_from_node_id_tool": MagicMock(),
            f"{_TS}.get_change_detection_tool": MagicMock(),
            f"{_TS}.get_code_file_structure_tool": MagicMock(),
            f"{_TS}.get_node_neighbours_from_node_id_tool": MagicMock(),
            f"{_TS}.get_intelligent_code_graph_tool": MagicMock(),
            f"{_TS}.fetch_file_tool": MagicMock(),
            f"{_TS}.fetch_files_batch_tool": MagicMock(),
            f"{_TS}.universal_analyze_code_tool": MagicMock(),
            f"{_TS}.bash_command_tool": MagicMock(return_value=None),
            f"{_TS}.apply_changes_tool": MagicMock(return_value=None),
            f"{_TS}.git_commit_tool": MagicMock(return_value=None),
            f"{_TS}.git_push_tool": MagicMock(return_value=None),
            f"{_TS}.create_todo_management_tools": MagicMock(return_value=[]),
            f"{_TS}.create_code_changes_management_tools": MagicMock(return_value=[]),
            f"{_TS}.create_requirement_verification_tools": MagicMock(return_value=[]),
            f"{_TS}.get_write_wiki_page_tool": MagicMock(),
            f"{_TS}.webpage_extractor_tool": MagicMock(return_value=None),
            f"{_TS}.code_provider_tool": MagicMock(return_value=None),
            f"{_TS}.code_provider_create_branch_tool": MagicMock(return_value=None),
            f"{_TS}.code_provider_create_pull_request_tool": MagicMock(return_value=None),
            f"{_TS}.code_provider_add_pr_comments_tool": MagicMock(return_value=None),
            f"{_TS}.code_provider_update_file_tool": MagicMock(return_value=None),
            f"{_TS}.web_search_tool": MagicMock(return_value=None),
            f"{_TS}.get_linear_issue_tool": MagicMock(),
            f"{_TS}.update_linear_issue_tool": MagicMock(),
            f"{_TS}.get_jira_issue_tool": MagicMock(),
            f"{_TS}.search_jira_issues_tool": MagicMock(),
            f"{_TS}.create_jira_issue_tool": MagicMock(),
            f"{_TS}.update_jira_issue_tool": MagicMock(),
            f"{_TS}.add_jira_comment_tool": MagicMock(),
            f"{_TS}.transition_jira_issue_tool": MagicMock(),
            f"{_TS}.get_jira_projects_tool": MagicMock(),
            f"{_TS}.get_jira_project_details_tool": MagicMock(),
            f"{_TS}.get_jira_project_users_tool": MagicMock(),
            f"{_TS}.link_jira_issues_tool": MagicMock(),
            f"{_TS}.get_confluence_spaces_tool": MagicMock(),
            f"{_TS}.get_confluence_page_tool": MagicMock(),
            f"{_TS}.search_confluence_pages_tool": MagicMock(),
            f"{_TS}.get_confluence_space_pages_tool": MagicMock(),
            f"{_TS}.create_confluence_page_tool": MagicMock(),
            f"{_TS}.update_confluence_page_tool": MagicMock(),
            f"{_TS}.add_confluence_comment_tool": MagicMock(),
        }

        db = _make_db()
        # Use ExitStack to apply all patches without Python's nesting limit
        import contextlib
        with contextlib.ExitStack() as stack:
            mocks = {k: stack.enter_context(patch(k, new=v)) for k, v in patches.items()}
            svc = ToolService(db, "user-1")

        assert "nl_cypher_query" in svc.tools
        patches[f"{_TS}.get_nl_cypher_query_tool"].assert_called_once_with(db, "user-1")
