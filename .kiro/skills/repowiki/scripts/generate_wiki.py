#!/usr/bin/env python3
"""
Repowiki Wiki Generator Script

Runs both phases of wiki generation using the potpie knowledge graph:
  Phase 1 — Query Neo4j for FILE/CLASS/FUNCTION nodes via graph.py → extraction dict
  Phase 2 — LLM agent writes Markdown wiki pages in batches + README index

Must be invoked with the potpie venv Python:
  .venv/bin/python .kiro/skills/repowiki/scripts/generate_wiki.py \\
    --project-id <uuid> --repo-path /abs/path/to/repo --output-dir /abs/path/to/.repowiki

Copyright 2025 Intel Corporation
Licensed under the Apache License, Version 2.0
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: repo root on sys.path, .env loaded — same as evaluate_qna.py
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).parent.resolve()
_REPO_ROOT = _SCRIPT_DIR.parents[3]  # potpie/.kiro/skills/repowiki/scripts/ → potpie/

for _p in [str(_REPO_ROOT), str(_SCRIPT_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

_ENV_FILE = _REPO_ROOT / ".env"
if _ENV_FILE.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_FILE, override=False)
    except ImportError:
        pass

from graph import graph_extract_async  # noqa: E402  (after sys.path bootstrap)


# ---------------------------------------------------------------------------
# Phase 2: LLM agent writes wiki pages in batches
# ---------------------------------------------------------------------------
_PAGE_STRUCTURE = """
For each module write one Markdown wiki page with this structure:

  # <module name>
  <description paragraph — write in your own words, do not just repeat the docstring>
  **Source:** `<path>`

  ## <ClassName>  (omit section if no classes)
  <class description>
  ### <methodName>
  <method description>
  | Name | Type | Description | Default |
  | ---- | ---- | ----------- | ------- |

  ## Functions  (omit section if no functions)
  ### <functionName>
  <description>

  ## Dependencies  (omit section if no imports)
  - `<import>`

Rules:
- Every heading must be followed by at least one sentence of prose.
- Omit any section whose data is absent — never emit an empty heading.
- Annotate async functions: ### myFunc `async`
- Include parameter table only when the function has parameters.
"""

BATCH_SIZE = 5


async def _generate(extraction: dict, output_dir: str, verbose: bool) -> int:
    from pydantic_ai import Agent
    from app.modules.intelligence.provider.litellm_model import LiteLLMModel

    model_name = os.environ.get("CHAT_MODEL", "github_copilot/gpt-4o")
    model = LiteLLMModel(model_name)

    agent = Agent(
        model=model,
        instructions=(
            "You are a technical documentation expert. "
            "Write clear, human-readable Markdown wiki pages from structured module data. "
            + _PAGE_STRUCTURE
        ),
    )

    @agent.tool_plain
    def write_file(path: str, content: str) -> str:
        """Write content to a file, creating parent directories as needed."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        print(f"  ✅ Written: {path}")
        return f"Written: {path}"

    modules = extraction.get("modules", [])
    batches = [modules[i:i + BATCH_SIZE] for i in range(0, len(modules), BATCH_SIZE)]
    total_written = 0

    print(f"\n[INFO] Generating wiki ({len(modules)} modules, {len(batches)} batches)...")

    def _trim(m: dict) -> dict:
        trimmed = {k: v for k, v in m.items() if k != "types"}
        if len(trimmed.get("imports", [])) > 20:
            trimmed["imports"] = trimmed["imports"][:20] + ["..."]
        return trimmed

    for idx, batch in enumerate(batches):
        paths = ", ".join(m["path"] for m in batch)
        if verbose:
            print(f"  Batch {idx+1}/{len(batches)}: {paths}")

        batch_json = json.dumps([_trim(m) for m in batch], indent=2)
        prompt = (
            f"Write Markdown wiki pages for the following source modules.\n"
            f"Output directory: '{output_dir}'\n\n"
            f"For each module:\n"
            f"1. Write one page following the structure in your instructions.\n"
            f"2. Output path: '{output_dir}/<module.path>' with extension replaced by .md\n"
            f"   e.g. py/dml/ast.py → {output_dir}/py/dml/ast.md\n"
            f"3. Call write_file(path, content) for each page.\n\n"
            f"Module data (batch {idx+1}/{len(batches)}):\n"
            f"```json\n{batch_json}\n```"
        )

        try:
            async with agent.iter(prompt) as run:
                async for node in run:
                    if verbose:
                        print(f"    Node: {type(node).__name__}")
            total_written += len(batch)
            print(f"[INFO] Batch {idx+1}/{len(batches)} done ({total_written}/{len(modules)})")
        except Exception as e:
            print(f"[FAIL] Batch {idx+1} failed: {e}", file=sys.stderr)
            raise

    return total_written


def _write_index(modules: list, output_dir: str) -> None:
    by_dir: dict = defaultdict(list)
    for m in modules:
        by_dir[str(Path(m["path"]).parent)].append(m["path"])

    lines = ["# Wiki Index\n"]
    for d in sorted(by_dir):
        lines.append(f"\n## {d}\n")
        for p in sorted(by_dir[d]):
            stem = Path(p).stem
            md_path = str(Path(p).with_suffix(".md"))
            lines.append(f"- [{stem}]({md_path})")

    readme = Path(output_dir) / "README.md"
    readme.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  ✅ Written: {readme}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def _main(project_id: str, repo_path: str, output_dir: str, verbose: bool) -> None:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    extraction_json = Path(output_dir) / "extraction.json"

    print("[INFO] Phase 1: Extracting source structure from knowledge graph...")
    extraction = await graph_extract_async(project_id, repo_path)
    module_count = len(extraction["modules"])
    skipped_count = len(extraction["skipped"])
    extraction_json.write_text(json.dumps(extraction, indent=2), encoding="utf-8")
    print(f"[PASS] Extracted {module_count} module(s). Skipped {skipped_count}.")

    print("\n[INFO] Phase 2: Generating wiki pages...")
    total = await _generate(extraction, output_dir, verbose)

    print("\n[INFO] Writing index...")
    _write_index(extraction["modules"], output_dir)

    print(f"\n[PASS] Wiki generation complete: {total} pages written to '{output_dir}'")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="generate_wiki",
        description="Generate wiki documentation from the potpie knowledge graph.",
    )
    parser.add_argument("--project_id", "--project-id", required=True, help="Potpie project UUID")
    parser.add_argument("--repo_path", "--repo-path", required=True, help="Absolute path to the repository root")
    parser.add_argument("--output_dir", "--output-dir", required=True, help="Directory to write wiki pages into")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show debug output")
    args = parser.parse_args()

    asyncio.run(_main(args.project_id, args.repo_path, args.output_dir, args.verbose))


if __name__ == "__main__":
    main()
