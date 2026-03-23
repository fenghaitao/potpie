---
name: wiki-evaluator
description: Evaluates wiki/documentation quality using two mutually exclusive modes — reference-docs rubrics (CodeWikiBench pipeline) or AI + graph rubrics (potpie code-graph). No golden answers required.
homepage: https://github.com/intel-sandbox/potpie
requires:
  - potpie venv Python (`.venv/bin/python`)
---

# Wiki Evaluator Skill

Evaluates the quality of wiki/documentation against ground-truth rubrics generated from
either **reference documentation** (Mode A) or the **potpie code knowledge graph + LLM**
(Mode B). No golden reference answers or `deepeval` dependency needed.

## Evaluation Modes

The pipeline runs in exactly one of two mutually exclusive modes, chosen automatically
based on whether `--reference-docs-dir` is supplied.

### Mode A — Reference-Docs Rubrics (`--reference-docs-dir` provided)

Implements the **CodeWikiBench "official docs rubric" pipeline**:

1. Parse the reference-docs directory (e.g. DeepWiki markdown exports) → `docs_tree`.
2. Generate LLM rubrics from the `docs_tree` → **reference rubrics**.
3. Evaluate the target wiki directly against those reference rubrics.

Steps 1–2 of the AI/graph flow are **skipped**; rubrics come entirely from the
reference docs. Use this mode when you have authoritative reference documentation for
the project (e.g. a DeepWiki export or official API docs).

```
Reference docs dir
  └── parse_docs_directory()       → docs_tree
  └── generate_reference_rubrics() → reference rubrics (LLM)
        └── WikiEvaluator.evaluate_async(final_rubrics=reference_rubrics)
              └── Steps 5-7: evaluate wiki, score, write report
```

### Mode B — AI + Graph Rubrics (no `--reference-docs-dir`)

Uses the **potpie code knowledge graph** as ground truth, supplemented by AI rubrics
generated from the wiki itself:

1. Parse wiki markdown → `docs_tree`.
2. Generate AI rubrics from `docs_tree` via LLM → **ai_rubrics**.
3. Generate graph rubrics via `GraphRubricGenerator` + `PotpieRuntime` → **graph_rubrics**.
4. Merge `ai_rubrics` + `graph_rubrics` (weighted) → **merged_rubrics**.
5. Evaluate the wiki against `merged_rubrics`.
6. Calculate weighted scores.
7. Write JSON + Markdown report.

```
PotpieRuntime
  └── GraphRubricGenerator      → graph_rubrics (ground-truth from code graph)
WikiEvaluator
  └── Step 1: parse wiki        → docs_tree
  └── Step 2: LLM rubrics       → ai_rubrics
  └── Step 4: merge             → merged_rubrics
  └── Steps 5-7: evaluate, score, report
```

## Quick Start

**Mode A** (reference docs available):
```bash
cd potpie
source .env && .venv/bin/python .kiro/skills/wiki-evaluator/scripts/evaluate_wiki.py \
  --project-id <project_id> \
  --wiki-dir /path/to/wiki \
  --reference-docs-dir /path/to/reference/docs \
  --output evaluation/wiki/score.md
```

**Mode B** (no reference docs):
```bash
cd potpie
source .env && .venv/bin/python .kiro/skills/wiki-evaluator/scripts/evaluate_wiki.py \
  --project-id <project_id> \
  --wiki-dir /path/to/wiki \
  --output evaluation/wiki/score.md
```

Or via the CLI:
```bash
source .env && python potpie_cli.py evaluate-wiki \
  --project <project_id> \
  --wiki-dir .codewiki \
  --output evaluation/wiki/score.md
```

## Prerequisites

- potpie `.venv` with all dependencies installed
- `.env` file with `CHAT_MODEL` set (e.g. `github_copilot/gpt-4o`)
- A parsed potpie project (visible in the project list) — required for Mode B
- A wiki/documentation directory with markdown files
- *(Mode A only)* A reference-docs directory (e.g. exported via `deepwiki-export`)

## Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `--project-id` | yes* | — | Potpie project ID (or use `--repo`) |
| `--repo` | yes* | — | Repo name to auto-resolve project ID |
| `--wiki-dir` | no | auto-detect | Path to wiki directory (abs, rel, or bare name) |
| `--reference-docs-dir` | no | — | **Mode A**: path to reference/deepwiki markdown docs. When provided, rubrics are generated from these docs and AI+graph generation is skipped. |
| `--reference-docs-weight` | no | `1.0` | Weight for reference-docs rubrics (Mode A only) |
| `--ai-weight` | no | `0.4` | Weight for AI-generated rubrics in merge (Mode B only) |
| `--graph-weight` | no | `0.6` | Weight for graph-derived rubrics in merge (Mode B only; ignored in Mode A) |
| `--context-window` | no | `120000` | LLM context window in tokens. Controls wiki-content chunk size per LLM call (≈ `tokens × 1.0` chars, 20% reserved for prompt+response) and concurrent batch size. Use `128000` for GPT-4o/Claude Sonnet, `256000` for Gemini 1.5 Pro. Also settable via `WIKI_CONTEXT_WINDOW` env var. |
| `--user-id` | no | `defaultuser` | User ID owning the project |
| `--model` | no | `LITELLM_MODEL_NAME` or `CHAT_MODEL` env | LLM for scoring and rubric generation |
| `--output` | no | `wiki_eval_score.md` | Output report path (`.md` and `.json` both written) |

\* One of `--project-id` or `--repo` is required.

## Output

Both modes produce identical output formats:

- **JSON report** (`<output>.json`): machine-readable full results including
  per-criterion scores, reasoning, evidence, and metadata.
- **Markdown report** (`<output>.md`): human-readable summary with overall score,
  per-category breakdown, and rubric sources used.

The report includes a `rubrics_sources` section indicating which sources contributed:

```json
{
  "rubrics_sources": {
    "reference_docs": true,
    "graph": false,
    "ai": false
  },
  "evaluation_mode": "reference_docs"
}
```

**Passing threshold:** ≥ 50% overall score.

## Scoring Thresholds

| Score | Status |
|---|---|
| ≥ 70% | Good |
| ≥ 50% | Pass |
| < 50% | Fail |

## Modules

| Module | Description |
|---|---|
| `evaluate_wiki.py` | Entry point; mode selection, report generation |
| `wiki_evaluator.py` | `WikiEvaluator` class; Steps 1-2-4-5-6 |
| `reference_rubrics_generator.py` | `generate_reference_rubrics()` — CodeWikiBench LLM rubric pipeline (Mode A) |
| `deepwiki_docs_parser.py` | `parse_docs_directory()` — parses reference/deepwiki markdown into `docs_tree` |
| `graph_rubric_generator.py` | `GraphRubricGenerator` — queries potpie code graph for ground-truth rubrics (Mode B) |

## Architecture

```
evaluate_wiki.py
  ├── Mode A: --reference-docs-dir provided
  │     ├── parse_docs_directory()           → docs_tree
  │     ├── generate_reference_rubrics()     → reference_rubrics (LLM)
  │     └── WikiEvaluator.evaluate_async(final_rubrics=reference_rubrics)
  │           └── Steps 5-7: evaluate, score, report
  │
  └── Mode B: no --reference-docs-dir
        ├── PotpieRuntime + GraphRubricGenerator  → graph_rubrics
        └── WikiEvaluator.evaluate_async(graph_rubrics=graph_rubrics, wiki_dir=wiki_dir)
              ├── Step 1: parse wiki          → docs_tree
              ├── Step 2: LLM rubrics         → ai_rubrics
              ├── Step 4: merge               → merged_rubrics
              └── Steps 5-7: evaluate, score, report
```

## Troubleshooting

**Empty wiki content**
Check that `--wiki-dir` exists and contains `.md` files. Try an absolute path.

**`project_id` not found**
Run using the potpie venv Python: `.venv/bin/python ...`. Ensure the project is parsed
and `POSTGRES_SERVER` / `REDIS_URL` are set in `.env`.

**Reference-docs rubrics failed / fell back to Mode B**
Check that `--reference-docs-dir` points to a directory containing `.md` files and that
the LLM model is reachable. A warning is printed and Mode B is used automatically.

**Import errors**
Always run using the potpie venv Python:
`.venv/bin/python .kiro/skills/wiki-evaluator/scripts/evaluate_wiki.py ...`
