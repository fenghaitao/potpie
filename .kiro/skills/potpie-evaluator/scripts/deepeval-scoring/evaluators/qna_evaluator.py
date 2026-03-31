"""QnA evaluator using pydantic_evals LLMJudge — no deepeval dependency.

Metrics
-------
  - AnswerRelevancy      : multiple rubrics checking whether the answer addresses
                           the question directly and without irrelevant content.
                           Computed for every case.
  - Faithfulness         : checks whether every claim in the answer is grounded in
                           the retrieved context chunks.
                           Computed when ``retrieval_context`` is non-empty.
  - ContextualRelevancy  : fraction of statements extracted from each retrieved
                           context chunk that are relevant to the question.
                           Ported from deepeval ContextualRelevancyMetric.
                           Computed when ``retrieval_context`` is non-empty.
  - ContextualPrecision  : weighted MAP-like score measuring whether relevant
                           context nodes are ranked above irrelevant ones.
                           Ported from deepeval ContextualPrecisionMetric.
                           Computed when ``retrieval_context`` is non-empty.
                           Uses ``expected_output`` / ``golden_answer`` as the
                           reference; falls back to the agent answer when absent.
  - ContextualRecall     : fraction of sentences in the expected output that can be
                           attributed to at least one retrieved context node.
                           Ported from deepeval ContextualRecallMetric.
                           Computed when ``retrieval_context`` is non-empty.
                           Uses ``expected_output`` / ``golden_answer`` as the
                           reference; falls back to the agent answer when absent.

All five metrics use the pydantic_evals ``Dataset.evaluate`` / ``LLMJudge`` pipeline
— one ``Case`` per judgement unit (rubric / context node / sentence), with a no-op
task that returns the pre-computed text.  No raw LLM calls or JSON parsing needed.
Each metric score is in [0.0, 1.0].

Copyright 2025 Intel Corporation
Licensed under the Apache License, Version 2.0
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import LLMJudge
from pydantic_evals.evaluators.llm_as_a_judge import set_default_judge_model


def _build_judge_model(model: Optional[str] = None):
    """Instantiate and return the judge model, also registering it with pydantic_evals."""
    from app.modules.intelligence.provider.copilot_model import CopilotModel
    from app.modules.intelligence.provider.litellm_model import LiteLLMModel

    model_name = (
        model
        or os.environ.get("LITELLM_MODEL_NAME")
        or os.environ.get("CHAT_MODEL")
        or "github_copilot/gpt-4o"
    )
    if model_name.startswith("copilot_cli/"):
        bare = model_name.split("/", 1)[1]
        judge = CopilotModel(bare)
    else:
        judge = LiteLLMModel(model_name)
    set_default_judge_model(judge)
    return judge


# ---------------------------------------------------------------------------
# Rubrics — AnswerRelevancy
# ---------------------------------------------------------------------------
_RELEVANCY_RUBRICS = [
    "The answer directly addresses the question asked.",
    "The answer does not contain significant irrelevant or off-topic content.",
    "The answer is specific and informative rather than vague or generic.",
]

# Rubric template — Faithfulness (context injected at runtime)
_FAITHFULNESS_RUBRIC_TEMPLATE = (
    "Every factual claim in the answer is supported by the following retrieved context:\n\n{context}"
)

# Rubric templates — ContextualRelevancy, ContextualPrecision, ContextualRecall
_CONTEXTUAL_RELEVANCY_RUBRIC_TEMPLATE = (
    "The context chunk below provides information that is useful for answering the question: {question}\n\n"
    "The chunk may contain source code, file paths, directory listings, documentation, or other "
    "repository content. Consider it relevant if it contains any information that directly or "
    "indirectly helps answer the question — even partial or structural information counts.\n\n"
    "Context:\n{context}"
)
_CONTEXTUAL_PRECISION_RUBRIC_TEMPLATE = (
    "The following retrieved context node is useful for producing the expected output.\n\n"
    "Question: {question}\n"
    "Expected output: {expected_output}\n\n"
    "Context node:\n{node}"
)
_CONTEXTUAL_RECALL_RUBRIC_TEMPLATE = (
    "The following sentence from the expected output can be attributed to (is supported by) "
    "the retrieved context below.\n\n"
    "Sentence: {sentence}\n\n"
    "Retrieved context:\n{context}"
)

# ---------------------------------------------------------------------------
# Input dataclasses (pydantic_evals Case inputs — one per judgement unit)
# ---------------------------------------------------------------------------


@dataclass
class _RelevancyInput:
    question: str
    answer: str


@dataclass
class _FaithfulnessInput:
    question: str
    answer: str
    context: str  # joined retrieval chunks


@dataclass
class _ContextualRelevancyInput:
    question: str
    context_chunk: str


@dataclass
class _ContextualPrecisionInput:
    question: str
    expected_output: str
    node: str


@dataclass
class _ContextualRecallInput:
    sentence: str
    context: str  # full joined retrieval context


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _calculate_contextual_precision(pass_flags: List[bool]) -> float:
    """Weighted MAP score identical to deepeval's _calculate_score()."""
    if not pass_flags:
        return 0.0
    sum_weighted = 0.0
    relevant_count = 0
    for k, is_relevant in enumerate(pass_flags, start=1):
        if is_relevant:
            relevant_count += 1
            sum_weighted += relevant_count / k
    if relevant_count == 0:
        return 0.0
    return sum_weighted / relevant_count


