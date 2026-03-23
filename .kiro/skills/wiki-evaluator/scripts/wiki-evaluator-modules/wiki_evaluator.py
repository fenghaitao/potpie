"""
Wiki Evaluator

Core evaluator implementing the full 6-step pipeline:

  Step 1: Parse wiki markdown files -> docs_tree structure
  Step 2: Generate AI rubrics from docs_tree via LLM
  Step 3: Generate graph-based rubrics via GraphRubricGenerator (replaces raw file scan)
  Step 4: Merge AI rubrics + graph rubrics -> final rubrics
  Step 5: Evaluate wiki content per-criterion with chunking (direct LLM calls)
  Step 6: Calculate weighted scores -> report

This mirrors the logic of wiki_evaluator_shim.py / multi_wiki_evaluator.py from the
standalone wiki-evaluator skill, but replaces CodeBasedRubricGenerator with the
potpie code-graph (GraphRubricGenerator) for ground-truth rubric generation.

Copyright 2025 Intel Corporation
Licensed under the Apache License, Version 2.0
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# CopilotModel LLM helper
# ---------------------------------------------------------------------------

async def _call_llm(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
) -> str:
    """
    Call the LLM via CopilotModel (copilot_cli/ prefix) or LiteLLMModel (all others).

    LiteLLMModel automatically injects the required ``Editor-Version`` /
    ``Copilot-Integration-Id`` headers for ``github_copilot/`` models, so raw
    ``litellm.acompletion`` calls (which miss those headers) are no longer used.

    Model priority:
      1. ``model`` argument
      2. ``LITELLM_MODEL_NAME`` env var
      3. ``CHAT_MODEL`` env var
      4. Hard-coded default ``github_copilot/gpt-4o``
    """
    model_name = (
        model
        or os.environ.get("LITELLM_MODEL_NAME")
        or os.environ.get("CHAT_MODEL")
        or "github_copilot/gpt-4o"
    )

    try:
        if model_name.startswith("copilot_cli/"):
            # Use the Copilot CLI SDK model (pydantic-ai based)
            from app.modules.intelligence.provider.copilot_model import CopilotModel
            from pydantic_ai import Agent as _PAAgent
            bare_name = model_name.split("/", 1)[1]
            _model = CopilotModel(bare_name)
            # Extract system prompt and user prompt from messages
            system_prompt = next(
                (m["content"] for m in messages if m.get("role") == "system"), None
            )
            user_content = "\n".join(
                m["content"] for m in messages if m.get("role") == "user"
            )
            _agent = _PAAgent(model=_model, system_prompt=system_prompt or "You are a helpful assistant.")
            result = await _agent.run(user_content)
            return result.output if hasattr(result, "output") else str(result)
        else:
            # Use LiteLLMModel which injects Editor-Version headers for github_copilot/ models
            from app.modules.intelligence.provider.litellm_model import LiteLLMModel
            from pydantic_ai.messages import ModelRequest, UserPromptPart, SystemPromptPart
            from pydantic_ai.models import ModelRequestParameters
            from pydantic_ai.settings import ModelSettings

            _model = LiteLLMModel(model_name)
            # Build pydantic-ai message list
            parts: List[Any] = []
            for m in messages:
                if m.get("role") == "system":
                    parts.append(SystemPromptPart(content=m["content"]))
                elif m.get("role") == "user":
                    parts.append(UserPromptPart(content=m["content"]))
            pydantic_messages = [ModelRequest(parts=parts)]
            mrp = ModelRequestParameters(
                function_tools=[],
                output_tools=[],
                allow_text_output=True,
            )
            response = await _model.request(pydantic_messages, ModelSettings(temperature=0.3), mrp)
            # Extract text from the response parts
            text_parts = [
                part.content for part in response.parts
                if hasattr(part, "content") and isinstance(getattr(part, "content", None), str)
            ]
            return "\n".join(text_parts) if text_parts else ""
    except Exception as exc:
        raise RuntimeError(f"LLM call failed (model={model_name!r}): {exc}") from exc


# ---------------------------------------------------------------------------
# DocsProxy -- wraps a docs_tree dict (mirrors wiki_evaluator_shim.DocsProxy)
# ---------------------------------------------------------------------------

_SECTION_CONTENT_LIMIT = 600

# Default context-window size in tokens assumed for the target LLM.
# At ~1.25 chars/token this gives the default CHUNK_SIZE below.
# Override via WikiEvaluator(context_window=...) or --context-window CLI flag.
DEFAULT_CONTEXT_WINDOW_TOKENS = 120_000  # safe default for 128K-window models

# Characters per wiki chunk fed to a single LLM evaluation call.
# Derived from DEFAULT_CONTEXT_WINDOW_TOKENS leaving ~20 % headroom for the
# prompt template + criterion text + JSON response.
# Formula: floor(tokens * chars_per_token * 0.80)  where chars_per_token ≈ 1.25
# 120_000 * 1.25 * 0.80 = 120_000
CHUNK_SIZE = int(DEFAULT_CONTEXT_WINDOW_TOKENS * 1.25 * 0.80)  # 120_000 chars


def _chunk_size_for_window(context_window_tokens: int) -> int:
    """
    Calculate the wiki-content chunk size (chars) for a given context window.

    Reserves ~20 % of the window for the system prompt, criterion text, and
    the JSON response, then converts tokens → characters at 1.25 chars/token.
    """
    usable_tokens = int(context_window_tokens * 0.80)
    return int(usable_tokens * 1.25)


def _batch_size_for_window(context_window_tokens: int) -> int:
    """
    Calculate a safe concurrent-batch size for a given context window.

    Larger context windows mean larger (heavier) per-call payloads, so we
    reduce concurrency to avoid rate-limit / OOM pressure:
      ≤  64K tokens → 8 concurrent calls
      ≤ 128K tokens → 6 concurrent calls
      ≤ 256K tokens → 4 concurrent calls
      >  256K tokens → 2 concurrent calls
    """
    if context_window_tokens <= 64_000:
        return 8
    if context_window_tokens <= 128_000:
        return 6
    if context_window_tokens <= 256_000:
        return 4
    return 2


class DocsProxy:
    """Lightweight wrapper around a docs_tree dict or raw wiki content."""

    def __init__(self, tree_data: Dict[str, Any]):
        self.tree_data = tree_data
        self._cached_summary: Optional[str] = None

    @classmethod
    def from_wiki_content(cls, wiki_content: str) -> "DocsProxy":
        """Create a DocsProxy directly from flat wiki text (no tree parsing)."""
        proxy = cls.__new__(cls)
        proxy.tree_data = {}
        proxy._cached_summary = wiki_content
        return proxy

    def get_content_summary(self) -> str:
        """Return structured content from the docs_tree (with per-section truncation)."""
        if self._cached_summary is not None:
            return self._cached_summary

        lines: List[str] = []
        pages = self.tree_data.get("subpages", [])

        if not pages:
            titles = self._extract_section_titles(self.tree_data)
            self._cached_summary = (
                f"Documentation contains {len(titles)} sections:\n"
                + "\n".join(f"- {t}" for t in titles)
            )
            return self._cached_summary

        for page in pages:
            page_title = page.get("title", "").replace("_", " ")
            lines.append(f"\n## {page_title}")
            for section in page.get("sections", []):
                sec_title = section.get("title", "").strip()
                content = section.get("content", "").strip()
                if not sec_title and not content:
                    continue
                if sec_title:
                    lines.append(f"### {sec_title}")
                if content:
                    if len(content) > _SECTION_CONTENT_LIMIT:
                        lines.append(content[:_SECTION_CONTENT_LIMIT] + "...")
                    else:
                        lines.append(content)

        self._cached_summary = "\n".join(lines)
        return self._cached_summary

    def _extract_section_titles(self, node, prefix: str = "") -> List[str]:
        sections: List[str] = []
        if isinstance(node, dict):
            title = node.get("title", "")
            if title:
                full = f"{prefix}{title}" if prefix else title
                sections.append(full)
                for sub in node.get("subpages", []):
                    sections.extend(self._extract_section_titles(sub, f"{full} > "))
        elif isinstance(node, list):
            for item in node:
                sections.extend(self._extract_section_titles(item, prefix))
        return sections


# ---------------------------------------------------------------------------
# Wiki parser -- converts markdown files to a docs_tree dict
# ---------------------------------------------------------------------------


def parse_wiki_directory(wiki_dir: Path) -> Dict[str, Any]:
    """
    Parse all .md files in wiki_dir into a docs_tree structure.

    Each markdown file becomes a page with sections split by ## headings.
    Returns:
        {"title": "<wiki dir name>", "subpages": [
            {"title": "<filename>", "sections": [{"title": ..., "content": ...}]},
        ]}
    """
    if not wiki_dir or not wiki_dir.exists():
        return {"title": wiki_dir.name if wiki_dir else "wiki", "subpages": []}

    subpages: List[Dict[str, Any]] = []
    for md_file in sorted(wiki_dir.rglob("*.md")):
        try:
            rel = md_file.relative_to(wiki_dir)
            raw = md_file.read_text(encoding="utf-8", errors="replace")
            sections = _split_into_sections(raw)
            title = str(rel).replace("\\", "/")
            if title.endswith(".md"):
                title = title[:-3]
            subpages.append({"title": title, "sections": sections})
        except Exception as exc:
            print(f"[wiki] WARN: Could not parse {md_file}: {exc}")

    return {"title": wiki_dir.name.lstrip(".") or "wiki", "subpages": subpages}


def _split_into_sections(markdown_text: str) -> List[Dict[str, str]]:
    """Split markdown into sections on ## headings."""
    sections: List[Dict[str, str]] = []
    current_title = ""
    current_lines: List[str] = []

    for line in markdown_text.splitlines():
        if line.startswith("## "):
            if current_lines or current_title:
                sections.append({
                    "title": current_title,
                    "content": "\n".join(current_lines).strip(),
                })
            current_title = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines or current_title:
        sections.append({
            "title": current_title,
            "content": "\n".join(current_lines).strip(),
        })

    return sections


