#!/usr/bin/env python3
"""
Potpie QnA Agent Evaluator

Calls the live potpie QnA agent directly (via PotpieRuntime), captures
answers + retrieval_context, then scores with pydantic_evals LLMJudge rubrics:

  - AnswerRelevancy  (no golden reference needed)
  - Faithfulness     (grounded in retrieved context, when available)

No deepeval dependency — uses pydantic_evals + CopilotModel already in the venv.

Usage:
  source .env && .venv/bin/python .kiro/skills/potpie-evaluator/scripts/evaluate_qna.py \\
    --cases evaluation/qna/qna_eval_dml_cases.yaml \\
    --project-id <project_id> \\
    --output evaluation/qna/score.md

Copyright 2025 Intel Corporation
Licensed under the Apache License, Version 2.0
"""

import argparse
import asyncio
import os
import sys
import yaml
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo root on sys.path so potpie app + scoring modules are importable
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).parent.resolve()
_SCORING_PATH = _SCRIPT_DIR / "deepeval-scoring"
_REPO_ROOT = _SCRIPT_DIR.parents[3]  # <repo>/.kiro/skills/potpie-evaluator/scripts/

for _p in [str(_SCORING_PATH), str(_SCORING_PATH / "evaluators"), str(_REPO_ROOT)]:
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


def load_questions(cases_file: str) -> list:
    path = Path(cases_file)
    if not path.exists():
        print(f"[FAIL] Cases file not found: {cases_file}")
        sys.exit(1)

    with open(path) as f:
        data = yaml.safe_load(f)

    cases = data.get("cases", data) if isinstance(data, dict) else data
    questions = []
    for case in cases:
        q = case.get("question") or case.get("input") or case.get("query", "")
        if q:
            questions.append(q)
        else:
            print(f"[WARN] Skipping case with no question: {case}")

    print(f"[PASS] Loaded {len(questions)} questions from {cases_file}")
    return questions


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


async def collect_answers(questions: list, project_id: str, agent_id: str, user_id: str) -> list:
    from potpie.runtime import PotpieRuntime
    from app.modules.intelligence.agents.chat_agent import ChatContext

    runtime = PotpieRuntime.from_env()
    await runtime.initialize()

    try:
        project_info = await runtime.projects.get(project_id)
        project_name = project_info.repo_name
    except Exception as exc:
        print(f"[WARN] Could not fetch project info: {exc}")
        project_name = project_id

    cases = []
    try:
        for i, question in enumerate(questions):
            print(f"  [{i+1}/{len(questions)}] Asking: {question[:80]}...")
            try:
                agent_handle = getattr(runtime.agents, agent_id)
                ctx = ChatContext(
                    project_id=project_id,
                    project_name=project_name,
                    curr_agent_id=agent_id,
                    query=f"[project_id:{project_id}] {question}",
                    history=[],
                    user_id=user_id,
                )
                response = await agent_handle.query(ctx)
                answer = response.response or ""
                retrieval_context = response.retrieval_context or []
                print(f"    -> Got answer ({len(answer)} chars), {len(retrieval_context)} context chunks")
            except Exception as exc:
                print(f"    -> [WARN] Agent call failed: {exc}")
                answer = ""
                retrieval_context = []

            cases.append({"question": question, "answer": answer, "retrieval_context": retrieval_context})
    finally:
        await runtime.close()

    return cases


