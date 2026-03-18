---
name: potpie-evaluator
description: Evaluates potpie QnA agent response quality using pydantic_evals LLMJudge metrics (AnswerRelevancy, Faithfulness). No golden answers required — scores live agent responses against the questions.
homepage: https://github.com/intel-sandbox/potpie
requires:
  - potpie venv Python (`.venv/bin/python`)
---

# Potpie QnA Evaluator Skill

Evaluates the quality of potpie's QnA agent responses using `pydantic_evals` LLMJudge rubrics. Sends live questions to the agent, collects answers, and scores them — no golden reference answers needed. No deepeval dependency.

## When to Use This Skill

- Measuring QnA agent response quality on a codebase project
- Regression testing after agent or model changes
- Benchmarking answer relevancy across different projects

## Quick Start

```bash
cd potpie
source .env && .venv/bin/python .kiro/skills/potpie-evaluator/scripts/evaluate_qna.py \
  --cases evaluation/qna/qna_eval_dml_cases.yaml \
  --repo <repo-name> \
  --output evaluation/qna/score.md
```

The `--repo` flag auto-resolves the project ID from the project list by repo name. You can also pass `--project-id <id>` directly if you already have it.

## Prerequisites

- potpie `.venv` with all dependencies installed
- `.env` file with `CHAT_MODEL` set (e.g. `github_copilot/gpt-4o`)
- A parsed potpie project (visible in the project list)

## Evaluation Workflow

### Step 1: Prepare a Cases File

Create a YAML file with questions only — no golden answers needed:

```yaml
cases:
  - question: "What is the overall architecture of this codebase?"
  - question: "What is the main entry point?"
  - question: "How does the parser work?"
```

### Step 2: Run Evaluation

```bash
cd potpie
source .env && .venv/bin/python .kiro/skills/potpie-evaluator/scripts/evaluate_qna.py \
  --cases evaluation/qna/<cases-file>.yaml \
  --repo <repo-name> \
  --output evaluation/qna/score.md
```

**Arguments:**

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--cases` | yes | — | YAML file with questions |
| `--repo` | yes* | — | Repo name to auto-resolve project ID |
| `--project-id` | yes* | — | Potpie project ID (alternative to `--repo`) |
| `--agent-id` | no | `codebase_qna_agent` | Agent to query |
| `--user-id` | no | `defaultuser` (or `POTPIE_USER_ID` env) | User ID owning the project |
| `--model` | no | `LITELLM_MODEL_NAME` or `CHAT_MODEL` env | LLM for scoring |
| `--output` | no | `score.md` | Output report path |

*One of `--repo` or `--project-id` is required.

### Step 3: Read Results

The output markdown report contains:
- Overall score and per-metric averages
- Per-case breakdown with the agent's full answer and relevancy score + reason

**Passing threshold:** 50% per metric, 50% overall.

## Metrics

### AnswerRelevancy
Measures whether the agent's answer is relevant to the question. Uses three LLMJudge rubrics (directness, absence of irrelevant content, specificity) and averages the pass rate.

### Faithfulness
Measures whether claims in the answer are grounded in retrieved context chunks. Only runs when `retrieval_context` is non-empty. Uses a single rubric checking all claims against the context.

Both metrics use the same `CopilotModel` / `LiteLLMModel` as the agent — no separate API key needed.

## Scoring Thresholds

| Score | Status |
|-------|--------|
| ≥ 70% | Good |
| ≥ 50% | Pass |
| < 50% | Fail |

## Architecture

```
evaluate_qna.py          # Entry point: loads questions, calls agent, runs scoring
  └── PotpieRuntime      # Direct Python call to agent (no HTTP)
  └── QnAEvaluator       # pydantic_evals LLMJudge runner
        └── CopilotModel / LiteLLMModel   # Same model as the agent
        └── LLMJudge rubrics              # AnswerRelevancy + Faithfulness
```

## Troubleshooting

**Empty answers**
Check that the repo name resolves to a valid project and the project is fully parsed. Try `--project-id` directly if `--repo` lookup fails.

**`retrieval_context` is always 0 chunks**
Faithfulness metric will be skipped; AnswerRelevancy still runs.

**Import errors**
Run using the potpie venv Python: `.venv/bin/python .kiro/skills/potpie-evaluator/scripts/evaluate_qna.py ...`
