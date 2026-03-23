#!/usr/bin/env python3
"""
Potpie Wiki Evaluator Skill -- entry point

Evaluates wiki/documentation quality using the full 6-step pipeline:

  Step 1: Parse wiki markdown files -> docs_tree
  Step 2: Generate AI rubrics from docs_tree (LLM)
  Step 3: Query potpie code graph for ground-truth rubrics (GraphRubricGenerator)
  Step 4: Merge AI + graph rubrics -> final rubrics
  Step 5: Evaluate wiki content per-criterion with chunking (direct LLM calls)
  Step 6: Calculate weighted scores
  Step 7: Write JSON + Markdown report

Key differentiator vs the standalone wiki-evaluator skill:
  - Step 3 uses the potpie code knowledge graph (GraphRubricGenerator) instead of
    raw file scanning -- richer and more accurate ground-truth rubric generation.
  - No pydantic_evals dependency -- uses direct LLM calls per criterion.

Usage:
  source .env && .venv/bin/python .kiro/skills/wiki-evaluator/scripts/evaluate_wiki.py \\
    --project-id <project_id> \\
    --wiki-dir /path/to/wiki \\
    --output evaluation/wiki/score.md

Or via CLI:
  python potpie_cli.py evaluate-wiki --project <project_id> --wiki-dir .codewiki

Copyright 2025 Intel Corporation
Licensed under the Apache License, Version 2.0
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Path setup -- add repo root + skill modules to sys.path
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).parent.resolve()
_MODULES_PATH = _SCRIPT_DIR / "wiki-evaluator-modules"
_REPO_ROOT = _SCRIPT_DIR.parents[3]  # <repo>/.kiro/skills/wiki-evaluator/scripts/

for _p in [str(_MODULES_PATH), str(_SCRIPT_DIR), str(_REPO_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Load .env so POSTGRES_SERVER, REDIS_URL, CHAT_MODEL etc. are available
_ENV_FILE = _REPO_ROOT / ".env"
if _ENV_FILE.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_FILE, override=False)
    except ImportError:
        pass

# ---------------------------------------------------------------------------
# Module-level imports for skill modules (allows patching in tests)
# ---------------------------------------------------------------------------

# Skill module imports — always importable (no live services needed)
from deepwiki_docs_parser import parse_docs_directory  # noqa: E402
from reference_rubrics_generator import generate_reference_rubrics  # noqa: E402
from graph_rubric_generator import GraphRubricGenerator  # noqa: E402

# potpie runtime — may not be importable in test environments; fall back to None
try:
    from potpie.runtime import PotpieRuntime  # noqa: E402
except ImportError:
    PotpieRuntime = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Wiki directory helpers
# ---------------------------------------------------------------------------

_WIKI_DIR_CANDIDATES = [
    ".repowiki/en/content",
    ".codewiki",
    ".deepwiki-open",
    ".deepwiki",
    "wiki",
    "docs",
]


def resolve_wiki_dir(wiki_dir_arg: Optional[str], base_dir: Optional[Path] = None) -> Optional[Path]:
    """
    Resolve --wiki-dir to an absolute Path, or auto-detect common names.
    Returns None if nothing is found.
    """
    if wiki_dir_arg:
        candidate = Path(wiki_dir_arg)
        if not candidate.is_absolute():
            candidate = (base_dir or Path.cwd()) / candidate
        resolved = candidate.resolve()
        if resolved.exists():
            return resolved
        print(f"[WARN] Wiki directory not found: {resolved}")
        return None

    cwd = base_dir or Path.cwd()
    for name in _WIKI_DIR_CANDIDATES:
        cand = (cwd / name).resolve()
        if cand.exists():
            print(f"[INFO] Auto-detected wiki directory: {cand}")
            return cand

    return None


def read_wiki_directory(wiki_dir: Path) -> str:
    """
    Read all markdown files under wiki_dir and return a single concatenated string.
    Each file is prefixed with a '### File: <rel>' header for context.
    """
    if not wiki_dir or not wiki_dir.exists():
        return ""

    md_files = sorted(wiki_dir.rglob("*.md"))
    if not md_files:
        print(f"[WARN] No .md files found under {wiki_dir}")
        return ""

    sections: List[str] = []
    for md_file in md_files:
        try:
            rel = md_file.relative_to(wiki_dir)
            content = md_file.read_text(encoding="utf-8", errors="replace")
            sections.append(f"\n\n---\n### File: {rel}\n\n{content}")
        except Exception as exc:
            print(f"[WARN] Could not read {md_file}: {exc}")

    print(f"[PASS] Read {len(md_files)} markdown files from {wiki_dir}")
    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Project ID resolution
# ---------------------------------------------------------------------------

async def resolve_project_id(repo_name: str, user_id: str) -> str:
    from potpie.runtime import PotpieRuntime
    runtime = PotpieRuntime.from_env()
    await runtime.initialize()
    try:
        projects = await runtime.projects.list(user_id=user_id)
        matches = [p for p in projects if p.repo_name == repo_name]
        if not matches:
            print(f"[FAIL] No project found with repo_name='{repo_name}'")
            sys.exit(1)
        return matches[0].id
    finally:
        await runtime.close()


# ---------------------------------------------------------------------------
# Full pipeline (async)
# ---------------------------------------------------------------------------

async def run_pipeline(
    project_id: str,
    wiki_dir: Optional[Path],
    model: Optional[str],
    ai_weight: float,
    graph_weight: float,
    output: str,
    reference_docs_dir: Optional[Path] = None,
    reference_docs_weight: float = 0.0,
    context_window: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Run the complete wiki evaluation pipeline in one of two modes:

    **Mode A — Reference-docs mode** (``reference_docs_dir`` is provided):
      1. Parse the reference-docs directory into a docs_tree.
      2. Generate rubrics from the docs_tree via LLM (reference rubrics).
      3. Use the reference rubrics directly as the final evaluation rubrics.
         Graph and AI rubric generation are skipped.

    **Mode B — AI + Graph mode** (``reference_docs_dir`` is None):
      1. Parse wiki markdown → docs_tree (Step 1).
      2. Generate AI rubrics from docs_tree via LLM (Step 2).
      3. Generate graph rubrics via GraphRubricGenerator + PotpieRuntime (Step 3a).
      4. Merge AI rubrics + graph rubrics → final rubrics (Step 4).

    In both modes Steps 5-7 are identical:
      5. Evaluate wiki content per-criterion with LLM chunking.
      6. Calculate weighted scores.
      7. Write JSON + Markdown report.
    """
    from wiki_evaluator import WikiEvaluator, merge_rubrics

    # -- Read wiki content ----------------------------------------------------
    wiki_content = read_wiki_directory(wiki_dir) if wiki_dir else ""
    if not wiki_content:
        print("[WARN] No wiki content found -- coverage scores will be 0.")

    # =========================================================================
    # MODE A: Reference-docs rubrics — use them directly, skip AI + graph
    # =========================================================================
    if reference_docs_dir and reference_docs_dir.exists():
        print(f"\n[INFO] Mode A: Generating rubrics from reference docs at {reference_docs_dir}...")
        reference_rubrics: Dict[str, Any] = {"categories": []}
        _reference_rubrics_ok = False
        try:
            _, docs_tree = parse_docs_directory(
                path=str(reference_docs_dir),
                project_name=reference_docs_dir.name,
            )
            reference_rubrics = await generate_reference_rubrics(docs_tree, model=model)
            n_cat = len(reference_rubrics.get("categories", []))
            n_crit = sum(len(c.get("criteria", [])) for c in reference_rubrics.get("categories", []))
            print(f"[INFO] Reference rubrics: {n_cat} categories, {n_crit} criteria")
            _reference_rubrics_ok = n_cat > 0
        except Exception as exc:
            print(f"[WARN] Reference rubric generation failed: {exc}")

        if not _reference_rubrics_ok:
            print("[WARN] Reference rubrics are empty (LLM failure?) — falling back to Mode B")
            results = await _run_mode_b(
                project_id, wiki_dir, wiki_content, model, ai_weight, graph_weight, context_window
            )
            results["rubrics_sources"] = {
                "reference_docs": False,
                "graph": bool(results.pop("_graph_had_categories", False)),
                "ai": bool(wiki_dir and wiki_dir.exists()),
            }
            results["evaluation_mode"] = "ai_graph"
        else:
            evaluator = WikiEvaluator(model=model, context_window=context_window)
            results = await evaluator.evaluate_async(
                wiki_content=wiki_content,
                graph_rubrics={"categories": []},   # not used in Mode A
                wiki_dir=None,                       # skip AI rubric steps
                ai_weight=0.0,
                graph_weight=0.0,                    # not used in Mode A (final_rubrics used directly)
                final_rubrics=reference_rubrics,     # use directly
            )
            results["rubrics_sources"] = {
                "reference_docs": True,
                "graph": False,
                "ai": False,
            }
            results["evaluation_mode"] = "reference_docs"

    elif reference_docs_dir:
        print(f"[WARN] --reference-docs-dir not found: {reference_docs_dir} — falling back to Mode B")
        reference_rubrics = {"categories": []}
        results = await _run_mode_b(
            project_id, wiki_dir, wiki_content, model, ai_weight, graph_weight, context_window
        )
        results["rubrics_sources"] = {
            "reference_docs": False,
            "graph": bool(results.pop("_graph_had_categories", False)),
            "ai": bool(wiki_dir and wiki_dir.exists()),
        }
        results["evaluation_mode"] = "ai_graph"

    # =========================================================================
    # MODE B: AI rubrics + graph rubrics — merge and evaluate
    # =========================================================================
    else:
        print("\n[INFO] Mode B: Using AI rubrics + graph rubrics (no reference-docs-dir).")
        results = await _run_mode_b(
            project_id, wiki_dir, wiki_content, model, ai_weight, graph_weight, context_window
        )
        results["rubrics_sources"] = {
            "reference_docs": False,
            "graph": bool(results.pop("_graph_had_categories", False)),
            "ai": bool(wiki_dir and wiki_dir.exists()),
        }
        results["evaluation_mode"] = "ai_graph"

    # -- Step 7: Write report -------------------------------------------------
    model_name = (
        model
        or os.environ.get("LITELLM_MODEL_NAME")
        or os.environ.get("CHAT_MODEL", "default")
    )
    generate_report(results, project_id, str(wiki_dir) if wiki_dir else None, model_name, output)

    return results


