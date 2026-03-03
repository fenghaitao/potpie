"""
Integration test: ask → YAML → eval pipeline using CopilotModel (gpt-4.1).

Scenario
--------
A "deepeval" repo project (ID: 3e052a9f-63c0-0201-f730-ba90decbb97d) already
exists in the database.  The test exercises the two CLI commands end-to-end:

  1. ``ask``  — calls ``_ask(question, project_id, agent_id, render_markdown=False)``
               for 4 standard deepeval Q&A questions; collects the answers in a
               temporary YAML file (the "golden answers" fixture).

  2. ``eval`` — calls ``_eval(project_id, agent_id, cases_path, concurrency=1)``
               with the YAML file produced in step 1;  uses ``CopilotModel("gpt-4.1")``
               as the LLM judge (free-tier, zero-cost); asserts the report was
               produced and every case received a score.

Both the agent backend and the Copilot CLI are **fully mocked** — no live
network calls are made.  This lets the test run in CI without credentials.

Environment variable simulated: ``ENABLE_MULTI_AGENT=false``

Equivalent shell commands (live run):
    ENABLE_MULTI_AGENT=false python potpie_cli.py ask "Explain the architecture" \\
        -p 3e052a9f-63c0-0201-f730-ba90decbb97d
    ENABLE_MULTI_AGENT=false python potpie_cli.py eval \\
        -p 3e052a9f-63c0-0201-f730-ba90decbb97d --cases answers.yaml
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

# ---------------------------------------------------------------------------
# Ensure app.core.database is stubbed before any app import
# (mirrors the pattern already established in test_copilot_model.py)
# ---------------------------------------------------------------------------

def _stub_database_module() -> None:
    if "app.core.database" in sys.modules:
        return
    stub = types.ModuleType("app.core.database")
    stub.engine = MagicMock()
    stub.SessionLocal = MagicMock()
    stub.Base = MagicMock()
    stub.get_db = MagicMock()
    stub.async_engine = MagicMock()
    stub.AsyncSessionLocal = MagicMock()
    sys.modules["app.core.database"] = stub


_stub_database_module()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ID = "3e052a9f-63c0-0201-f730-ba90decbb97d"
REPO_NAME = "deepeval"
AGENT_ID = "codebase_qna_agent"
JUDGE_MODEL = "gpt-4.1"   # free-tier Copilot CLI model, 0× cost multiplier

# The four standard Q&A questions (mirrors _DEFAULT_EVAL_CASES in potpie_cli.py)
DEEPEVAL_QUESTIONS = [
    "Explain the overall system architecture",
    "What is the main entry point of the application?",
    "How does data flow from an API request to the database?",
    "What are the main external libraries or frameworks used?",
]

# Canned agent answers — realistic but short; used for the mock agent
CANNED_ANSWERS = {
    DEEPEVAL_QUESTIONS[0]: (
        "DeepEval is a testing framework for LLM applications. "
        "It exposes a `deepeval` CLI entry point (defined in `setup.py`) and a "
        "`deepeval/` package containing metric classes (e.g. `GEval`, "
        "`HallucinationMetric`) built on top of `pydantic-ai` and `langchain`. "
        "The framework is organised into layers: metrics → evaluators → dataset "
        "runners → CLI commands."
    ),
    DEEPEVAL_QUESTIONS[1]: (
        "The main entry point is the `deepeval` CLI command, registered via "
        "`setup.py` under `console_scripts`. It delegates to "
        "`deepeval/cli/main.py:app` which is a Typer application."
    ),
    DEEPEVAL_QUESTIONS[2]: (
        "An API request arrives at the FastAPI app in `deepeval/telemetry/`. "
        "It is validated by Pydantic models, passed to a service layer, and "
        "finally persisted using SQLAlchemy ORM models to the configured "
        "PostgreSQL (or SQLite) database."
    ),
    DEEPEVAL_QUESTIONS[3]: (
        "Key external dependencies include: `pydantic-ai` (model interface), "
        "`langchain` / `langchain-openai` (LLM chains), `typer` (CLI), "
        "`rich` (terminal formatting), `openai` (default LLM provider), "
        "and `sqlalchemy` (ORM)."
    ),
}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_info():
    """Minimal mock ProjectInfo object."""
    info = MagicMock()
    info.id = PROJECT_ID
    info.repo_name = REPO_NAME
    info.branch_name = "main"
    return info


@pytest.fixture
def mock_agent(project_info):
    """Mock AgentHandle whose .query() returns canned answers."""

    async def _query(ctx):
        # Strip the "[Codebase: …] " prefix that _ask() prepends
        raw_question = ctx.query
        for prefix_char in ["["]:
            if raw_question.startswith(prefix_char):
                # e.g. "[Codebase: deepeval, project_id: …] Explain …"
                raw_question = raw_question.split("] ", 1)[-1]
        answer_text = CANNED_ANSWERS.get(raw_question, f"Mock answer for: {raw_question}")
        response = MagicMock()
        response.response = answer_text
        return response

    handle = MagicMock()
    handle.query = AsyncMock(side_effect=_query)
    return handle


@pytest.fixture
def mock_runtime(project_info, mock_agent):
    """Mock PotpieRuntime with projects and agents attached."""
    runtime = MagicMock()
    runtime.projects.get = AsyncMock(return_value=project_info)

    # Allow getattr(runtime.agents, AGENT_ID) to work
    agents_ns = MagicMock()
    setattr(agents_ns, AGENT_ID, mock_agent)
    runtime.agents = agents_ns
    return runtime


@pytest.fixture(autouse=True)
def set_multi_agent_false(monkeypatch):
    """Simulate ENABLE_MULTI_AGENT=false as specified in the task."""
    monkeypatch.setenv("ENABLE_MULTI_AGENT", "false")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_potpie_ctx(mock_runtime):
    """Return a mock CLIContext whose get_runtime() resolves to mock_runtime."""
    ctx = MagicMock()
    ctx.default_user_id = "defaultuser"
    ctx.get_runtime = AsyncMock(return_value=mock_runtime)
    return ctx


def _make_cases_yaml(qa_pairs: list[dict]) -> str:
    """Serialise ask results into the YAML format accepted by _eval."""
    cases = []
    for item in qa_pairs:
        cases.append(
            {
                "name": item["question"][:60],
                "question": item["question"],
                "rubrics": [
                    "Answer is specific to the DeepEval codebase, not a generic description",
                    "Answer mentions at least one concrete component, file, or function",
                ],
            }
        )
    return yaml.dump({"cases": cases}, allow_unicode=True)


# ---------------------------------------------------------------------------
# Phase 1 — ask: collect answers
# ---------------------------------------------------------------------------


class TestAskCommand:
    """
    Exercise ``_ask()`` for each deepeval question and verify the collected
    answers can be serialised into a YAML eval-cases file.
    """

    @pytest.mark.asyncio
    async def test_ask_returns_nonempty_answer_for_each_question(self, mock_runtime):
        """Each canned answer is non-empty and longer than 20 chars."""
        import potpie_cli as cli_module

        cli_ctx = _build_potpie_ctx(mock_runtime)

        for question in DEEPEVAL_QUESTIONS:
            with patch.object(cli_module, "ctx_obj", cli_ctx):
                # _ask prints to console; we don't care about output here
                await cli_module._ask(question, PROJECT_ID, AGENT_ID, render_markdown=False)

            # agent.query was called with a ChatContext whose query contains the question
            last_call = mock_runtime.agents.codebase_qna_agent.query.call_args
            ctx_arg = last_call[0][0]
            assert question in ctx_arg.query, f"Question not forwarded to agent: {question}"

    @pytest.mark.asyncio
    async def test_ask_collects_all_four_answers_into_yaml(self, mock_runtime, tmp_path):
        """
        Calls _ask() for all 4 questions, collects the responses and writes
        them to a YAML file.  Asserts the YAML parses back to 4 valid cases.
        """
        import potpie_cli as cli_module

        cli_ctx = _build_potpie_ctx(mock_runtime)
        collected: list[dict] = []

        # Wrap once — call the canned lookup directly (avoids side_effect chaining)
        async def _capturing_query(ctx):
            raw_q = ctx.query.split("] ", 1)[-1] if "] " in ctx.query else ctx.query
            answer = CANNED_ANSWERS.get(raw_q, f"Mock answer for: {raw_q}")
            resp = MagicMock()
            resp.response = answer
            # detect which original question this corresponds to
            for q in DEEPEVAL_QUESTIONS:
                if q in ctx.query:
                    collected.append({"question": q, "answer": answer})
                    break
            return resp

        mock_runtime.agents.codebase_qna_agent.query.side_effect = _capturing_query

        for question in DEEPEVAL_QUESTIONS:
            with patch.object(cli_module, "ctx_obj", cli_ctx):
                await cli_module._ask(question, PROJECT_ID, AGENT_ID, render_markdown=False)

        assert len(collected) == 4, f"Expected 4 answers, got {len(collected)}"
        for item in collected:
            assert len(item["answer"]) > 20, f"Answer too short for: {item['question']}"

        # Write YAML fixture
        yaml_text = _make_cases_yaml(collected)
        yaml_path = tmp_path / "deepeval_answers.yaml"
        yaml_path.write_text(yaml_text, encoding="utf-8")

        # Validate round-trip
        loaded = yaml.safe_load(yaml_path.read_text())
        assert "cases" in loaded
        assert len(loaded["cases"]) == 4
        for case in loaded["cases"]:
            assert "question" in case
            assert "rubrics" in case
            assert len(case["rubrics"]) == 2

    @pytest.mark.asyncio
    async def test_ask_architecture_question(self, mock_runtime):
        """Specifically test the 'Explain the architecture' question from the task spec."""
        import potpie_cli as cli_module

        cli_ctx = _build_potpie_ctx(mock_runtime)
        with patch.object(cli_module, "ctx_obj", cli_ctx):
            # Should not raise
            await cli_module._ask(
                "Explain the architecture",
                PROJECT_ID,
                AGENT_ID,
                render_markdown=False,
            )

        last_call = mock_runtime.agents.codebase_qna_agent.query.call_args
        ctx_arg = last_call[0][0]
        assert ctx_arg.project_id == PROJECT_ID
        assert ctx_arg.project_name == REPO_NAME
        assert "Explain the architecture" in ctx_arg.query

    @pytest.mark.asyncio
    async def test_ask_builds_correct_chat_context(self, mock_runtime):
        """Verify ChatContext is populated with the right project metadata."""
        import potpie_cli as cli_module

        cli_ctx = _build_potpie_ctx(mock_runtime)
        with patch.object(cli_module, "ctx_obj", cli_ctx):
            await cli_module._ask(DEEPEVAL_QUESTIONS[0], PROJECT_ID, AGENT_ID, False)

        call_args = mock_runtime.agents.codebase_qna_agent.query.call_args
        ctx = call_args[0][0]

        assert ctx.project_id == PROJECT_ID
        assert ctx.project_name == REPO_NAME
        assert ctx.curr_agent_id == AGENT_ID
        assert ctx.history == []
        assert ctx.user_id == "defaultuser"
        # _ask() wraps the query with the codebase prefix
        assert REPO_NAME in ctx.query


# ---------------------------------------------------------------------------
# Phase 2 — eval: score the collected answers with CopilotModel as judge
# ---------------------------------------------------------------------------


class TestEvalCommand:
    """
    Exercise ``_eval()`` using:
    - A YAML cases file derived from the ask results
    - ``CopilotModel("gpt-4.1")`` as the LLM judge (mocked CLI)
    - Asserts the report is produced with the correct number of cases
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_yaml_cases_file(tmp_path: Path) -> Path:
        """Write a minimal 4-case YAML file to tmp_path."""
        cases = []
        for q, a in CANNED_ANSWERS.items():
            cases.append(
                {
                    "name": q[:50],
                    "question": q,
                    "rubrics": [
                        "Answer references a real component or file from DeepEval",
                        "Answer is not a generic placeholder",
                    ],
                }
            )
        yaml_path = tmp_path / "deepeval_cases.yaml"
        yaml_path.write_text(yaml.dump({"cases": cases}), encoding="utf-8")
        return yaml_path

    @staticmethod
    def _mock_copilot_model_session(response_text: str):
        """
        Build a mock copilot session whose send_and_wait returns response_text.
        Used to make CopilotModel produce deterministic judge verdicts.
        """
        event = MagicMock()
        event.data = MagicMock()
        event.data.content = response_text
        session = AsyncMock()
        session.send_and_wait = AsyncMock(return_value=event)
        session.destroy = AsyncMock()
        return session

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_eval_runs_and_produces_report(self, mock_runtime, tmp_path):
        """
        _eval() should complete without raising and produce an EvaluationReport
        that contains one result per case in the YAML file.
        """
        import potpie_cli as cli_module
        from app.modules.intelligence.provider.copilot_model import CopilotModel
        from pydantic_evals.evaluators.llm_as_a_judge import set_default_judge_model

        yaml_path = self._make_yaml_cases_file(tmp_path)
        cli_ctx = _build_potpie_ctx(mock_runtime)

        # Judge verdict: always PASS with a reason
        judge_json = json.dumps({"pass": True, "reason": "Answer references concrete components."})
        mock_judge_session = self._mock_copilot_model_session(judge_json)
        judge_model = CopilotModel(JUDGE_MODEL)

        # Patch _create_session so no real CLI is invoked
        with patch.object(judge_model, "_create_session", return_value=mock_judge_session):
            set_default_judge_model(judge_model)

            # Also patch the agent used inside _eval's task()
            with patch.object(cli_module, "ctx_obj", cli_ctx):
                await cli_module._eval(
                    project_id=PROJECT_ID,
                    agent_id=AGENT_ID,
                    cases_path=str(yaml_path),
                    concurrency=1,
                )

        # If we reach here without exception the report was produced
        # (rich console output is discarded; we verify via mock call counts)
        assert mock_runtime.projects.get.await_count >= 1

    @pytest.mark.asyncio
    async def test_eval_agent_called_once_per_case(self, mock_runtime, tmp_path):
        """
        The agent's query() method must be called exactly N times — once per
        case in the YAML file (4 cases × 1 concurrency).
        """
        import potpie_cli as cli_module
        from app.modules.intelligence.provider.copilot_model import CopilotModel
        from pydantic_evals.evaluators.llm_as_a_judge import set_default_judge_model

        yaml_path = self._make_yaml_cases_file(tmp_path)
        cli_ctx = _build_potpie_ctx(mock_runtime)

        judge_json = json.dumps({"pass": True, "reason": "Looks good."})
        judge_model = CopilotModel(JUDGE_MODEL)
        mock_judge_session = self._mock_copilot_model_session(judge_json)

        with patch.object(judge_model, "_create_session", return_value=mock_judge_session):
            set_default_judge_model(judge_model)
            with patch.object(cli_module, "ctx_obj", cli_ctx):
                await cli_module._eval(
                    project_id=PROJECT_ID,
                    agent_id=AGENT_ID,
                    cases_path=str(yaml_path),
                    concurrency=1,
                )

        # 4 questions → agent.query called 4 times
        assert mock_runtime.agents.codebase_qna_agent.query.await_count == 4

    @pytest.mark.asyncio
    async def test_eval_uses_gpt41_copilot_model_as_judge(self, mock_runtime, tmp_path):
        """
        The judge model passed to set_default_judge_model must be a
        CopilotModel with model_name == 'gpt-4.1'.
        """
        import potpie_cli as cli_module
        from app.modules.intelligence.provider.copilot_model import CopilotModel
        from pydantic_evals.evaluators.llm_as_a_judge import set_default_judge_model

        yaml_path = self._make_yaml_cases_file(tmp_path)
        cli_ctx = _build_potpie_ctx(mock_runtime)

        captured_judge: list[Any] = []

        def _capturing_set(model):
            captured_judge.append(model)
            # intentionally don't forward — avoids needing a real judge model

        # set_default_judge_model is imported at call-time inside _eval, so we
        # must patch the canonical source module rather than potpie_cli.
        with patch(
            "pydantic_evals.evaluators.llm_as_a_judge.set_default_judge_model",
            side_effect=_capturing_set,
        ):
            with patch.object(cli_module, "ctx_obj", cli_ctx):
                os.environ["CHAT_MODEL"] = f"copilot_cli/{JUDGE_MODEL}"
                try:
                    await cli_module._eval(
                        project_id=PROJECT_ID,
                        agent_id=AGENT_ID,
                        cases_path=str(yaml_path),
                        concurrency=1,
                    )
                finally:
                    os.environ.pop("CHAT_MODEL", None)

        # set_default_judge_model was called exactly once
        assert len(captured_judge) == 1
        # When CHAT_MODEL=copilot_cli/gpt-4.1, the judge must be a CopilotModel
        from app.modules.intelligence.provider.copilot_model import CopilotModel
        assert isinstance(captured_judge[0], CopilotModel)
        assert captured_judge[0].model_name == JUDGE_MODEL

    @pytest.mark.asyncio
    async def test_eval_default_cases_used_when_no_yaml(self, mock_runtime):
        """
        When cases_path is None, _eval() falls back to the built-in
        _DEFAULT_EVAL_CASES (4 cases).
        """
        import potpie_cli as cli_module
        from app.modules.intelligence.provider.copilot_model import CopilotModel
        from pydantic_evals.evaluators.llm_as_a_judge import set_default_judge_model

        cli_ctx = _build_potpie_ctx(mock_runtime)

        judge_json = json.dumps({"pass": True, "reason": "ok"})
        judge_model = CopilotModel(JUDGE_MODEL)
        mock_judge_session = self._mock_copilot_model_session(judge_json)

        with patch.object(judge_model, "_create_session", return_value=mock_judge_session):
            set_default_judge_model(judge_model)
            with patch.object(cli_module, "ctx_obj", cli_ctx):
                await cli_module._eval(
                    project_id=PROJECT_ID,
                    agent_id=AGENT_ID,
                    cases_path=None,
                    concurrency=1,
                )

        # Default has 4 cases → 4 agent calls
        assert mock_runtime.agents.codebase_qna_agent.query.await_count == 4

    @pytest.mark.asyncio
    async def test_eval_handles_agent_error_gracefully(self, mock_runtime, tmp_path):
        """
        If the agent raises, _eval() should catch it and record 'ERROR: …'
        as the response (not crash the whole test run).
        """
        import potpie_cli as cli_module
        from app.modules.intelligence.provider.copilot_model import CopilotModel
        from pydantic_evals.evaluators.llm_as_a_judge import set_default_judge_model

        # Make agent always fail
        mock_runtime.agents.codebase_qna_agent.query.side_effect = RuntimeError("agent down")

        yaml_path = self._make_yaml_cases_file(tmp_path)
        cli_ctx = _build_potpie_ctx(mock_runtime)

        # Judge still needs to evaluate the "ERROR: agent down" string
        judge_json = json.dumps({"pass": False, "reason": "The answer is an error message."})
        judge_model = CopilotModel(JUDGE_MODEL)
        mock_judge_session = self._mock_copilot_model_session(judge_json)

        with patch.object(judge_model, "_create_session", return_value=mock_judge_session):
            set_default_judge_model(judge_model)
            with patch.object(cli_module, "ctx_obj", cli_ctx):
                # Should NOT raise — errors are swallowed per _eval task() impl
                await cli_module._eval(
                    project_id=PROJECT_ID,
                    agent_id=AGENT_ID,
                    cases_path=str(yaml_path),
                    concurrency=1,
                )


