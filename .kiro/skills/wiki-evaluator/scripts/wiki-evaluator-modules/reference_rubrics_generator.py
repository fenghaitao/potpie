"""
Reference Rubrics Generator

Ports generate_rubrics.py + combine_rubrics.py from CodeWikiBench to the
wiki-evaluator skill.

Pipeline
--------
1. ``generate_rubrics_from_docs_tree(docs_tree, model)``
   — sends the docs_tree JSON to an LLM and gets back a hierarchical rubric
     list in the CodeWikiBench ``sub_tasks`` format.

2. ``combine_rubrics(rubric_sets, model)``
   — calls the LLM to semantically merge N rubric sets into one combined set.
     Falls back to a simple dedup-merge on LLM failure.

3. ``flatten_rubrics_to_categories(combined_rubrics)``
   — converts the hierarchical ``sub_tasks`` rubric format into the flat
     ``{"categories": [...]}`` format consumed by ``WikiEvaluator``.

4. High-level helper ``generate_reference_rubrics(docs_tree, model)``
   — runs steps 1 + 3 for a single-model workflow (no multi-model combining).

All LLM calls go through the same ``_call_llm`` helper used by wiki_evaluator.py.

Copyright 2025 Intel Corporation
Licensed under the Apache License, Version 2.0
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# System prompts (ported from generate_rubrics.py)
# ---------------------------------------------------------------------------

_GENERATE_SYSTEM_PROMPT = """\
You are a skilled technical assistant assigned to analyze the reference documentation of a software repository.
You will be provided with a documentation tree written primarily in a HOW-TO-USE format, which focuses on how to operate the repository's features and tools.
Your task is to reverse-engineer and reconstruct the internal structure and logic of the system by transforming this HOW-TO-USE information into a HOW-DOES-IT-WORK perspective.

# OBJECTIVE
Develop a hierarchical rubric that captures the underlying architecture and working principles of the repository. This rubric should reflect what the system does and how its parts interact, abstracting away from usage instructions into architectural insight.

# DELIVERABLE FORMAT
Return the rubrics in the following nested JSON format, where:
- Each rubric item includes a "requirements" field summarizing the system concept or functionality.
- Each item is assigned a "weight" to indicate its importance:
  - 3 = Essential to the system's core functionality
  - 2 = Important but not core
  - 1 = Minor or supporting functionality
- Items can recursively contain "sub_tasks" that break down more specific elements.

[
  {
    "requirements": "Top-level concept or component",
    "weight": 3,
    "sub_tasks": [
      {
        "requirements": "More specific concept or subcomponent",
        "weight": 2,
        "sub_tasks": [
          {
            "requirements": "Leaf-level functionality",
            "weight": 3
          }
        ]
      }
    ]
  }
]

# REQUIREMENTS
- Begin with abstract, high-level components, then drill down to concrete sub-elements.
- Structure the rubric to support deep understanding of the system's architecture and internal logic.
- Be analytical: DO NOT mimic the documentation structure. Instead, distill and reframe it.
- Return ONLY the JSON array — no preamble, no explanation.
""".strip()

_COMBINE_SYSTEM_PROMPT = """\
You are an expert at combining and consolidating evaluation rubrics for code repositories.

Your task is to intelligently combine multiple rubric sets into a single, comprehensive set that:
1. Eliminates redundancy while preserving important distinctions
2. Combines similar requirements into more comprehensive ones
3. Maintains appropriate granularity and specificity
4. Preserves the hierarchical structure with sub_tasks where appropriate

Return ONLY a JSON object with this exact structure:
{
  "rubrics": [
    {
      "requirements": "Top-level concept or component",
      "weight": 3,
      "sub_tasks": [
        {
          "requirements": "More specific concept",
          "weight": 2
        }
      ]
    }
  ]
}