def _extract_text_from_chunk(chunk) -> Optional[str]:
    """Extract readable text from a context chunk returned by the agent.

    The agent's tool results are stored verbatim as strings, but they often
    contain JSON-serialised structures such as:
      - ``[{'file_path': '...', 'docstring': '...', 'text': '...'}]``
      - ``{'success': True/False, 'content': '...', ...}``
      - ``[[]]``  (empty / error result)
      - plain prose strings

    The strings may use either JSON double-quotes or Python single-quotes
    (from ``repr()``/``str()`` of a list/dict).  Both forms are handled:
    ``json.loads`` is tried first; if it fails and the raw string starts with
    ``[`` or ``{``, ``ast.literal_eval`` is tried next so the same
    field-extraction logic applies.  Strings that parse to neither dict nor list
    (e.g. bare integers) return *None*.

    Returns *None* if the chunk contains no usable content (empty, error-only,
    or a null result).
    """
    import ast
    import json as _json

    if not isinstance(chunk, str):
        chunk = str(chunk)

    raw = chunk.strip()
    if not raw or raw in ("[[]]", "[]", "null", "None"):
        return None

    # Python repr of query responses like [[QueryResponse(...)], []] — not JSON,
    # not useful prose.  Detect by a leading '[' but failing JSON parse + looking
    # like a Python object repr, and discard.
    if raw.startswith("[") and "QueryResponse(" in raw:
        return None

    # Try JSON first (double-quoted, standard serialisation)
    parsed = None
    try:
        parsed = _json.loads(raw)
    except Exception:
        pass

    # Fallback: try ast.literal_eval for Python list/dict literals (single-quoted strings,
    # True/False/None booleans, etc.) — only attempt when the string looks like a
    # container to avoid accidentally evaluating arbitrary prose.
    if parsed is None and raw and raw[0] in ("[", "{"):
        try:
            candidate = ast.literal_eval(raw)
            if isinstance(candidate, (list, dict)):
                parsed = candidate
        except Exception:
            pass

    # Neither parser succeeded — return the raw string as prose (capped)
    if parsed is None:
        return raw[:4000] if raw else None

    # Parsed to a scalar (int, float, bool, …) — no text to extract
    if not isinstance(parsed, (list, dict)):
        return None

    def _extract(obj) -> List[str]:
        """Recursively pull text/content/docstring fields out of parsed JSON."""
        texts: List[str] = []
        if isinstance(obj, list):
            for item in obj:
                texts.extend(_extract(item))
        elif isinstance(obj, dict):
            # Prefer 'text' field (code/file content), then 'content', then 'docstring'
            for field in ("text", "content", "docstring"):
                val = obj.get(field)
                if val and isinstance(val, str) and val.strip():
                    texts.append(val.strip())
                    break  # one field per dict node is enough
            # Recurse into nested structures when none of the known fields matched
            if not texts:
                for v in obj.values():
                    if isinstance(v, (dict, list)):
                        texts.extend(_extract(v))
        return texts

    parts = _extract(parsed)
    if not parts:
        return None
    joined = "\n\n".join(parts)
    return joined[:4000] if joined.strip() else None


def _normalize_retrieval_context(retrieval_context: List[str]) -> List[str]:
    """Clean up raw agent context chunks into plain readable text.

    Filters out empty / error-only chunks so metrics are not confused by
    JSON scaffolding or tool-call error messages.
    """
    cleaned: List[str] = []
    for chunk in retrieval_context:
        text = _extract_text_from_chunk(chunk)
        if text:
            cleaned.append(text)
    return cleaned


# ---------------------------------------------------------------------------
# Optional session debug log
# ---------------------------------------------------------------------------

_debug_log = None  # file object; set via set_debug_log()