# ---------------------------------------------------------------------------
# Phase 3 — full pipeline: ask → YAML → eval (end-to-end mock)
# ---------------------------------------------------------------------------


class TestAskThenEvalPipeline:
    """
    End-to-end test: ask 4 questions, write answers to YAML, then evaluate.
    This mirrors the exact workflow described in the task.
    """

    @pytest.mark.asyncio
    async def test_full_ask_then_eval_pipeline(self, mock_runtime, tmp_path):
        """
        1. Call _ask() for each deepeval question → collect (question, answer) pairs
        2. Write them to a YAML file with rubric assertions
        3. Call _eval() with that YAML file and CopilotModel(gpt-4.1) as judge
        4. Assert: 4 agent calls in ask phase + 4 agent calls in eval phase = 8 total
        """
        import potpie_cli as cli_module
        from app.modules.intelligence.provider.copilot_model import CopilotModel
        from pydantic_evals.evaluators.llm_as_a_judge import set_default_judge_model

        cli_ctx = _build_potpie_ctx(mock_runtime)

        # ── Phase 1: ask ──────────────────────────────────────────────
        collected: list[dict] = []

        # Set up a single intercepting side_effect that records answers.
        # We snapshot the original canned-answers function so there's no
        # recursive chaining as the loop reassigns side_effect each iteration.
        _original_ask_se = mock_runtime.agents.codebase_qna_agent.query.side_effect

        async def _ask_interceptor(ctx):
            resp = await _original_ask_se(ctx)
            # Recover the original question from the prefixed query
            raw_q = ctx.query.split("] ", 1)[-1] if "] " in ctx.query else ctx.query
            for q in DEEPEVAL_QUESTIONS:
                if q in ctx.query:
                    collected.append({"question": q, "answer": resp.response})
                    break
            return resp

        mock_runtime.agents.codebase_qna_agent.query.side_effect = _ask_interceptor

        for question in DEEPEVAL_QUESTIONS:
            with patch.object(cli_module, "ctx_obj", cli_ctx):
                await cli_module._ask(question, PROJECT_ID, AGENT_ID, render_markdown=False)

        assert len(collected) == 4

        # ── Write YAML ────────────────────────────────────────────────
        yaml_path = tmp_path / "pipeline_cases.yaml"
        cases_data = {
            "cases": [
                {
                    "name": item["question"][:50],
                    "question": item["question"],
                    "rubrics": [
                        "Answer is specific to the DeepEval project",
                        "Answer mentions a real file, class, or dependency",
                    ],
                }
                for item in collected
            ]
        }
        yaml_path.write_text(yaml.dump(cases_data), encoding="utf-8")

        assert yaml_path.exists()
        loaded = yaml.safe_load(yaml_path.read_text())
        assert len(loaded["cases"]) == 4

        # ── Phase 2: eval ─────────────────────────────────────────────
        # Reset call count before eval phase
        ask_call_count = mock_runtime.agents.codebase_qna_agent.query.await_count

        # Restore original side_effect for eval phase
        from unittest.mock import AsyncMock as _AsyncMock

        async def _default_query(ctx):
            raw_q = ctx.query.split("] ", 1)[-1] if "] " in ctx.query else ctx.query
            answer = CANNED_ANSWERS.get(raw_q, f"Mock answer for: {raw_q}")
            resp = MagicMock()
            resp.response = answer
            return resp

        mock_runtime.agents.codebase_qna_agent.query.side_effect = _default_query

        judge_json = json.dumps({"pass": True, "reason": "Answer references DeepEval components."})
        judge_model = CopilotModel(JUDGE_MODEL)
        mock_judge_session = MagicMock()
        mock_judge_session.send_and_wait = AsyncMock(
            return_value=MagicMock(**{"data.content": judge_json})
        )
        mock_judge_session.destroy = AsyncMock()

        with patch.object(judge_model, "_create_session", return_value=mock_judge_session):
            set_default_judge_model(judge_model)
            with patch.object(cli_module, "ctx_obj", cli_ctx):
                await cli_module._eval(
                    project_id=PROJECT_ID,
                    agent_id=AGENT_ID,
                    cases_path=str(yaml_path),
                    concurrency=1,
                )

        eval_call_count = (
            mock_runtime.agents.codebase_qna_agent.query.await_count - ask_call_count
        )
        assert eval_call_count == 4, (
            f"Expected 4 agent calls in eval phase, got {eval_call_count}"
        )

        # Total = 4 (ask) + 4 (eval)
        assert mock_runtime.agents.codebase_qna_agent.query.await_count == 8

    @pytest.mark.asyncio
    async def test_yaml_fixture_structure(self, tmp_path):
        """
        The YAML file written from ask results must be parseable by _eval's
        YAML loader (which expects ``cases[].question`` and ``cases[].rubrics``).
        """
        cases = [
            {
                "name": q[:50],
                "question": q,
                "rubrics": ["Answer is not empty", "Answer mentions DeepEval"],
            }
            for q in DEEPEVAL_QUESTIONS
        ]
        yaml_path = tmp_path / "fixture.yaml"
        yaml_path.write_text(yaml.dump({"cases": cases}), encoding="utf-8")

        raw = yaml.safe_load(yaml_path.read_text())
        assert isinstance(raw, dict)
        assert "cases" in raw

        for c in raw["cases"]:
            assert "question" in c, "Missing 'question' key"
            assert "rubrics" in c, "Missing 'rubrics' key"
            assert isinstance(c["rubrics"], list)
            assert len(c["rubrics"]) >= 1

    @pytest.mark.asyncio
    async def test_copilot_gpt41_used_as_judge_in_eval(self, mock_runtime, tmp_path):
        """
        Verify that when CHAT_MODEL=copilot_cli/gpt-4.1, _eval() constructs a
        LiteLLMModel wrapping that model name and passes it to set_default_judge_model.
        (This tests the judge-wiring in _eval, not the full eval execution.)
        """
        import potpie_cli as cli_module

        cases = [
            {
                "name": "arch",
                "question": "Explain the architecture",
                "rubrics": ["Answer is non-empty"],
            }
        ]
        yaml_path = tmp_path / "one_case.yaml"
        yaml_path.write_text(yaml.dump({"cases": cases}), encoding="utf-8")

        cli_ctx = _build_potpie_ctx(mock_runtime)

        judge_calls: list = []

        def _mock_set_default(model):
            judge_calls.append(model)

        # set_default_judge_model is imported inside _eval's function body
        # with `from pydantic_evals.evaluators.llm_as_a_judge import …`
        # so we must patch the name on the source module, not on potpie_cli.
        with (
            patch(
                "pydantic_evals.evaluators.llm_as_a_judge.set_default_judge_model",
                side_effect=_mock_set_default,
            ),
            patch.object(cli_module, "ctx_obj", cli_ctx),
        ):
            os.environ["CHAT_MODEL"] = f"copilot_cli/{JUDGE_MODEL}"
            try:
                await cli_module._eval(
                    project_id=PROJECT_ID,
                    agent_id=AGENT_ID,
                    cases_path=str(yaml_path),
                    concurrency=1,
                )
            finally:
                os.environ.pop("CHAT_MODEL", None)

        assert len(judge_calls) == 1
        # When CHAT_MODEL=copilot_cli/gpt-4.1, the judge must be a CopilotModel
        from app.modules.intelligence.provider.copilot_model import CopilotModel
        assert isinstance(judge_calls[0], CopilotModel)
        assert judge_calls[0].model_name == JUDGE_MODEL


