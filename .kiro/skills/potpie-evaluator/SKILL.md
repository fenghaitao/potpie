---
name: potpie-evaluator
description: Evaluates potpie QnA agent response quality using pydantic_evals LLMJudge metrics (AnswerRelevancy, Faithfulness, ContextualRelevancy, ContextualPrecision, ContextualRecall). Scores live agent responses against questions; optional golden answers unlock the retrieval-quality metrics.
homepage: https://github.com/intel-sandbox/potpie
requires:
  - potpie venv Python (`.venv/bin/python`)
---

# Potpie QnA Evaluator Skill

Evaluates the quality of potpie's QnA agent responses using `pydantic_evals` LLMJudge rubrics and deepeval-ported retrieval metrics. Sends live questions to the agent, collects answers and retrieval context, and scores them. No deepeval dependency.

## When to Use This Skill

- Measuring QnA agent response quality on a codebase project
- Regression testing after agent or model changes
- Benchmarking answer relevancy and retrieval quality across different projects

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

Create a YAML file with questions. Golden answers are optional — only the two retrieval-ranking metrics (`ContextualPrecision`, `ContextualRecall`) require them:

```yaml
cases:
  # Minimal — runs AnswerRelevancy, Faithfulness, ContextualRelevancy
  - question: "What is the overall architecture of this codebase?"

  # With golden answer — also runs ContextualPrecision and ContextualRecall
  - question: "What is the main entry point?"
    expected_output: "app/main.py bootstraps the FastAPI application."
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
| `--cases` | yes | — | YAML file with questions (and optional `expected_output`) |
| `--repo` | yes* | — | Repo name to auto-resolve project ID |
| `--project-id` | yes* | — | Potpie project ID (alternative to `--repo`) |
| `--agent-id` | no | `codebase_qna_agent` | Agent to query |
| `--user-id` | no | `defaultuser` (or `POTPIE_USER_ID` env) | User ID owning the project |
| `--model` | no | `LITELLM_MODEL_NAME` or `CHAT_MODEL` env | LLM for scoring |
| `--output` | no | `score.md` | Output report path |
| `--debug-log` | no | _(disabled)_ | Append per-rubric LLM judge trace to FILE |

*One of `--repo` or `--project-id` is required.

### Step 3: Read Results

The output markdown report contains:
- Overall score and per-metric averages
- Per-case breakdown with the agent's full answer, retrieved context chunks, and per-metric scores + reasons

**Passing threshold:** 50% per metric, 50% overall.

## Metrics

All metrics share a single judge model instance (configured once via `_build_judge_model`) and are executed through the same `Dataset.evaluate` / `LLMJudge` pipeline, so every scoring LLM call uses exactly the same model configuration.

### AnswerRelevancy
Measures whether the agent's answer is relevant to the question. Uses three LLMJudge rubrics (directness, absence of irrelevant content, specificity) and averages the pass rate. **Always computed.**

### Faithfulness
Measures whether every factual claim in the answer is grounded in the retrieved context chunks. Uses a single rubric. **Requires `retrieval_context`.**

### ContextualRelevancy *(ported from deepeval)*
Asks the LLM to extract statements from each retrieved context chunk and classify each as relevant (`yes`) or irrelevant (`no`) to the question. Score = `relevant_statements / total_statements`. **Requires `retrieval_context`.**

### ContextualPrecision *(ported from deepeval)*
Asks the LLM to classify each retrieved context node as useful (`yes`) or not (`no`) for producing the expected output, then computes a weighted MAP (Mean Average Precision) score. Relevant nodes ranked higher receive a better score. **Requires `retrieval_context` + `expected_output`.**

### ContextualRecall *(ported from deepeval)*
Asks the LLM to determine whether each sentence in the expected output can be attributed to at least one retrieved context node. Score = `attributed_sentences / total_sentences`. **Requires `retrieval_context` + `expected_output`.**

## Scoring Thresholds

| Score | Status |
|-------|--------|
| ≥ 70% | Good |
| ≥ 50% | Pass |
| < 50% | Fail |

## Architecture

```
evaluate_qna.py            # Entry point: loads questions, calls agent, runs scoring
  └── PotpieRuntime        # Direct Python call to agent (no HTTP)
  └── QnAEvaluator         # Orchestrates all 5 metrics
        ├── _build_judge_model()          # Configures the shared judge model once
        └── Dataset.evaluate(...)         # pydantic_evals Dataset + LLMJudge pipeline
              ├── AnswerRelevancy, Faithfulness
              ├── ContextualRelevancy
              ├── ContextualPrecision
              ├── ContextualRecall
              ├── _run_rubrics()                # pydantic_evals LLMJudge (all 5 metrics)
              │     └── _evaluate_dataset()     # Dataset.evaluate no-op task wrapper
              ├── _evaluate_dataset_per_case()  # Per-node booleans for MAP (ContextualPrecision)
              ├── _score_contextual_relevancy() # One Case per context chunk
              ├── _score_contextual_precision() # One Case per context node → MAP
              └── _score_contextual_recall()    # One Case per expected-output sentence
```

## Debugging

Enable the per-rubric LLM judge trace to understand exactly what text each judge call sees and what verdict it returns:

```bash
source .env && .venv/bin/python .kiro/skills/potpie-evaluator/scripts/evaluate_qna.py \
  --cases evaluation/qna/qna_eval_dml_cases.yaml \
  --repo <repo-name> \
  --debug-log /tmp/qna_judge_trace.log
```

The log records for every rubric call:
- The full rubric text sent to the LLM judge
- The `task_output` (text the judge evaluates)
- The `inputs` dataclass (question/answer/context passed to the Case)
- The resulting average assertion score

This is the primary tool for diagnosing why `ContextualRecall` or `ContextualRelevancy` scores unexpectedly low.

## Troubleshooting

**Empty answers**
Check that the repo name resolves to a valid project and the project is fully parsed. Try `--project-id` directly if `--repo` lookup fails.

**`retrieval_context` is always 0 chunks**
Faithfulness, ContextualRelevancy, ContextualPrecision, and ContextualRecall will all be skipped; AnswerRelevancy still runs.

**ContextualPrecision / ContextualRecall scoring against agent answer instead of golden reference**
When no `expected_output` or `golden_answer` is present in the YAML, both metrics fall back to using the agent's own answer as the reference. The report reason field will say `[reference: agent answer]`. Add `expected_output` to the case for ground-truth comparison.

**Import errors**
Run using the potpie venv Python: `.venv/bin/python .kiro/skills/potpie-evaluator/scripts/evaluate_qna.py ...`
