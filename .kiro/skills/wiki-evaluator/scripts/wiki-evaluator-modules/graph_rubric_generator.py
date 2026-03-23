"""
Graph Rubric Generator

Generates ground-truth evaluation rubrics for wiki/documentation by querying
the potpie code knowledge graph.  This replaces the raw file-scan approach of
the standalone ``CodeBasedRubricGenerator`` with semantically-rich graph queries,
analogous to how the QnA evaluator's Faithfulness metric retrieves context via
``ask_knowledge_graph_queries``.

The graph is queried for:
  - Overall file / module structure  (``get_code_file_structure``)
  - High-level architecture answers  (``ask_knowledge_graph_queries``)
  - Component relationships          (``get_node_neighbours_from_node_id``)

The collected graph data is then fed to an LLM to produce a structured rubric
(categories + criteria) that reflects *what actually exists in the codebase* and
*should therefore be covered by the wiki*.

Copyright 2025 Intel Corporation
Licensed under the Apache License, Version 2.0
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Architecture queries that cover all major aspects of a typical codebase
# ---------------------------------------------------------------------------

GRAPH_QUERIES: List[str] = [
    "What are the main modules and their responsibilities?",
    "What public API endpoints or entry points exist?",
    "What are the core data models or schemas?",
    "What external integrations or dependencies are used?",
    "What configuration or environment variables are used?",
    "What error handling patterns exist?",
    "What are the key design patterns or architectural decisions?",
    "What authentication or authorization mechanisms are implemented?",
]

# How many graph queries to run (cap to avoid token bloat)
MAX_GRAPH_QUERIES = 6

# How many neighbour nodes to fetch per key node
MAX_NEIGHBOUR_NODES = 3


class GraphRubricGenerator:
    """
    Generate evaluation rubrics by querying the potpie code knowledge graph.

    Works entirely through the PotpieRuntime's tool functions — no direct DB
    access needed.  Designed to be used inside the skill script where a
    ``PotpieRuntime`` is already initialised.

    Usage::

        gen = GraphRubricGenerator(runtime, project_id)
        rubrics = await gen.generate(model="github_copilot/gpt-4o")
        # rubrics = {"categories": [...]}
    """

    def __init__(self, runtime, project_id: str):
        """
        Parameters
        ----------
        runtime:
            An initialised ``PotpieRuntime`` instance.
        project_id:
            The potpie project ID whose graph to query.
        """
        self.runtime = runtime
        self.project_id = project_id

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def generate(self, model: Optional[str] = None) -> Dict[str, Any]:
        """
        Query the code graph and produce a rubric dict suitable for scoring.

        Returns
        -------
        dict
            ``{"categories": [{"name": ..., "weight": ..., "criteria": [...]}]}``
        """
        print("[graph] Collecting code graph data...")

        graph_context = await self._collect_graph_context()

        if not graph_context:
            print("[graph] ⚠  No graph data collected, returning empty rubrics")
            return {"categories": [], "source": "graph"}

        print(f"[graph] Generating rubrics from {len(graph_context)} graph responses...")
        rubrics = await self._generate_rubrics_from_context(graph_context, model)
        rubrics["source"] = "graph"
        return rubrics

    # ------------------------------------------------------------------
    # Step 1 — collect graph data
    # ------------------------------------------------------------------

    async def _collect_graph_context(self) -> List[Dict[str, str]]:
        """
        Run graph tool calls and return a list of
        ``{"query": ..., "response": ...}`` dicts.
        """
        context_items: List[Dict[str, str]] = []

        # 1a. File structure (gives an overview of modules / packages)
        try:
            structure = await self._get_file_structure()
            if structure:
                context_items.append({
                    "query": "Repository file and module structure",
                    "response": structure,
                })
                print(f"[graph] ✓ file structure ({len(structure)} chars)")
        except Exception as exc:
            print(f"[graph] ✗ file structure: {exc}")

        # 1b. Semantic graph queries
        queries_to_run = GRAPH_QUERIES[:MAX_GRAPH_QUERIES]
        for q in queries_to_run:
            try:
                answer = await self._ask_graph(q)
                if answer:
                    context_items.append({"query": q, "response": answer})
                    print(f"[graph] ✓ {q[:60]}… ({len(answer)} chars)")
            except Exception as exc:
                print(f"[graph] ✗ '{q[:50]}…': {exc}")

        return context_items

    # ------------------------------------------------------------------
    # Graph tool wrappers
    # ------------------------------------------------------------------

    async def _get_file_structure(self) -> str:
        """Call get_code_file_structure via the runtime tool service."""
        try:
            tool_service = self._get_tool_service()
            result = await asyncio.wait_for(
                tool_service.file_structure_tool.arun(self.project_id),
                timeout=30,
            )
            return str(result) if result else ""
        except Exception as exc:
            print(f"[graph] ✗ direct tool call 'get_code_file_structure': {exc}")
            return ""

    async def _ask_graph(self, query: str) -> str:
        """Call ask_knowledge_graph_queries via the runtime tool service."""
        try:
            tool_service = self._get_tool_service()
            kg_tool = tool_service.tools.get("ask_knowledge_graph_queries")
            if kg_tool is None:
                print("[graph] ✗ direct tool call 'ask_knowledge_graph_queries': tool not found in registry")
                return ""
            result = await asyncio.wait_for(
                kg_tool.arun(
                    queries=[query],
                    project_id=self.project_id,
                    node_ids=[],
                ),
                timeout=60,
            )
            return str(result) if result else ""
        except Exception as exc:
            print(f"[graph] ✗ direct tool call 'ask_knowledge_graph_queries': {exc}")
            return ""

    def _get_tool_service(self):
        """
        Return a ToolService instance, creating one from the runtime's DB session
        if the runtime does not expose ``tool_service`` directly.
        """
        # Fast path: runtime already exposes a typed tool_service accessor
        ts = getattr(self.runtime, "tool_service", None)
        if ts is not None:
            return ts

        # Build one from the runtime's database manager
        from app.modules.intelligence.tools.tool_service import ToolService

        db_manager = getattr(self.runtime, "_db_manager", None)
        if db_manager is None:
            raise AttributeError(
                "PotpieRuntime has no 'tool_service' and no '_db_manager' "
                "— cannot construct ToolService"
            )

        # Retrieve a SQLAlchemy session from the DB manager
        session = db_manager.get_session()

        # Resolve user_id from the runtime config (falls back to a safe default)
        user_id = getattr(
            getattr(self.runtime, "_config", None), "default_user_id", None
        ) or "defaultuser"

        return ToolService(session, user_id)

    # ------------------------------------------------------------------
    # Step 2 — LLM rubric generation from graph context
    # ------------------------------------------------------------------

    async def _generate_rubrics_from_context(
        self,
        context_items: List[Dict[str, str]],
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send collected graph context to an LLM and parse the rubric JSON.
        Falls back to a heuristic rubric on LLM failure.
        """
        try:
            return await self._llm_generate(context_items, model)
        except Exception as exc:
            print(f"[graph] ⚠  LLM rubric generation failed: {exc}; using fallback")
            return self._fallback_rubrics(context_items)

    async def _llm_generate(
        self,
        context_items: List[Dict[str, str]],
        model: Optional[str],
    ) -> Dict[str, Any]:
        """Call the LLM to produce structured rubrics from graph context."""
        from app.modules.intelligence.provider.copilot_model import CopilotModel
        from app.modules.intelligence.provider.litellm_model import LiteLLMModel

        model_name = (
            model
            or os.environ.get("LITELLM_MODEL_NAME")
            or os.environ.get("CHAT_MODEL")
            or "github_copilot/gpt-4o"
        )

        # Build context block
        context_block = "\n\n".join(
            f"### {item['query']}\n{item['response'][:2000]}"
            for item in context_items
        )

        system_prompt = (
            "You are a documentation quality expert. "
            "Your task is to generate evaluation rubrics that assess whether "
            "documentation adequately covers a codebase. "
            "Focus on what SHOULD be documented based on the code graph data.\n\n"
            "Return ONLY a valid JSON object with this structure:\n"
            "{\n"
            '  "categories": [\n'
            "    {\n"
            '      "name": "Category Name",\n'
            '      "weight": 0.25,\n'
            '      "criteria": [\n'
            '        "Specific measurable criterion 1",\n'
            '        "Specific measurable criterion 2"\n'
            "      ]\n"
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            "- 4–6 categories, weights summing to 1.0\n"
            "- 3–5 criteria per category, derived from the code graph data\n"
            "- Be specific to this codebase, not generic boilerplate\n"
            "- Criteria must be falsifiable (can be checked yes/no against wiki)"
        )

        user_prompt = (
            "Based on the following code graph data, generate evaluation rubrics "
            "for the wiki/documentation of this codebase.\n\n"
            f"CODE GRAPH DATA:\n\n{context_block}"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Route through the appropriate model class so headers are injected correctly
        if model_name.startswith("copilot_cli/"):
            bare = model_name.split("/", 1)[1]
            pydantic_model = CopilotModel(bare)
            from pydantic_ai import Agent as PAAgent
            agent = PAAgent(model=pydantic_model, system_prompt=system_prompt)
            result = await agent.run(user_prompt)
            raw = result.output if hasattr(result, "output") else str(result)
        else:
            # LiteLLMModel injects Editor-Version headers for github_copilot/ models
            from pydantic_ai.messages import ModelRequest, UserPromptPart, SystemPromptPart
            from pydantic_ai.models import ModelRequestParameters
            from pydantic_ai.settings import ModelSettings

            _model = LiteLLMModel(model_name)
            parts = [
                SystemPromptPart(content=system_prompt),
                UserPromptPart(content=user_prompt),
            ]
            pydantic_messages = [ModelRequest(parts=parts)]
            mrp = ModelRequestParameters(
                function_tools=[],
                output_tools=[],
                allow_text_output=True,
            )
            response = await _model.request(pydantic_messages, ModelSettings(temperature=0.3), mrp)
            text_parts = [
                part.content for part in response.parts
                if hasattr(part, "content") and isinstance(getattr(part, "content", None), str)
            ]
            raw = "\n".join(text_parts) if text_parts else ""

        return self._parse_rubric_json(raw, context_items)

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_rubric_json(
        self,
        raw: str,
        context_items: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """Extract and validate rubric JSON from LLM response."""
        # Try extracting JSON object
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in LLM response")

        rubrics = json.loads(match.group())

        if "categories" not in rubrics or not isinstance(rubrics["categories"], list):
            raise ValueError("Response missing 'categories' list")

        # Normalise weights
        total = sum(cat.get("weight", 0) for cat in rubrics["categories"])
        if total > 0:
            for cat in rubrics["categories"]:
                cat["weight"] = cat.get("weight", 0) / total

        return rubrics

    def _fallback_rubrics(
        self,
        context_items: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """
        Produce basic rubrics from context keywords when LLM generation fails.
        """
        # Build a simple text corpus from context
        corpus = " ".join(item["response"].lower() for item in context_items)

        categories: List[Dict[str, Any]] = []

        has_api = any(kw in corpus for kw in ("endpoint", "api", "route", "rest"))
        if has_api:
            categories.append({
                "name": "API Documentation",
                "weight": 0.30,
                "criteria": [
                    "Public API endpoints are documented",
                    "Request/response schemas are described",
                    "Authentication requirements are explained",
                    "Usage examples are provided for key endpoints",
                ],
            })

        has_arch = any(kw in corpus for kw in ("module", "service", "layer", "architecture"))
        if has_arch:
            categories.append({
                "name": "Architecture Overview",
                "weight": 0.25,
                "criteria": [
                    "System architecture and major components are described",
                    "Component interactions and data flow are explained",
                    "Key design decisions are documented",
                ],
            })

        has_data = any(kw in corpus for kw in ("model", "schema", "entity", "database", "table"))
        if has_data:
            categories.append({
                "name": "Data Models",
                "weight": 0.20,
                "criteria": [
                    "Core data models or schemas are documented",
                    "Field descriptions and constraints are provided",
                    "Relationships between entities are explained",
                ],
            })

        # Always include setup and config
        categories.append({
            "name": "Setup and Configuration",
            "weight": 0.15,
            "criteria": [
                "Installation and setup instructions are provided",
                "Environment variables and configuration options are documented",
                "Dependencies are listed and explained",
            ],
        })

        categories.append({
            "name": "Usage Examples",
            "weight": 0.10,
            "criteria": [
                "Code examples are provided for common use cases",
                "Getting-started guide exists",
                "Examples are complete and runnable",
            ],
        })

        # Normalise weights
        total = sum(cat["weight"] for cat in categories)
        if total > 0:
            for cat in categories:
                cat["weight"] = cat["weight"] / total

        return {"categories": categories}