Guidelines:
- Merge similar requirements that overlap significantly (>70% semantic similarity)
- Keep distinct requirements separate even if related
- sub_tasks should be specific, measurable criteria
""".strip()


# ---------------------------------------------------------------------------
# LLM call (re-uses the same helper from wiki_evaluator.py)
# ---------------------------------------------------------------------------

async def _call_llm(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
) -> str:
    """Delegate to wiki_evaluator._call_llm (shares the same module path)."""
    try:
        from wiki_evaluator import _call_llm as _wv_call
        return await _wv_call(messages, model)
    except ImportError:
        pass

    # Inline fallback if wiki_evaluator not importable (should not happen in normal use)
    # Use LiteLLMModel so that github_copilot/ models receive the required headers.
    model_name = (
        model
        or os.environ.get("LITELLM_MODEL_NAME")
        or os.environ.get("CHAT_MODEL")
        or "github_copilot/gpt-4o"
    )
    try:
        if model_name.startswith("copilot_cli/"):
            from app.modules.intelligence.provider.copilot_model import CopilotModel
            from pydantic_ai import Agent as _PAAgent
            bare_name = model_name.split("/", 1)[1]
            _model = CopilotModel(bare_name)
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
            from app.modules.intelligence.provider.litellm_model import LiteLLMModel
            from pydantic_ai.messages import ModelRequest, UserPromptPart, SystemPromptPart
            from pydantic_ai.models import ModelRequestParameters
            from pydantic_ai.settings import ModelSettings
            _model = LiteLLMModel(model_name)
            parts = []
            for m in messages:
                if m.get("role") == "system":
                    parts.append(SystemPromptPart(content=m["content"]))
                elif m.get("role") == "user":
                    parts.append(UserPromptPart(content=m["content"]))
            pydantic_messages = [ModelRequest(parts=parts)]
            mrp = ModelRequestParameters(function_tools=[], output_tools=[], allow_text_output=True)
            response = await _model.request(pydantic_messages, ModelSettings(temperature=0.3), mrp)
            text_parts = [
                part.content for part in response.parts
                if hasattr(part, "content") and isinstance(getattr(part, "content", None), str)
            ]
            return "\n".join(text_parts) if text_parts else ""
    except Exception as exc:
        raise RuntimeError(f"LLM call failed (model={model_name!r}): {exc}") from exc


# ---------------------------------------------------------------------------
# Step 1 — generate hierarchical rubrics from docs_tree
# ---------------------------------------------------------------------------

async def generate_rubrics_from_docs_tree(
    docs_tree: Dict[str, Any],
    model: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Generate a hierarchical rubric list from a docs_tree dict.

    Mirrors ``generate_rubrics.run()`` from CodeWikiBench.

    Returns a list of rubric dicts in the ``sub_tasks`` format::

        [{"requirements": "...", "weight": 3, "sub_tasks": [...]}]

    Falls back to an empty list on failure.
    """
    print("[reference-rubrics] Generating rubrics from docs_tree via LLM...")

    prompt = (
        "Given the docs tree:\n"
        '"""\n'
        + json.dumps(docs_tree, indent=2)[:12_000]
        + '\n"""\n\n'
        "Analyze the documentation above and generate hierarchical rubrics that describe "
        "what the system does and how it works. Return ONLY the JSON array."
    )

    try:
        raw = await _call_llm(
            messages=[
                {"role": "system", "content": _GENERATE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            model=model,
        )
        rubrics = _parse_rubric_list(raw)
        print(f"[reference-rubrics] OK Generated {len(rubrics)} top-level rubrics")
        return rubrics
    except Exception as exc:
        print(f"[reference-rubrics] WARN Rubric generation failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Step 2 — combine multiple rubric sets into one
# ---------------------------------------------------------------------------

async def combine_rubrics(
    rubric_sets: List[List[Dict[str, Any]]],
    model: Optional[str] = None,
    max_retries: int = 3,
) -> List[Dict[str, Any]]:
    """
    Semantically combine N rubric sets into one merged set.

    Mirrors ``semantic_combine_rubrics`` from combine_rubrics.py.
    Falls back to simple dedup-merge on repeated LLM failure.

    Args:
        rubric_sets:  List of rubric lists (output of
                      ``generate_rubrics_from_docs_tree``).
        model:        LLM model name.
        max_retries:  How many times to retry the LLM call.

    Returns:
        A single merged rubric list.
    """
    if not rubric_sets:
        return []
    if len(rubric_sets) == 1:
        return rubric_sets[0]

    print(f"[reference-rubrics] Combining {len(rubric_sets)} rubric sets via LLM...")

    rubrics_payload = {
        f"rubrics_set_{i + 1}": rs for i, rs in enumerate(rubric_sets)
    }
    prompt = (
        f"You have been given {len(rubric_sets)} different sets of rubrics "
        "generated by different AI models for the same repository.\n\n"
        f"{json.dumps(rubrics_payload, indent=2)[:16_000]}\n\n"
        "Combine them into one comprehensive set. "
        "Return ONLY a JSON object with a 'rubrics' key."
    )

    for attempt in range(max_retries):
        try:
            raw = await _call_llm(
                messages=[
                    {"role": "system", "content": _COMBINE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                model=model,
            )
            result = _parse_combined_rubrics(raw)
            if result:
                print(f"[reference-rubrics] OK Combined into {len(result)} top-level rubrics")
                return result
        except Exception as exc:
            print(f"[reference-rubrics] WARN combine attempt {attempt + 1}/{max_retries}: {exc}")

    print("[reference-rubrics] Falling back to simple merge")
    return _fallback_simple_merge(rubric_sets)


# ---------------------------------------------------------------------------
# Step 3 — flatten hierarchical rubrics → categories format
# ---------------------------------------------------------------------------

def flatten_rubrics_to_categories(
    rubrics: List[Dict[str, Any]],
    max_depth: int = 3,
) -> Dict[str, Any]:
    """
    Convert CodeWikiBench hierarchical ``sub_tasks`` rubrics into the flat
    ``{"categories": [...]}`` format consumed by ``WikiEvaluator``.

    Strategy:
    - Top-level items become category names.
    - All leaf ``requirements`` strings (nodes with no ``sub_tasks``) become
      criteria within their ancestor category.
    - Weights are normalised to sum to 1.0 across categories.

    Args:
        rubrics:   List of hierarchical rubric dicts.
        max_depth: Maximum recursion depth when collecting leaf criteria.

    Returns:
        ``{"categories": [{"name": ..., "weight": ..., "criteria": [...]}]}``
    """
    if not rubrics:
        return {"categories": []}

    categories: List[Dict[str, Any]] = []

    for top in rubrics:
        cat_name = top.get("requirements", "General")[:80]
        raw_weight = top.get("weight", 2)  # 1/2/3 scale
        subtasks = top.get("sub_tasks", top.get("children", []))

        criteria = _collect_leaf_criteria(subtasks, depth=0, max_depth=max_depth)
        # If no subtasks, the top-level requirement itself is the criterion
        if not criteria:
            criteria = [cat_name]

        categories.append({
            "name": cat_name,
            "weight": float(raw_weight),
            "criteria": criteria,
            "source": "reference_docs",
        })

    # Normalise weights to sum to 1.0
    total_w = sum(c["weight"] for c in categories) or 1.0
    for cat in categories:
        cat["weight"] = round(cat["weight"] / total_w, 4)

    return {"categories": categories, "source": "reference_docs"}


def _collect_leaf_criteria(
    items: List[Dict[str, Any]],
    depth: int,
    max_depth: int,
) -> List[str]:
    """Recursively collect leaf ``requirements`` strings."""
    criteria: List[str] = []
    for item in items:
        req = item.get("requirements", "")
        subtasks = item.get("sub_tasks", item.get("children", []))
        if not subtasks or depth >= max_depth:
            if req:
                criteria.append(req)
        else:
            criteria.extend(
                _collect_leaf_criteria(subtasks, depth + 1, max_depth)
            )
    return criteria


# ---------------------------------------------------------------------------
# High-level helper — single-model workflow
# ---------------------------------------------------------------------------

async def generate_reference_rubrics(
    docs_tree: Dict[str, Any],
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    End-to-end helper: docs_tree → flat categories rubrics (single model).

    Steps:
      1. Generate hierarchical rubrics from docs_tree via LLM.
      2. Flatten to ``{"categories": [...]}`` format.

    Returns the flat rubrics dict ready for ``WikiEvaluator``.
    Falls back to empty categories dict on complete failure.
    """
    hierarchical = await generate_rubrics_from_docs_tree(docs_tree, model)
    if not hierarchical:
        print("[reference-rubrics] No hierarchical rubrics generated — returning empty")
        return {"categories": [], "source": "reference_docs"}

    flat = flatten_rubrics_to_categories(hierarchical)
    n_cats = len(flat.get("categories", []))
    n_crit = sum(len(c.get("criteria", [])) for c in flat.get("categories", []))
    print(f"[reference-rubrics] Flattened: {n_cats} categories, {n_crit} criteria")
    return flat


async def generate_reference_rubrics_multi_model(
    docs_tree: Dict[str, Any],
    models: List[str],
) -> Dict[str, Any]:
    """
    Multi-model workflow: generate rubrics with each model, then combine.

    Steps:
      1. Generate one hierarchical rubric list per model.
      2. Semantically combine all sets via LLM.
      3. Flatten to flat categories format.

    Returns the flat rubrics dict.
    """
    import asyncio

    print(f"[reference-rubrics] Generating rubrics with {len(models)} model(s): {models}")
    tasks = [generate_rubrics_from_docs_tree(docs_tree, m) for m in models]
    all_sets: List[List[Dict]] = await asyncio.gather(*tasks)

    # Filter out empty sets
    non_empty = [s for s in all_sets if s]
    if not non_empty:
        return {"categories": [], "source": "reference_docs"}

    # Use the primary model for combining
    combined = await combine_rubrics(non_empty, model=models[0])
    flat = flatten_rubrics_to_categories(combined)
    n_cats = len(flat.get("categories", []))
    n_crit = sum(len(c.get("criteria", [])) for c in flat.get("categories", []))
    print(f"[reference-rubrics] Multi-model combined: {n_cats} categories, {n_crit} criteria")
    return flat


# ---------------------------------------------------------------------------
# Rubric statistics (ported from combine_rubrics.calculate_rubrics_statistics)
# ---------------------------------------------------------------------------

def calculate_rubrics_statistics(rubrics: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate statistics about a hierarchical rubric list."""
    from collections import Counter

    total = 0
    weights: List[int] = []
    max_depth = 0

    def _count(items: List[Dict], level: int) -> None:
        nonlocal total, max_depth
        for item in items:
            total += 1
            weights.append(item.get("weight", 1))
            max_depth = max(max_depth, level)
            children = item.get("sub_tasks", item.get("children", []))
            if children:
                _count(children, level + 1)

    _count(rubrics, 0)

    return {
        "total_items": total,
        "top_level_items": len(rubrics),
        "max_depth": max_depth,
        "weight_distribution": dict(Counter(weights)),
        "average_weight": sum(weights) / len(weights) if weights else 0,
    }


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_rubric_list(raw: str) -> List[Dict[str, Any]]:
    """Extract a JSON array from an LLM response."""
    start = raw.find("[")
    end = raw.rfind("]") + 1
    if start == -1 or end <= start:
        raise ValueError("No JSON array found in LLM response")
    return json.loads(raw[start:end])


def _parse_combined_rubrics(raw: str) -> List[Dict[str, Any]]:
    """Extract the 'rubrics' list from a combined-rubrics LLM response."""
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end <= start:
        raise ValueError("No JSON object found in LLM response")
    obj = json.loads(raw[start:end])
    if "rubrics" in obj and isinstance(obj["rubrics"], list):
        return obj["rubrics"]
    if isinstance(obj, list):
        return obj
    raise ValueError(f"Unexpected combined rubrics format: {list(obj.keys())}")


def _fallback_simple_merge(rubric_sets: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Dedup-merge multiple rubric lists by requirements text."""
    seen: set = set()
    merged: List[Dict[str, Any]] = []
    for rubric_set in rubric_sets:
        for item in rubric_set:
            key = item.get("requirements", "").lower().strip()
            if key and key not in seen:
                merged.append(item)
                seen.add(key)
    return merged