async def _run_mode_b(
    project_id: str,
    wiki_dir: Optional[Path],
    wiki_content: str,
    model: Optional[str],
    ai_weight: float,
    graph_weight: float,
    context_window: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Mode B: Generate graph rubrics via PotpieRuntime, then run WikiEvaluator
    which handles AI rubric generation (Steps 1-2) and merging (Step 4).

    Returns the evaluation result dict with an extra ``_graph_had_categories``
    key so the caller can populate ``rubrics_sources``.
    """
    from wiki_evaluator import WikiEvaluator

    # -- Step 3a: Generate graph rubrics via PotpieRuntime --------------------
    print(f"\n[INFO] Step 3a: Generating graph rubrics (project={project_id})...")
    graph_rubrics: Dict[str, Any] = {"categories": []}

    try:
        if PotpieRuntime is None:
            raise ImportError("potpie.runtime not available")
        runtime = PotpieRuntime.from_env()
        await runtime.initialize()
        try:
            gen = GraphRubricGenerator(runtime, project_id)
            graph_rubrics = await gen.generate(model=model)
            n_cat = len(graph_rubrics.get("categories", []))
            n_crit = sum(len(c.get("criteria", [])) for c in graph_rubrics.get("categories", []))
            print(f"[INFO] Graph rubrics: {n_cat} categories, {n_crit} criteria")
        finally:
            await runtime.close()
    except Exception as exc:
        print(f"[WARN] Graph rubric generation failed: {exc}")
        print("[WARN] Proceeding with AI rubrics only")

    # -- Steps 1-2 and 4-6: WikiEvaluator handles AI rubrics + merge ----------
    evaluator = WikiEvaluator(model=model, context_window=context_window)
    results = await evaluator.evaluate_async(
        wiki_content=wiki_content,
        graph_rubrics=graph_rubrics,
        wiki_dir=wiki_dir,
        ai_weight=ai_weight,
        graph_weight=graph_weight,
    )

    results["_graph_had_categories"] = bool(graph_rubrics.get("categories"))
    return results


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(
    wiki_results: Dict[str, Any],
    project_id: str,
    wiki_dir: Optional[str],
    model_name: str,
    output: str,
) -> None:
    """Write JSON + Markdown report."""
    overall = wiki_results.get("overall_score", 0.0)
    met = wiki_results.get("met_criteria", wiki_results.get("met_requirements", 0))
    total = wiki_results.get("total_criteria", wiki_results.get("total_requirements", 0))

    # JSON report
    json_out = Path(output) if output.endswith(".json") else Path(output).with_suffix(".json")
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(wiki_results, indent=2), encoding="utf-8")
    print(f"[PASS] JSON report saved to: {json_out}")

    # Markdown report
    md_out = Path(output) if output.endswith(".md") else json_out.with_suffix(".md")
    lines = [
        "# Wiki Evaluation Report",
        "",
        f"**Project ID**: {project_id}",
        f"**Wiki directory**: {wiki_dir or '(auto-detected)'}",
        f"**Model**: {model_name}",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Overall Score",
        "",
        f"**{overall:.1%}**  ({met}/{total} criteria met)",
        "",
    ]

    # Category breakdown
    for cat, data in wiki_results.get("category_scores", {}).items():
        if isinstance(data, dict):
            score = data.get("score", 0)
            cat_met = data.get("met", 0)
            cat_total = data.get("total", 0)
        else:
            score = float(data)
            cat_met = "-"
            cat_total = "-"
        status = "PASS" if score >= 0.5 else "FAIL"
        lines += [f"### {cat}", "", f"**Score**: {score:.1%}  [{status}]  ({cat_met}/{cat_total})", ""]

    # Rubrics used
    rubrics_used = wiki_results.get("rubrics_used", {})
    rubrics_sources = wiki_results.get("rubrics_sources", {})
    if rubrics_used or rubrics_sources:
        lines += ["## Rubrics Used", ""]
        if rubrics_sources.get("reference_docs"):
            lines.append("- ✅ Reference-docs rubrics (CodeWikiBench pipeline)")
        if rubrics_sources.get("graph"):
            lines.append("- ✅ Graph-derived rubrics (potpie code graph)")
        if rubrics_sources.get("ai"):
            lines.append("- ✅ AI-generated rubrics (from wiki docs_tree)")
        if rubrics_used:
            lines += [
                "",
                f"- AI-generated categories: {rubrics_used.get('ai_categories', 0)}",
                f"- Graph-derived categories: {rubrics_used.get('graph_categories', 0)}",
                f"- Merged total categories: {rubrics_used.get('merged_categories', 0)}",
            ]
        lines.append("")

    report = "\n".join(lines) + "\n\n## Per-Criterion Results\n\n"
    for item in wiki_results.get("detailed_criteria", []):
        cov_score = item.get("overall_score", item.get("score", 0))
        status = "PASS" if cov_score >= 0.5 else "FAIL"
        report += f"### [{status}] {item.get('criterion', item.get('criteria', ''))[:80]}\n\n"
        report += f"- **Category**: {item.get('category', '')}\n"
        report += f"- **Score**: {int(cov_score)}\n"
        if item.get("reasoning"):
            report += f"- **Reasoning**: {item['reasoning']}\n"
        if item.get("evidence") and item["evidence"] not in ("", "none", "None"):
            report += f"- **Evidence**: {item['evidence'][:200]}\n"
        report += "\n"

    md_out.write_text(report, encoding="utf-8")
    print(f"[PASS] Markdown report saved to: {md_out}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Potpie Wiki Evaluator Skill")
    parser.add_argument("--project-id", default=None, help="Potpie project ID (or use --repo)")
    parser.add_argument("--repo", default=None, help="Repo name to auto-resolve project ID")
    parser.add_argument("--wiki-dir", default=None,
                        help="Path to wiki directory (abs, rel, or bare name; auto-detects if omitted)")
    parser.add_argument("--user-id", default=os.environ.get("POTPIE_USER_ID", "defaultuser"))
    parser.add_argument("--model", default=None, help="LLM model for evaluation and rubric generation")
    parser.add_argument("--output", default="wiki_eval_score.md",
                        help="Output report path (.md or .json; both formats always written)")
    parser.add_argument("--reference-docs-dir", default=None,
                        help=(
                            "Path to a directory of reference/deepwiki markdown docs "
                            "(e.g. downloaded via `deepwiki-export`). When provided, "
                            "the CodeWikiBench pipeline runs to parse the docs and "
                            "generate rubrics from them, which are merged with the "
                            "graph rubrics and AI rubrics."
                        ))
    parser.add_argument("--reference-docs-weight", type=float, default=1.0,
                        help="Weight for reference-docs rubrics when --reference-docs-dir is used (default 0.3)")
    parser.add_argument("--ai-weight", type=float, default=0.4,
                        help="Weight for AI-generated rubrics in merge (default 0.4)")
    parser.add_argument("--graph-weight", type=float, default=0.6,
                        help="Weight for graph-derived rubrics in merge (default 0.6)")
    parser.add_argument("--context-window", type=int, default=None,
                        help=(
                            "LLM context window size in tokens (default: 120000). "
                            "Controls the wiki-content chunk size fed to each LLM call "
                            "(chunk_size ≈ context_window * 1.0 chars, leaving 20%% headroom) "
                            "and the concurrent batch size. "
                            "Use 128000 for GPT-4o / Claude Sonnet, 256000 for Gemini 1.5 Pro. "
                            "Can also be set via the WIKI_CONTEXT_WINDOW environment variable."
                        ))
    args = parser.parse_args()

    if not args.project_id and not args.repo:
        print("[FAIL] Provide either --project-id or --repo")
        sys.exit(1)

    if not args.project_id:
        print(f"[INFO] Resolving project ID for repo: {args.repo}")
        args.project_id = asyncio.run(resolve_project_id(args.repo, args.user_id))
        print(f"[INFO] Resolved project ID: {args.project_id}")

    # Resolve wiki directory
    wiki_dir = resolve_wiki_dir(args.wiki_dir)

    # Resolve optional reference-docs directory
    reference_docs_dir: Optional[Path] = None
    if args.reference_docs_dir:
        p = Path(args.reference_docs_dir)
        if not p.is_absolute():
            p = Path.cwd() / p
        reference_docs_dir = p.resolve()
        if not reference_docs_dir.exists():
            print(f"[WARN] --reference-docs-dir not found: {reference_docs_dir}")
            reference_docs_dir = None

    # Run pipeline
    results = asyncio.run(
        run_pipeline(
            project_id=args.project_id,
            wiki_dir=wiki_dir,
            model=args.model,
            ai_weight=args.ai_weight,
            graph_weight=args.graph_weight,
            output=args.output,
            reference_docs_dir=reference_docs_dir,
            reference_docs_weight=args.reference_docs_weight,
            context_window=args.context_window,
        )
    )

    # Summary
    overall = results.get("overall_score", 0.0)
    met = results.get("met_criteria", results.get("met_requirements", 0))
    total = results.get("total_criteria", results.get("total_requirements", 0))

    print(f"\n{'='*60}")
    print("WIKI EVALUATION SUMMARY")
    print(f"{'='*60}")
    print(f"  Overall Score : {overall:.1%}")
    print(f"  Criteria Met  : {met}/{total}")
    for cat, data in results.get("category_scores", {}).items():
        if isinstance(data, dict):
            score = data.get("score", 0)
        else:
            score = float(data)
        status = "PASS" if score >= 0.5 else "FAIL"
        print(f"  [{status}] {cat}: {score:.1%}")
    skipped = results.get("skipped_categories", {})
    if skipped:
        for cat, reason in skipped.items():
            print(f"  [SKIP] {cat}: {reason}")
    print(f"{'='*60}\n")

    sys.exit(0 if overall >= 0.5 else 1)


if __name__ == "__main__":
    main()