def set_debug_log(path: str) -> None:
    """Open *path* for append and direct per-rubric LLM judge tracing to it.

    Call this before :meth:`QnAEvaluator.evaluate_cases` to capture every
    rubric text, the task output shown to the judge, and the resulting pass/fail
    verdict + score.  Useful for diagnosing why a metric scores unexpectedly.

    The file is flushed after every entry so it is readable mid-run.
    """
    global _debug_log
    import io
    _debug_log = open(path, "a", encoding="utf-8", buffering=1)  # line-buffered
    ts = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _debug_log.write(f"\n{'='*80}\n[SESSION] {ts}\n{'='*80}\n")


def _dlog(msg: str) -> None:
    """Write *msg* to the debug log if one is open; no-op otherwise."""
    if _debug_log is not None:
        _debug_log.write(msg + "\n")


# ---------------------------------------------------------------------------
# Main evaluator class
# ---------------------------------------------------------------------------

class QnAEvaluator:
    """Evaluates potpie QnA agent responses using pydantic_evals LLMJudge.

    All metrics use the same ``Dataset.evaluate`` / ``LLMJudge`` pipeline:
    one ``Case`` per judgement unit, a no-op task returning the target text,
    and ``LLMJudge`` doing the actual evaluation.

    Metrics computed per case:
      - AnswerRelevancy      : always
      - Faithfulness         : when retrieval_context is non-empty
      - ContextualRelevancy  : when retrieval_context is non-empty
      - ContextualPrecision  : when retrieval_context is non-empty
                               (uses expected_output/golden_answer or falls back to answer)
      - ContextualRecall     : when retrieval_context is non-empty
                               (uses expected_output/golden_answer or falls back to answer)
    """

    def __init__(self, model: Optional[str] = None):
        self._judge_model = _build_judge_model(model)

    def evaluate_cases(self, cases: List[Dict]) -> Dict:
        return asyncio.run(self._evaluate_cases_async(cases))

    async def _evaluate_cases_async(self, cases: List[Dict]) -> Dict:
        all_results = []
        for i, case in enumerate(cases):
            print(f"\n[{i+1}/{len(cases)}] Evaluating: {case['question'][:80]}...")
            result = await self._evaluate_single(case)
            result["question"] = case["question"]
            result["answer"] = case["answer"]
            # _evaluate_single already normalised the context and stored it in
            # the result so the report shows exactly what the metrics saw.
            all_results.append(result)
        return self._aggregate(all_results)

    async def _evaluate_single(self, case: Dict) -> Dict:
        question = case["question"]
        answer = case["answer"]
        raw_context: List[str] = case.get("retrieval_context") or []
        retrieval_context = _normalize_retrieval_context(raw_context)
        # Use explicit golden reference when provided; fall back to the agent's
        # own answer so ContextualPrecision/Recall always run when context exists.
        golden = case.get("expected_output") or case.get("golden_answer")
        expected_output: str = golden or answer
        using_answer_as_reference = not golden

        # --- debug logging ---------------------------------------------------
        if _debug_log is not None:
            _dlog(f"\n{'#'*70}")
            _dlog(f"[CASE] Q: {question[:120]}")
            _dlog(f"  raw context chunks  : {len(raw_context)}")
            _dlog(f"  clean context chunks: {len(retrieval_context)}")
            _dlog(f"  reference source    : {'golden' if golden else 'agent answer (fallback)'}")
            _dlog(f"  expected_output[:200]: {expected_output[:200]}")
            for i, chunk in enumerate(retrieval_context):
                _dlog(f"  chunk[{i}]: {chunk[:200]}")
        # ---------------------------------------------------------------------

        metric_results: Dict[str, Dict] = {}

        # --- AnswerRelevancy ---
        rel_score = await self._run_rubrics(
            inputs=_RelevancyInput(question=question, answer=answer),
            task_output=answer,
            rubrics=_RELEVANCY_RUBRICS,
        )
        metric_results["AnswerRelevancy"] = {
            "score": rel_score,
            "reason": f"Average of {len(_RELEVANCY_RUBRICS)} relevancy rubrics",
            "success": rel_score >= 0.5,
            "threshold": 0.5,
        }

        # --- Faithfulness (only when context is available) ---
        if retrieval_context:
            joined = "\n\n---\n\n".join(retrieval_context[:10])  # cap to avoid token bloat
            faith_score = await self._run_rubrics(
                inputs=_FaithfulnessInput(question=question, answer=answer, context=joined),
                task_output=answer,
                rubrics=[_FAITHFULNESS_RUBRIC_TEMPLATE.format(context=joined[:3000])],
            )
            metric_results["Faithfulness"] = {
                "score": faith_score,
                "reason": "Claims grounded in retrieved context",
                "success": faith_score >= 0.5,
                "threshold": 0.5,
            }

        # --- ContextualRelevancy (one Case per context chunk) ---
        if retrieval_context:
            try:
                cr_score = await self._score_contextual_relevancy(question, retrieval_context)
            except Exception as exc:  # noqa: BLE001
                print(f"    [WARN] ContextualRelevancy failed: {exc}")
                cr_score = 0.0
            metric_results["ContextualRelevancy"] = {
                "score": cr_score,
                "reason": "Fraction of context chunks relevant to the question",
                "success": cr_score >= 0.5,
                "threshold": 0.5,
            }

        # --- ContextualPrecision (one Case per context node, then MAP) ---
        if retrieval_context:
            try:
                cp_score = await self._score_contextual_precision(
                    question, expected_output, retrieval_context
                )
            except Exception as exc:  # noqa: BLE001
                print(f"    [WARN] ContextualPrecision failed: {exc}")
                cp_score = 0.0
            metric_results["ContextualPrecision"] = {
                "score": cp_score,
                "reason": (
                    "Relevant nodes ranked above irrelevant ones (weighted MAP)"
                    + (" [reference: agent answer]" if using_answer_as_reference else "")
                ),
                "success": cp_score >= 0.5,
                "threshold": 0.5,
            }

        # --- ContextualRecall (one Case per expected-output sentence) ---
        if retrieval_context:
            try:
                rec_score = await self._score_contextual_recall(
                    expected_output, retrieval_context
                )
            except Exception as exc:  # noqa: BLE001
                print(f"    [WARN] ContextualRecall failed: {exc}")
                rec_score = 0.0
            metric_results["ContextualRecall"] = {
                "score": rec_score,
                "reason": (
                    "Fraction of expected-output sentences attributable to context"
                    + (" [reference: agent answer]" if using_answer_as_reference else "")
                ),
                "success": rec_score >= 0.5,
                "threshold": 0.5,
            }

        overall = (
            sum(v["score"] for v in metric_results.values()) / len(metric_results)
            if metric_results else 0.0
        )
        return {
            "overall_score": overall,
            "metrics": metric_results,
            # Expose the exact normalized context used for scoring so callers
            # and the report always reflect what the metrics actually saw.
            "retrieval_context": retrieval_context,
        }

    # ------------------------------------------------------------------
    # Shared pydantic_evals runner
    # ------------------------------------------------------------------

    async def _run_rubrics(
        self,
        inputs,  # single object (shared) OR list (one per rubric)
        task_output: str,
        rubrics: List[str],
    ) -> float:
        """Build one Case per rubric, evaluate, return average assertion pass-rate.

        *inputs* may be a single dataclass instance that is reused for every
        Case, or a list of dataclass instances — one per rubric entry.  The
        list form lets the three context-aware metrics (ContextualRelevancy,
        ContextualPrecision, ContextualRecall) reuse this method instead of
        duplicating the Case-building / Dataset.evaluate boilerplate.
        """
        inputs_list = inputs if isinstance(inputs, list) else [inputs] * len(rubrics)
        cases = [
            Case(
                name=f"rubric_{i}",
                inputs=inp,
                evaluators=(LLMJudge(rubric=r),),
            )
            for i, (inp, r) in enumerate(zip(inputs_list, rubrics))
        ]
        score = await self._evaluate_dataset(cases, task_output)

        # --- debug logging ---------------------------------------------------
        if _debug_log is not None:
            sep = "-" * 60
            for i, (case, rubric) in enumerate(zip(cases, rubrics)):
                _dlog(f"\n{sep}")
                _dlog(f"[RUBRIC {i}] {case.name}")
                _dlog(f"  rubric      : {rubric[:400]}")
                _dlog(f"  task_output : {str(task_output)[:300]}")
                _dlog(f"  inputs      : {str(case.inputs)[:300]}")
            _dlog(f"  >> avg score: {score:.3f}")
        # ---------------------------------------------------------------------

        return score

    async def _evaluate_dataset(self, cases: List[Case], task_output: str) -> float:
        """Run ``Dataset.evaluate`` with a no-op task and return the assertion average."""
        dataset = Dataset(cases=cases)

        async def _task(_inputs):
            return task_output

        report = await dataset.evaluate(_task, max_concurrency=1)
        averages = report.averages()
        if averages and averages.assertions is not None:
            return float(averages.assertions)
        return 0.0

    async def _evaluate_dataset_per_case(self, cases: List[Case], task_outputs: List[str]) -> List[bool]:
        """Run each Case with its own task output and return per-case pass flags.

        Used by ContextualPrecision which needs individual verdicts to compute MAP.
        """
        results: List[bool] = []
        for case, task_output in zip(cases, task_outputs):
            dataset = Dataset(cases=[case])

            async def _task(_inputs, _out=task_output):
                return _out

            report = await dataset.evaluate(_task, max_concurrency=1)
            averages = report.averages()
            passed = (
                averages is not None
                and averages.assertions is not None
                and float(averages.assertions) >= 0.5
            )
            results.append(passed)
        return results

    # ------------------------------------------------------------------
    # ContextualRelevancy
    # One Case per context chunk; rubric checks relevance to the question.
    # Score = fraction of chunks that pass.
    # ------------------------------------------------------------------

    async def _score_contextual_relevancy(
        self,
        question: str,
        retrieval_context: List[str],
    ) -> float:
        if not retrieval_context:
            return 0.0
        if isinstance(retrieval_context, str):
            raise TypeError(
                "_score_contextual_relevancy expects a list of strings, not a bare string"
            )
        chunks = retrieval_context[:10]  # cap to avoid token bloat
        return await self._run_rubrics(
            inputs=[_ContextualRelevancyInput(question=question, context_chunk=c) for c in chunks],
            task_output="",
            rubrics=[
                _CONTEXTUAL_RELEVANCY_RUBRIC_TEMPLATE.format(question=question, context=c)
                for c in chunks
            ],
        )

    # ------------------------------------------------------------------
    # ContextualPrecision
    # One Case per context node; rubric checks usefulness for expected_output.
    # Per-node verdicts feed the MAP formula.
    # ------------------------------------------------------------------

    async def _score_contextual_precision(
        self,
        question: str,
        expected_output: str,
        retrieval_context: List[str],
    ) -> float:
        if isinstance(retrieval_context, str):
            raise TypeError(
                "_score_contextual_precision expects a list of strings, not a bare string"
            )
        cases = [
            Case(
                name=f"cp_node_{i}",
                inputs=_ContextualPrecisionInput(
                    question=question,
                    expected_output=expected_output,
                    node=node,
                ),
                evaluators=(
                    LLMJudge(
                        rubric=_CONTEXTUAL_PRECISION_RUBRIC_TEMPLATE.format(
                            question=question,
                            expected_output=expected_output,
                            node=node,
                        )
                    ),
                ),
            )
            for i, node in enumerate(retrieval_context)
        ]
        pass_flags = await self._evaluate_dataset_per_case(
            cases, task_outputs=list(retrieval_context)
        )
        return _calculate_contextual_precision(pass_flags)

    # ------------------------------------------------------------------
    # ContextualRecall
    # Split expected_output into sentences; one Case per sentence.
    # Rubric checks whether the sentence is supported by the full context.
    # Score = fraction of sentences that pass.
    # ------------------------------------------------------------------

    async def _score_contextual_recall(
        self,
        expected_output: str,
        retrieval_context: List[str],
    ) -> float:
        if isinstance(retrieval_context, str):
            raise TypeError(
                "_score_contextual_recall expects a list of strings, not a bare string"
            )
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", expected_output) if s.strip()]
        if not sentences:
            return 0.0
        joined_context = "\n\n---\n\n".join(retrieval_context[:10])
        return await self._run_rubrics(
            inputs=[_ContextualRecallInput(sentence=s, context=joined_context) for s in sentences],
            task_output="",
            rubrics=[
                _CONTEXTUAL_RECALL_RUBRIC_TEMPLATE.format(
                    sentence=s, context=joined_context[:3000]
                )
                for s in sentences
            ],
        )

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def _aggregate(self, all_results: List[Dict]) -> Dict:
        if not all_results:
            return {
                "overall_score": 0.0,
                "cases": [],
                "metrics_summary": {},
                "total_cases": 0,
                "passed_cases": 0,
            }

        metrics_summary: Dict[str, List[float]] = {}
        for r in all_results:
            for name, data in r.get("metrics", {}).items():
                metrics_summary.setdefault(name, []).append(data["score"])

        avg_metrics = {
            name: sum(scores) / len(scores)
            for name, scores in metrics_summary.items()
        }
        overall = sum(avg_metrics.values()) / len(avg_metrics) if avg_metrics else 0.0

        return {
            "overall_score": overall,
            "metrics_summary": avg_metrics,
            "cases": all_results,
            "total_cases": len(all_results),
            "passed_cases": sum(1 for r in all_results if r["overall_score"] >= 0.5),
        }
