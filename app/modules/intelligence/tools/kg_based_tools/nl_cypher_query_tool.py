"""Natural-language-to-Cypher query tool.

Translates a natural language question about code structure into a Neo4j Cypher
query (via CypherGenerator / pydantic-ai), executes it, and returns the results.

Complements ask_knowledge_graph_queries (vector/semantic search) by handling
structural/relational questions:
  - "What functions does UserService call?"
  - "Which files import auth.py?"
  - "List all classes in the payments module."
"""

import asyncio
import re
from typing import Any, Dict, List

from langchain_core.tools import StructuredTool
from neo4j import GraphDatabase, READ_ACCESS
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config_provider import config_provider
from app.modules.intelligence.provider.cypher_generator import CypherGenerator
from app.modules.utils.logger import setup_logger

logger = setup_logger(__name__)

_TOOL_DESCRIPTION = """Query the code knowledge graph using a natural language question.

Translates your question into a Cypher query and runs it against the Neo4j graph.
Use this for STRUCTURAL questions about the codebase:
  - Call graphs: "What does UserService.login call?"
  - Inheritance / references: "Which classes extend BaseModel?"
  - Imports: "Which files import auth.py?"
  - File/module structure: "List all functions in the payments module."

Do NOT use this for semantic/meaning questions ("what does this function do?") —
use ask_knowledge_graph_queries for those.

:param project_id: string, the project UUID.
:param query: string, natural language question about code structure.

Returns a dict with:
  - cypher_used: the generated Cypher query (useful for debugging)
  - results: list of result rows (each row is a dict of column → value)
  - count: number of rows returned
  - error: present only on failure
"""


class NLCypherQueryInput(BaseModel):
    project_id: str = Field(description="The project/repo UUID")
    query: str = Field(
        description="Natural language question about code structure, e.g. "
        "'What functions does UserService call?'"
    )


class NLCypherQueryTool:
    name = "Query Code Graph with Natural Language"
    description = _TOOL_DESCRIPTION

    def __init__(self, sql_db: Session, user_id: str) -> None:
        self.sql_db = sql_db
        self.user_id = user_id
        self._cypher_gen = CypherGenerator(sql_db, user_id)
        neo4j_cfg = config_provider.get_neo4j_config()
        self._driver = GraphDatabase.driver(
            neo4j_cfg["uri"],
            auth=(neo4j_cfg["username"], neo4j_cfg["password"]),
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def arun(self, project_id: str, query: str) -> Dict[str, Any]:
        cypher: str = ""
        try:
            cypher = await self._cypher_gen.generate(query)
            results = await asyncio.to_thread(self._execute, cypher, project_id)
            return {
                "cypher_used": cypher,
                "results": results,
                "count": len(results),
            }
        except ValueError as e:
            # LLM failed to produce valid Cypher
            logger.warning("NLCypherQueryTool: Cypher generation failed: %s", e)
            return {
                "cypher_used": cypher,
                "results": [],
                "count": 0,
                "error": f"Could not translate query to Cypher: {e}",
            }
        except Exception as e:
            logger.exception(
                "NLCypherQueryTool: unexpected error project_id=%s query=%r",
                project_id,
                query,
            )
            return {
                "cypher_used": cypher,
                "results": [],
                "count": 0,
                "error": f"Graph query failed: {e}",
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_read_only_cypher(self, cypher: str) -> None:
        """Validate that the generated Cypher is read-only.

        Raises:
            ValueError: If the query appears to perform write/admin operations
            or otherwise looks unsafe to run in this read-only tool.
        """
        text = cypher or ""
        upper = text.upper()

        # Denylist of clearly unsafe / write / admin operations.
        forbidden_substrings = [
            " CREATE ",
            " MERGE ",
            " DELETE ",
            " DETACH ",
            " SET ",
            " REMOVE ",
            " DROP ",
            " LOAD CSV",
            " COPY ",
            " CALL DB",
            " CALL APOC",
            " CALL GDS",
            " CALL TX",
            " CALL DBMS",
            " CALL SYS",
            " INDEX ",
            " CONSTRAINT ",
            " TRIGGER ",
            " DATABASE ",
            " USER ",
            " GRANT ",
            " REVOKE ",
            " USE ",
            " BEGIN ",
            " COMMIT ",
            " ROLLBACK ",
        ]

        # Pad with spaces at both ends to make substring checks more robust.
        padded = f" {upper} "
        for token in forbidden_substrings:
            if token in padded:
                raise ValueError("Write or admin operations are not allowed in this tool.")

        # Simple allowlist on the leading keyword to keep queries strictly read-oriented.
        # Strip leading comments and whitespace, then extract the first word.
        # This is intentionally conservative.
        first_token_match = re.search(r"^[\s/\\*#-]*([A-Z]+)", upper)
        if first_token_match:
            first = first_token_match.group(1)
            allowed_leading = {
                "MATCH",
                "OPTIONAL",
                "RETURN",
                "WITH",
                "UNWIND",
                "EXPLAIN",
                "PROFILE",
            }
            if first not in allowed_leading:
                raise ValueError(
                    f"Only read-only Cypher starting with {sorted(allowed_leading)} is allowed."
                )

    def _execute(self, cypher: str, project_id: str) -> List[Dict[str, Any]]:
        """Run *cypher* synchronously and return rows as plain dicts."""
        # Enforce strict read-only Cypher before hitting the database.
        self._ensure_read_only_cypher(cypher)
        with self._driver.session(default_access_mode=READ_ACCESS) as session:
            result = session.run(cypher, project_id=project_id)
            return [dict(record) for record in result]

    def __del__(self) -> None:
        if hasattr(self, "_driver"):
            try:
                self._driver.close()
            except Exception:
                pass


# ------------------------------------------------------------------
# Factory function (matches the pattern used by all other KG tools)
# ------------------------------------------------------------------


def get_nl_cypher_query_tool(sql_db: Session, user_id: str) -> StructuredTool:
    tool = NLCypherQueryTool(sql_db, user_id)
    return StructuredTool.from_function(
        coroutine=tool.arun,
        name="Query Code Graph with Natural Language",
        description=_TOOL_DESCRIPTION,
        args_schema=NLCypherQueryInput,
    )