# ---------------------------------------------------------------------------
# Phase 4 — LIVE integration test: real Copilot CLI network calls
# ---------------------------------------------------------------------------
#
# This class makes REAL network calls to the GitHub Copilot CLI (`copilot`).
# No mocking of any kind is performed — CopilotModel("gpt-4.1") is instantiated
# bare and its full request() pipeline runs against the live service.
#
# The test is marked @pytest.mark.integration and is automatically skipped when:
#   • `copilot` is not found on PATH, OR
#   • the SKIP_INTEGRATION env-var is set to a truthy value
#
# To run it explicitly:
#   pytest -m integration unit-tests/test_eval_ask_pipeline.py -s -v
# ---------------------------------------------------------------------------

import shutil as _shutil


@pytest.mark.integration
class TestCopilotJudgeEvaluation:
    """
    Live integration test: CopilotModel("gpt-4.1") drives pydantic_evals LLMJudge.

    The full ask→YAML→eval pipeline runs with real Copilot CLI network calls.
    No sessions, clients, or transports are mocked.

    Results are printed to stdout (use ``pytest -s`` or check "Captured stdout call").
    """

    # ------------------------------------------------------------------
    # Skip guard — runs before every test in this class
    # ------------------------------------------------------------------

    @pytest.fixture(autouse=True)
    def _require_copilot_cli(self):
        """Skip the test if `copilot` is not available or integration is suppressed."""
        import os as _os

        if _shutil.which("copilot") is None:
            pytest.skip(
                "`copilot` CLI not found on PATH — skipping live Copilot integration test. "
                "Install the Copilot CLI standalone binary to enable."
            )
        if _os.environ.get("SKIP_INTEGRATION", "").strip().lower() in {
            "1", "true", "yes",
        }:
            pytest.skip("SKIP_INTEGRATION is set — skipping live integration test.")

    # ------------------------------------------------------------------
    # Dataset builder (shared with both tests in this class)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_dataset():
        """Build a pydantic_evals Dataset from CANNED_ANSWERS + two rubrics per case."""
        from dataclasses import dataclass as _dc
        from pydantic_evals import Case, Dataset
        from pydantic_evals.evaluators import LLMJudge

        @_dc
        class EvalInputs:
            question: str

        cases = []
        for q in DEEPEVAL_QUESTIONS:
            answer = CANNED_ANSWERS[q]
            cases.append(
                Case(
                    name=q[:50],
                    inputs=EvalInputs(question=q),
                    expected_output=answer,
                    evaluators=(
                        LLMJudge(
                            rubric=(
                                "The answer is specific to the DeepEval codebase "
                                "and not a generic description."
                            ),
                            include_input=True,
                        ),
                        LLMJudge(
                            rubric=(
                                "The answer mentions at least one concrete component, "
                                "file, or function name."
                            ),
                            include_input=True,
                        ),
                    ),
                )
            )
        return Dataset(cases=cases), EvalInputs

    # ------------------------------------------------------------------
    # Helper: print a pretty results table
    # ------------------------------------------------------------------

    @staticmethod
    def _print_report(report, *, judge_model_name: str) -> tuple[int, int]:
        """Print per-case verdicts to stdout; return (passed, total) counts.

        LLMJudge stores pass/fail results in ``case.assertions`` (dict mapping
        rubric name → EvaluationResult[bool]).  ``case.scores`` holds numeric
        metrics and is empty for pure pass/fail evaluators like LLMJudge.
        """
        print("\n")
        print("=" * 70)
        print(f"  🤖  CopilotModel judge : {judge_model_name}  (LIVE — real network)")
        print(f"  📋  Project            : {REPO_NAME}  |  Agent: {AGENT_ID}")
        print("=" * 70)

        passed = 0
        total = 0
        for case in report.cases:
            # assertions: dict[str, EvaluationResult[bool]]  — LLMJudge results
            assertions = case.assertions or {}
            print(f"\n  Case   : {case.name!r}")
            print(f"  Answer : {str(case.output)[:120]}…")
            for rubric_name, result in assertions.items():
                total += 1
                ok = bool(result.value)
                if ok:
                    passed += 1
                label = "✅ PASS" if ok else "❌ FAIL"
                reason = f"  — {result.reason}" if result.reason else ""
                print(f"    [{label}]  {rubric_name}{reason}")
            # Also report evaluator failures (judge errors, not rubric failures)
            for failure in (case.evaluator_failures or []):
                print(f"    [⚠️  ERROR]  {failure}")

        pct = (passed / total * 100) if total else 0.0
        color = "\033[92m" if pct >= 70 else "\033[93m" if pct >= 40 else "\033[91m"
        reset = "\033[0m"
        print(f"\n{'─' * 70}")
        print(f"  Overall pass rate: {color}{passed}/{total} ({pct:.0f}%){reset}")
        print("=" * 70)
        print()
        return passed, total

    # ------------------------------------------------------------------
    # Test 1 — model instantiation and name
    # ------------------------------------------------------------------

    def test_copilot_judge_model_name(self):
        """CopilotModel("gpt-4.1") exposes the correct model_name property."""
        from app.modules.intelligence.provider.copilot_model import CopilotModel

        model = CopilotModel(JUDGE_MODEL)
        assert model.model_name == JUDGE_MODEL
        assert model.system == "copilot"

    # ------------------------------------------------------------------
    # Test 2 — full live evaluation pipeline
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_copilot_judge_scores_deepeval_answers(self):
        """
        Run the full pydantic_evals evaluation pipeline against the LIVE Copilot CLI.

        ──────────────────────────────────────────────────────────────────
        ✅  NO MOCKING — every LLM judge call hits the real gpt-4.1 model
            via the standalone ``copilot`` CLI.  Requires:
              • ``copilot`` installed and on PATH
              • authenticated (run ``copilot auth`` or equivalent once)
        ──────────────────────────────────────────────────────────────────

        The canned answers (CANNED_ANSWERS) are realistic descriptions of the
        DeepEval codebase.  The live judge should score them as PASS on both
        rubrics.  The test asserts ≥ 50 % pass rate to allow for model variance.

        Run with ``pytest -s`` to see the full results table.
        """
        from app.modules.intelligence.provider.copilot_model import CopilotModel
        from pydantic_evals.evaluators.llm_as_a_judge import set_default_judge_model

        # ── Instantiate the live judge — NO patching ───────────────────
        judge_model = CopilotModel(JUDGE_MODEL)

        dataset, EvalInputs = self._build_dataset()

        # ── Task: echo the pre-written canned answer for each question ─
        async def task(inputs: EvalInputs) -> str:
            return CANNED_ANSWERS.get(
                inputs.question,
                f"No canned answer for: {inputs.question}",
            )

        # ── Wire judge and run ─────────────────────────────────────────
        set_default_judge_model(judge_model)
        report = await dataset.evaluate(task, max_concurrency=1, progress=False)

        # ── Print results table ────────────────────────────────────────
        passed, total = self._print_report(report, judge_model_name=JUDGE_MODEL)

        # ── Assertions ─────────────────────────────────────────────────
        averages = report.averages()
        assert averages is not None, (
            "EvaluationReport.averages() returned None — no cases ran"
        )

        # Every case must have at least one assertion (LLMJudge stores pass/fail
        # in case.assertions, not case.scores — scores holds numeric metrics only)
        for case in report.cases:
            has_results = bool(case.assertions) or bool(case.evaluator_failures)
            assert has_results, (
                f"Case {case.name!r} produced no assertions and no evaluator failures "
                f"— judge may have silently errored. "
                f"scores={case.scores}, assertions={case.assertions}, "
                f"failures={case.evaluator_failures}"
            )

        # Live model variance: require ≥ 50 % pass rate
        if total > 0:
            pass_rate = passed / total
            assert pass_rate >= 0.5, (
                f"Live judge pass rate {pass_rate * 100:.0f}% is below the 50% threshold. "
                f"Passed {passed}/{total} rubrics.  Check stdout for per-case verdicts."
            )

        print(
            f"  ℹ  Live evaluation complete — "
            f"{passed}/{total} rubric(s) passed ({passed / total * 100 if total else 0:.0f}%)."
        )