# ---------------------------------------------------------------------------
# Step 2 -- AI rubric generator from docs_tree
# ---------------------------------------------------------------------------

_AI_RUBRIC_SYSTEM_PROMPT = """\
You are a skilled technical assistant assigned to analyze the official documentation of a software repository.
Your task is to reconstruct the internal structure and logic of the system from the provided documentation.

# OBJECTIVE
Develop a flat evaluation rubric (categories + criteria) that captures the underlying architecture
and key functionality of the repository. Each criterion must be:
- Specific and measurable (can be checked yes/no against the wiki)
- Derived from what the documentation actually covers
- At most one sentence

# DELIVERABLE FORMAT
Return ONLY a valid JSON object:
{
  "categories": [
    {
      "name": "Category Name",
      "weight": 0.25,
      "criteria": [
        "Specific measurable criterion 1",
        "Specific measurable criterion 2"
      ]
    }
  ]
}

Rules:
- 4-6 categories, weights summing to 1.0
- 3-5 criteria per category
- Be specific to this codebase, not generic boilerplate
"""


async def generate_ai_rubrics(
    docs_tree: Dict[str, Any],
    source_name: str,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate rubrics from the docs_tree structure via LLM (Step 2).

    Mirrors AIRubricGenerator._generate_without_tools() from multi_wiki_evaluator.py.
    Returns {"categories": [...], "source": "ai"}.
    """
    print(f"[wiki-eval] Step 2: Generating AI rubrics from '{source_name}' docs tree...")

    summary_lines: List[str] = []
    for page in docs_tree.get("subpages", []):
        page_title = page.get("title", "")
        summary_lines.append(f"\n## {page_title}")
        for sec in page.get("sections", []):
            sec_title = sec.get("title", "").strip()
            content = sec.get("content", "").strip()
            if sec_title:
                summary_lines.append(f"### {sec_title}")
            if content:
                summary_lines.append(content[:400] + ("..." if len(content) > 400 else ""))

    docs_summary = "\n".join(summary_lines)[:12_000]

    user_prompt = (
        f"Given the following documentation for repository '{source_name}':\n\n"
        f"{docs_summary}\n\n"
        "Generate evaluation rubrics that describe what this system covers. "
        "Return ONLY the JSON object."
    )

    try:
        raw = await _call_llm(
            messages=[
                {"role": "system", "content": _AI_RUBRIC_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            model=model,
        )
        rubrics = _parse_rubric_json(raw)
        rubrics["source"] = "ai"
        print(f"[wiki-eval] OK AI rubrics: {len(rubrics.get('categories', []))} categories")
        return rubrics
    except Exception as exc:
        print(f"[wiki-eval] WARN AI rubric generation failed: {exc}; using fallback")
        return _fallback_ai_rubrics(docs_tree, source_name)


def _fallback_ai_rubrics(docs_tree: Dict[str, Any], source_name: str) -> Dict[str, Any]:
    """Keyword-based fallback AI rubrics when LLM call fails."""
    sections = _extract_all_section_titles(docs_tree)
    corpus = " ".join(s.lower() for s in sections)

    categories: List[Dict[str, Any]] = []

    if any(kw in corpus for kw in ("install", "setup", "getting started", "quickstart")):
        categories.append({
            "name": "Installation and Setup",
            "weight": 0.20,
            "criteria": [
                "Installation instructions are provided",
                "Prerequisites are documented",
                "Setup steps are clear and complete",
            ],
        })

    if any(kw in corpus for kw in ("api", "endpoint", "route", "function", "method")):
        categories.append({
            "name": "API Documentation",
            "weight": 0.30,
            "criteria": [
                "Public API endpoints or functions are documented",
                "Parameters and return values are described",
                "Usage examples are provided for key APIs",
            ],
        })

    if any(kw in corpus for kw in ("architecture", "overview", "design", "component")):
        categories.append({
            "name": "Architecture Overview",
            "weight": 0.25,
            "criteria": [
                "System architecture and major components are described",
                "Component interactions are documented",
                "Design decisions are explained",
            ],
        })

    if any(kw in corpus for kw in ("example", "tutorial", "guide", "usage")):
        categories.append({
            "name": "Examples and Guides",
            "weight": 0.15,
            "criteria": [
                "Code examples are provided",
                "Common use cases are demonstrated",
                "Getting-started guide exists",
            ],
        })

    categories.append({
        "name": "General Documentation Quality",
        "weight": 0.10,
        "criteria": [
            "Documentation is well-structured and navigable",
            "Key concepts are explained clearly",
        ],
    })

    total = sum(c["weight"] for c in categories)
    if total > 0:
        for cat in categories:
            cat["weight"] = round(cat["weight"] / total, 4)

    return {"categories": categories, "source": "ai"}


def _extract_all_section_titles(docs_tree: Dict[str, Any]) -> List[str]:
    titles: List[str] = []

    def _walk(node):
        if isinstance(node, dict):
            if "title" in node:
                titles.append(node["title"])
            for sec in node.get("sections", []):
                if isinstance(sec, dict) and sec.get("title"):
                    titles.append(sec["title"])
            for sub in node.get("subpages", []):
                _walk(sub)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(docs_tree)
    return titles


# ---------------------------------------------------------------------------
# Step 4 -- Rubric merger (AI rubrics + graph rubrics)
# ---------------------------------------------------------------------------


def merge_rubrics(
    ai_rubrics: Dict[str, Any],
    graph_rubrics: Dict[str, Any],
    ai_weight: float = 0.4,
    graph_weight: float = 0.6,
) -> Dict[str, Any]:
    """
    Merge AI-generated rubrics with graph-derived rubrics into final rubrics.

    Mirrors FinalRubricMerger.merge_ai_and_code_rubrics() from multi_wiki_evaluator.py.
    Strategy:
    - Graph categories carry graph_weight share (higher ground-truth weight)
    - AI-only categories (not already covered by graph) carry ai_weight share
    - Re-normalise weights so all sum to 1.0
    """
    ai_cats = ai_rubrics.get("categories", [])
    graph_cats = graph_rubrics.get("categories", [])

    if not ai_cats and not graph_cats:
        return {"categories": [], "source": "merged"}

    if not ai_cats:
        return {**graph_rubrics, "source": "merged"}

    if not graph_cats:
        return {**ai_rubrics, "source": "merged"}

    merged: List[Dict[str, Any]] = []

    total_graph_weight = sum(c.get("weight", 0.1) for c in graph_cats) or 1.0
    for cat in graph_cats:
        norm_w = cat.get("weight", 0.1) / total_graph_weight
        merged.append({
            "name": cat["name"],
            "weight": norm_w * graph_weight,
            "criteria": list(cat.get("criteria", [])),
            "source": "graph",
        })

    graph_names_lower = {c["name"].lower() for c in graph_cats}
    ai_only = [c for c in ai_cats if c["name"].lower() not in graph_names_lower]

    if ai_only:
        total_ai_weight = sum(c.get("weight", 0.1) for c in ai_only) or 1.0
        for cat in ai_only:
            norm_w = cat.get("weight", 0.1) / total_ai_weight
            merged.append({
                "name": cat["name"],
                "weight": norm_w * ai_weight,
                "criteria": list(cat.get("criteria", [])),
                "source": "ai",
            })

    total_w = sum(c["weight"] for c in merged) or 1.0
    for cat in merged:
        cat["weight"] = round(cat["weight"] / total_w, 4)

    return {"categories": merged, "source": "merged"}


# ---------------------------------------------------------------------------
# Step 5 -- Per-criterion evaluation with chunking
# ---------------------------------------------------------------------------

_EVAL_SYSTEM_PROMPT = """\
You are a documentation evaluation expert. Your task is to determine whether a specific \
criterion is adequately covered in the provided wiki/documentation content.

# SCORING SCALE
- 1 (Documented): The criterion is explicitly explained, described, or meaningfully addressed \
with enough detail that a reader would understand the concept. A passing mention of the topic \
without any useful detail does NOT qualify.
- 0 (Not Documented): The criterion is absent, only superficially mentioned with no supporting \
detail, or the information is too vague to be useful.

# EVALUATION GUIDELINES
- Read the full documentation content before judging.
- Focus on substance: a criterion is met only if a reader could act on or understand it from \
the documentation alone.
- Do not infer or assume content that is not explicitly present.
- If a criterion is partially addressed, score 0 and note what is missing in your reasoning.
- Quote the most relevant excerpt verbatim as your evidence (max 200 characters); \
use "none" only if the topic is completely absent.

# OUTPUT FORMAT
You MUST respond with ONLY a valid JSON object — no preamble, no explanation outside the JSON:
{
  "criteria": "<criterion text>",
  "score": 0 or 1,
  "reasoning": "<one or two sentences explaining your decision>",
  "evidence": "<direct quote from the documentation, or 'none'>"
}
"""


async def _evaluate_single_criterion(
    criterion: str,
    category: str,
    doc_content: str,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Evaluate one criterion against doc_content via LLM, return result dict."""
    prompt = (
        f"Documentation Content:\n{doc_content}\n\n"
        f"Criterion to evaluate:\n\"{criterion}\"\n\n"
        "Read the documentation above carefully. Does it cover this criterion? "
        "Respond with JSON only."
    )

    last_exc = None
    try:
        raw = await _call_llm(
            messages=[
                {"role": "system", "content": _EVAL_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            model=model,
        )
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            return {
                "category": category,
                "criteria": criterion,
                "score": int(data.get("score", 0)),
                "reasoning": data.get("reasoning", ""),
                "evidence": data.get("evidence", ""),
            }
    except Exception as exc:
        last_exc = exc
        print(f"[wiki-eval] WARN Error evaluating '{criterion[:50]}...': {exc}")

    return {
        "category": category,
        "criteria": criterion,
        "score": 0,
        "reasoning": f"evaluation error: {last_exc if last_exc else 'unknown'}",
        "evidence": "",
    }


def _chunk_content(content: str, chunk_size: int = CHUNK_SIZE) -> List[str]:
    """Split content into chunks of at most chunk_size characters."""
    if len(content) <= chunk_size:
        return [content]
    chunks: List[str] = []
    start = 0
    while start < len(content):
        end = min(start + chunk_size, len(content))
        boundary = content.rfind("\n\n", start, end)
        if boundary > start:
            end = boundary
        chunks.append(content[start:end])
        start = end
    return chunks


async def _evaluate_criterion_chunked(
    criterion: str,
    category: str,
    wiki_content: str,
    model: Optional[str] = None,
    chunk_size: int = CHUNK_SIZE,
) -> Dict[str, Any]:
    """
    Evaluate a criterion, splitting wiki_content into chunks if needed.
    Score is 1 if criterion is found in ANY chunk (short-circuit on first hit).

    ``chunk_size`` is the maximum characters per chunk and should be set from
    ``WikiEvaluator.chunk_size`` (derived from the model's context window).
    """
    chunks = _chunk_content(wiki_content, chunk_size)
    if len(chunks) == 1:
        return await _evaluate_single_criterion(criterion, category, chunks[0], model)

    best_result: Optional[Dict[str, Any]] = None
    for chunk in chunks:
        result = await _evaluate_single_criterion(criterion, category, chunk, model)
        if result["score"] == 1:
            return result
        if best_result is None:
            best_result = result

    return best_result or {
        "category": category, "criteria": criterion, "score": 0,
        "reasoning": "not found in any chunk", "evidence": "",
    }


# ---------------------------------------------------------------------------
# Step 6 -- Weighted scoring
# ---------------------------------------------------------------------------


def _calculate_scores(
    results: List[Dict[str, Any]],
    rubrics: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Calculate overall and per-category scores.

    Every criterion — regardless of its score or reasoning — is counted in
    both the numerator and the denominator.  No categories are skipped.
    ``skipped_categories`` is kept in the return dict for API compatibility
    but will always be an empty dict.
    """
    cat_results: Dict[str, List[Dict]] = {}
    for r in results:
        cat_results.setdefault(r["category"], []).append(r)

    cat_weights = {
        c["name"]: c.get("weight", 0.1)
        for c in rubrics.get("categories", [])
    }

    category_scores: Dict[str, float] = {}
    skipped_categories: Dict[str, str] = {}

    for cat, cat_res in cat_results.items():
        scores = [r["score"] for r in cat_res]
        n = len(scores)
        total_score = sum(scores)
        cat_score = total_score / n if n > 0 else 0.0

        category_scores[cat] = cat_score

    scored_cats = list(category_scores.keys())
    if scored_cats:
        weight_sum = sum(cat_weights.get(cat, 0.1) for cat in scored_cats)
        if weight_sum > 0:
            overall_score = sum(
                category_scores[cat] * cat_weights.get(cat, 0.1)
                for cat in scored_cats
            ) / weight_sum
        else:
            overall_score = 0.0
    else:
        overall_score = 0.0

    scored_results = [r for r in results if r["category"] in category_scores]
    met_requirements = sum(1 for r in scored_results if r["score"] == 1)
    total_requirements = len(scored_results)
    total_all = len(results)
    met_all = sum(1 for r in results if r["score"] == 1)

    return {
        "overall_score": overall_score,
        "overall_pct": f"{overall_score:.1%}",
        "total_requirements": total_requirements,
        "met_requirements": met_requirements,
        "total_requirements_including_skipped": total_all,
        "met_requirements_including_skipped": met_all,
        "scores_by_category": category_scores,
        "skipped_categories": skipped_categories,
        "detailed_results": results,
        # Aliases used in report / test code
        "total_criteria": total_requirements,
        "met_criteria": met_requirements,
        "category_scores": {
            cat: {
                "score": score,
                "met": sum(1 for r in cat_results.get(cat, []) if r["score"] == 1),
                "total": len(cat_results.get(cat, [])),
            }
            for cat, score in category_scores.items()
        },
    }


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def _parse_rubric_json(raw: str) -> Dict[str, Any]:
    """Extract and validate a rubric JSON object from an LLM response."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in LLM response")

    rubrics = json.loads(match.group())

    if "categories" not in rubrics or not isinstance(rubrics["categories"], list):
        raise ValueError("Response missing 'categories' list")

    total = sum(cat.get("weight", 0) for cat in rubrics["categories"])
    if total > 0:
        for cat in rubrics["categories"]:
            cat["weight"] = round(cat.get("weight", 0) / total, 4)

    return rubrics


# ---------------------------------------------------------------------------
# Main WikiEvaluator class
# ---------------------------------------------------------------------------


class WikiEvaluator:
    """
    Evaluates wiki/documentation using the full 6-step pipeline.

    GraphRubricGenerator is called externally and the result passed as
    ``graph_rubrics``.  This class handles Steps 1-2 and 4-6.
    """

    def __init__(self, model: Optional[str] = None, context_window: Optional[int] = None):
        self.model = (
            model
            or os.environ.get("LITELLM_MODEL_NAME")
            or os.environ.get("CHAT_MODEL")
            or "github_copilot/gpt-4o"
        )
        self.model_name = self.model  # alias for test compatibility

        # Context window (tokens) drives both chunk size and batch concurrency.
        # Priority: constructor arg → WIKI_CONTEXT_WINDOW env var → default.
        _env_window = os.environ.get("WIKI_CONTEXT_WINDOW")
        self.context_window: int = (
            context_window
            or (int(_env_window) if _env_window and _env_window.isdigit() else None)
            or DEFAULT_CONTEXT_WINDOW_TOKENS
        )
        self.chunk_size: int = _chunk_size_for_window(self.context_window)
        self.batch_size: int = _batch_size_for_window(self.context_window)

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def evaluate(
        self,
        wiki_content: str,
        graph_rubrics: Dict[str, Any],
        wiki_dir: Optional[Path] = None,
        ai_weight: float = 0.4,
        graph_weight: float = 0.6,
    ) -> Dict[str, Any]:
        """
        Synchronous entry point -- runs the async pipeline via asyncio.run.

        Parameters
        ----------
        wiki_content:
            Full text of the wiki (all markdown files joined).
        graph_rubrics:
            Graph-derived rubrics from GraphRubricGenerator.
        wiki_dir:
            Optional path to wiki directory for AI rubric generation (Steps 1+2).
            If None, AI rubrics are skipped and only graph rubrics are used.
        ai_weight / graph_weight:
            Merging weights for Step 4.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run,
                    self._evaluate_async(wiki_content, graph_rubrics, wiki_dir, ai_weight, graph_weight),
                )
                return future.result(timeout=600)
        else:
            return asyncio.run(
                self._evaluate_async(wiki_content, graph_rubrics, wiki_dir, ai_weight, graph_weight)
            )

    async def evaluate_async(
        self,
        wiki_content: str,
        graph_rubrics: Dict[str, Any],
        wiki_dir: Optional[Path] = None,
        ai_weight: float = 0.4,
        graph_weight: float = 0.6,
        final_rubrics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Async entry point (call directly from async code).

        Parameters
        ----------
        final_rubrics:
            When provided, skip Steps 1-2 (AI rubric generation) and Step 4
            (merging) and use these rubrics directly for evaluation.
            Used by Mode A (reference-docs mode) in run_pipeline.
        """
        return await self._evaluate_async(
            wiki_content, graph_rubrics, wiki_dir, ai_weight, graph_weight,
            final_rubrics=final_rubrics,
        )

    # ------------------------------------------------------------------
    # Async pipeline
    # ------------------------------------------------------------------

    async def _evaluate_async(
        self,
        wiki_content: str,
        graph_rubrics: Dict[str, Any],
        wiki_dir: Optional[Path],
        ai_weight: float,
        graph_weight: float,
        final_rubrics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        # ------------------------------------------------------------------
        # If final_rubrics is provided (Mode A), skip Steps 1-2-4 entirely
        # ------------------------------------------------------------------
        if final_rubrics is not None:
            n_merged = sum(len(c.get("criteria", [])) for c in final_rubrics.get("categories", []))
            print(f"\n[wiki-eval] Mode A — evaluating against reference-docs rubrics: "
                  f"{len(final_rubrics.get('categories', []))} categories, {n_merged} criteria")
            if n_merged == 0:
                return self._empty_result()
            flat_criteria = self._flatten_criteria(final_rubrics)
            all_results = await self._run_eval_batches(flat_criteria, wiki_content)
            scores = _calculate_scores(all_results, final_rubrics)
            scores["model"] = self.model
            scores["rubrics_used"] = {
                "ai_categories": 0,
                "graph_categories": 0,
                "merged_categories": len(final_rubrics.get("categories", [])),
            }
            scores["detailed_criteria"] = self._format_detailed(all_results)
            overall = scores["overall_score"]
            met = scores["met_requirements"]
            total = scores["total_requirements"]
            print(f"[wiki-eval] OK Overall score: {overall:.1%}  ({met}/{total} criteria met)")
            return scores

        # Step 1+2: AI rubrics from docs tree
        ai_rubrics: Dict[str, Any] = {"categories": []}
        if wiki_dir and wiki_dir.exists():
            print("\n[wiki-eval] Step 1: Parsing wiki directory into docs_tree...")
            docs_tree = parse_wiki_directory(wiki_dir)
            n_pages = len(docs_tree.get("subpages", []))
            print(f"[wiki-eval] OK Parsed {n_pages} pages from {wiki_dir.name}")
            ai_rubrics = await generate_ai_rubrics(docs_tree, wiki_dir.name.lstrip("."), self.model)
        else:
            print("[wiki-eval] Step 1+2: Skipped (no wiki_dir) -- using graph rubrics only")

        # Step 3: Graph rubrics provided externally
        n_graph_cats = len(graph_rubrics.get("categories", []))
        n_graph_crit = sum(len(c.get("criteria", [])) for c in graph_rubrics.get("categories", []))
        print(f"\n[wiki-eval] Step 3: Graph rubrics: {n_graph_cats} categories, {n_graph_crit} criteria")

        # Step 4: Merge
        print("\n[wiki-eval] Step 4: Merging AI + graph rubrics...")
        merged_rubrics = merge_rubrics(ai_rubrics, graph_rubrics, ai_weight, graph_weight)
        n_merged = sum(len(c.get("criteria", [])) for c in merged_rubrics.get("categories", []))
        print(f"[wiki-eval] OK Final rubrics: {len(merged_rubrics.get('categories', []))} categories, "
              f"{n_merged} criteria total")

        if n_merged == 0:
            return self._empty_result()

        # Step 5: Evaluate per criterion
        print(f"\n[wiki-eval] Step 5: Evaluating {n_merged} criteria "
              f"(content length: {len(wiki_content):,} chars)...")

        flat_criteria = self._flatten_criteria(merged_rubrics)
        all_results = await self._run_eval_batches(flat_criteria, wiki_content)

        # Step 6: Calculate weighted scores
        print("\n[wiki-eval] Step 6: Calculating weighted scores...")
        scores = _calculate_scores(all_results, merged_rubrics)

        scores["model"] = self.model
        scores["rubrics_used"] = {
            "ai_categories": len(ai_rubrics.get("categories", [])),
            "graph_categories": n_graph_cats,
            "merged_categories": len(merged_rubrics.get("categories", [])),
        }
        scores["detailed_criteria"] = self._format_detailed(all_results)

        overall = scores["overall_score"]
        met = scores["met_requirements"]
        total = scores["total_requirements"]
        print(f"[wiki-eval] OK Overall score: {overall:.1%}  ({met}/{total} criteria met)")

        return scores

    async def _run_eval_batches(
        self,
        flat_criteria: List[Dict[str, Any]],
        wiki_content: str,
    ) -> List[Dict[str, Any]]:
        """Run per-criterion evaluation in batches and return all result dicts."""
        print(f"[wiki-eval] Config: context_window={self.context_window:,} tokens, "
              f"chunk_size={self.chunk_size:,} chars, batch_size={self.batch_size}")
        all_results: List[Dict[str, Any]] = []
        total_batches = (len(flat_criteria) + self.batch_size - 1) // self.batch_size
        for i in range(0, len(flat_criteria), self.batch_size):
            batch = flat_criteria[i:i + self.batch_size]
            batch_num = i // self.batch_size + 1
            print(f"[wiki-eval] Batch {batch_num}/{total_batches} ({len(batch)} criteria)...")
            batch_results = await asyncio.gather(*[
                _evaluate_criterion_chunked(
                    item["criterion"], item["category"], wiki_content, self.model,
                    chunk_size=self.chunk_size,
                )
                for item in batch
            ])
            all_results.extend(batch_results)
        return all_results

    def _format_detailed(self, all_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Format raw evaluation results into the detailed_criteria report format."""
        return [
            {
                "category": r["category"],
                "criterion": r["criteria"],
                "score": r["score"],
                "overall_score": float(r["score"]),
                "reasoning": r.get("reasoning", ""),
                "evidence": r.get("evidence", ""),
            }
            for r in all_results
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _flatten_criteria(self, rubrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Flatten categories + criteria into a flat list of dicts."""
        flat: List[Dict[str, Any]] = []
        for cat in rubrics.get("categories", []):
            cat_name = cat.get("name", "General")
            cat_weight = float(cat.get("weight", 0.1))
            for crit in cat.get("criteria", []):
                flat.append({
                    "category": cat_name,
                    "category_weight": cat_weight,
                    "criterion": str(crit),
                })
        return flat

    def _aggregate(
        self,
        case_results: List[Dict[str, Any]],
        rubrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Aggregate per-criterion results (for test compatibility)."""
        if not case_results:
            return self._empty_result()
        return _calculate_scores(
            [
                {
                    "category": r["category"],
                    "criteria": r.get("criterion", r.get("criteria", "")),
                    "score": int(round(r.get("overall_score", r.get("score", 0)))),
                    "reasoning": r.get("reasoning", ""),
                    "evidence": r.get("evidence", ""),
                }
                for r in case_results
            ],
            rubrics,
        )

    def _empty_result(self) -> Dict[str, Any]:
        return {
            "overall_score": 0.0,
            "overall_pct": "0.0%",
            "total_requirements": 0,
            "met_requirements": 0,
            "total_requirements_including_skipped": 0,
            "met_requirements_including_skipped": 0,
            "scores_by_category": {},
            "skipped_categories": {},
            "detailed_results": [],
            "total_criteria": 0,
            "met_criteria": 0,
            "category_scores": {},
            "detailed_criteria": [],
            "model": getattr(self, "model", None),
        }


# ---------------------------------------------------------------------------
# Backward-compat dataclass (kept so existing test imports work)
# ---------------------------------------------------------------------------


@dataclass
class _CoverageInput:
    criterion: str
    wiki_content: str