def generate_report(qna_results: dict, project_id: str, model_name: str, output: str):
    overall = qna_results["overall_score"]
    lines = [
        "# QnA Evaluation Report",
        "",
        f"**Project**: potpie-qna (project={project_id}, {qna_results['total_cases']} cases)",
        f"**Model**: {model_name}",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Overall Score",
        "",
        f"**{overall:.1%}**",
        "",
    ]
    for name, score in qna_results["metrics_summary"].items():
        status = "PASS" if score >= 0.5 else "FAIL"
        lines += [f"### {name}", "", f"**Score**: {score:.1%}  [{status}]", ""]

    report = "\n".join(lines) + "\n## Per-Case Results\n\n"
    for i, case_result in enumerate(qna_results["cases"]):
        status = "PASS" if case_result["overall_score"] >= 0.5 else "FAIL"
        report += f"### Case {i+1}: [{status}] {case_result['overall_score']:.0%}\n\n"
        report += f"**Q**: {case_result['question']}\n\n"
        if case_result.get("answer"):
            report += f"**A**: {case_result['answer']}\n\n"
        if case_result.get("retrieval_context"):
            report += "**Retrieved Context**:\n\n"
            for j, chunk in enumerate(case_result["retrieval_context"]):
                report += f"<details><summary>Chunk {j+1}</summary>\n\n```\n{chunk[:500]}{'...' if len(chunk) > 500 else ''}\n```\n\n</details>\n\n"
        for metric_name, data in case_result.get("metrics", {}).items():
            report += f"- {metric_name}: {data['score']:.0%}"
            if data.get("reason"):
                report += f" — {data['reason'][:200]}"
            report += "\n"
        report += "\n"

    Path(output).write_text(report)
    print(f"[PASS] Report saved to: {output}")


def main():
    parser = argparse.ArgumentParser(description="Potpie QnA Agent Evaluator")
    parser.add_argument("--cases", required=True, help="YAML file with questions")
    parser.add_argument("--project-id", default=None, help="Potpie project ID (or use --repo)")
    parser.add_argument("--repo", default=None, help="Repo name to auto-resolve project ID")
    parser.add_argument("--agent-id", default="codebase_qna_agent")
    parser.add_argument("--user-id", default=os.environ.get("POTPIE_USER_ID", "defaultuser"))
    parser.add_argument("--model", default=None, help="LLM model for scoring")
    parser.add_argument("--output", default="score.md")
    args = parser.parse_args()

    if not args.project_id and not args.repo:
        print("[FAIL] Provide either --project-id or --repo")
        sys.exit(1)

    if not args.project_id:
        print(f"[INFO] Resolving project ID for repo: {args.repo}")
        args.project_id = asyncio.run(resolve_project_id(args.repo, args.user_id))
        print(f"[INFO] Resolved project ID: {args.project_id}")

    # Import evaluator (uses pydantic_evals + CopilotModel, no deepeval)
    try:
        from evaluators.qna_evaluator import QnAEvaluator
    except ImportError as e:
        print(f"[FAIL] Could not import QnAEvaluator: {e}")
        sys.exit(1)

    questions = load_questions(args.cases)
    if not questions:
        print("[FAIL] No valid questions found")
        sys.exit(1)

    print(f"\n[INFO] Collecting answers from '{args.agent_id}' (project={args.project_id})...")
    cases = asyncio.run(collect_answers(questions, args.project_id, args.agent_id, args.user_id))

    valid_cases = [c for c in cases if c["answer"].strip()]
    if not valid_cases:
        print("[FAIL] All agent responses were empty")
        sys.exit(1)
    if len(valid_cases) < len(cases):
        print(f"[WARN] {len(cases) - len(valid_cases)} cases skipped (empty answers)")

    print(f"\n[INFO] Scoring {len(valid_cases)} cases with pydantic_evals LLMJudge...")
    evaluator = QnAEvaluator(model=args.model)
    results = evaluator.evaluate_cases(valid_cases)

    model_name = args.model or os.environ.get("LITELLM_MODEL_NAME") or os.environ.get("CHAT_MODEL", "default")
    print("\n[INFO] Generating report...")
    generate_report(results, args.project_id, model_name, args.output)

    overall = results["overall_score"]
    passed = results["passed_cases"]
    total = results["total_cases"]
    print(f"\n{'='*60}")
    print("QnA EVALUATION SUMMARY")
    print(f"{'='*60}")
    print(f"  Overall Score : {overall:.1%}")
    print(f"  Cases Passed  : {passed}/{total}")
    for name, score in results["metrics_summary"].items():
        status = "PASS" if score >= 0.5 else "FAIL"
        print(f"  [{status}] {name}: {score:.1%}")
    print(f"{'='*60}\n")

    sys.exit(0 if overall >= 0.5 else 1)


if __name__ == "__main__":
    main()
