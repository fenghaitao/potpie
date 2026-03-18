"""QnA evaluator using pydantic_evals LLMJudge — no deepeval dependency.

Metrics:
  - AnswerRelevancy : multiple rubrics checking whether the answer addresses
                      the question directly and without irrelevant content.
  - Faithfulness    : rubrics checking whether claims are grounded in the
                      retrieved context (only when retrieval_context is present).

Each metric is the average pass-rate across its rubrics (0.0–1.0).

Copyright 2025 Intel Corporation
Licensed under the Apache License, Version 2.0
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import LLMJudge
from pydantic_evals.evaluators.llm_as_a_judge import set_default_judge_model


def _setup_judge_model(model: Optional[str] = None):
    """Point pydantic_evals at the same model potpie uses."""
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
        set_default_judge_model(CopilotModel(bare))
    else:
        set_default_judge_model(LiteLLMModel(model_name))


# Rubrics for AnswerRelevancy
_RELEVANCY_RUBRICS = [
    "The answer directly addresses the question asked.",
    "The answer does not contain significant irrelevant or off-topic content.",
    "The answer is specific and informative rather than vague or generic.",
]

# Rubrics for Faithfulness (injected with context at runtime)
_FAITHFULNESS_RUBRIC_TEMPLATE = (
    "Every factual claim in the answer is supported by the following retrieved context:\n\n{context}"
)


@dataclass
class _RelevancyInput:
    question: str
    answer: str


@dataclass
class _FaithfulnessInput:
    question: str
    answer: str
    context: str  # joined retrieval chunks


class QnAEvaluator:
    """Evaluates potpie QnA agent responses using pydantic_evals LLMJudge."""

    def __init__(self, model: Optional[str] = None):
        _setup_judge_model(model)

    def evaluate_cases(self, cases: List[Dict]) -> Dict:
        return asyncio.run(self._evaluate_cases_async(cases))

    async def _evaluate_cases_async(self, cases: List[Dict]) -> Dict:
        all_results = []
        for i, case in enumerate(cases):
            print(f"\n[{i+1}/{len(cases)}] Evaluating: {case['question'][:80]}...")
            result = await self._evaluate_single(case)
            result["question"] = case["question"]
            result["answer"] = case["answer"]
            result["retrieval_context"] = case.get("retrieval_context") or []
            all_results.append(result)
        return self._aggregate(all_results)

    async def _evaluate_single(self, case: Dict) -> Dict:
        question = case["question"]
        answer = case["answer"]
        retrieval_context: List[str] = case.get("retrieval_context") or []

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

        overall = (
            sum(v["score"] for v in metric_results.values()) / len(metric_results)
            if metric_results else 0.0
        )
        return {"overall_score": overall, "metrics": metric_results}

    async def _run_rubrics(self, inputs, task_output: str, rubrics: List[str]) -> float:
        """Run a list of LLMJudge rubrics and return the average pass rate."""
        cases = [
            Case(
                name=f"rubric_{i}",
                inputs=inputs,
                evaluators=(LLMJudge(rubric=r),),
            )
            for i, r in enumerate(rubrics)
        ]
        dataset = Dataset(cases=cases)

        async def task(_inputs):
            return task_output

        report = await dataset.evaluate(task, max_concurrency=1)

        # Extract pass/fail from report averages
        averages = report.averages()
        if averages and averages.assertions is not None:
            return float(averages.assertions)
        return 0.0

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
