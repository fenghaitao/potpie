"""
conftest.py for qna_evaluator unit tests.

Stubs all heavy dependencies (pydantic_evals, pydantic_ai, app provider modules)
so the evaluator modules can be imported without a live LLM, database, or network.

All LLM calls are monkey-patched at the call site by individual tests.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest


def _stub_module(name: str, **attrs) -> types.ModuleType:
    """Insert a lightweight stub only if the real module is not already loaded."""
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


@pytest.fixture(scope="session", autouse=True)
def _qna_eval_stubs():
    """
    Register stubs for all heavy dependencies used by qna_evaluator.py.

    Stubbed modules
    ---------------
    - app.modules.intelligence.provider.copilot_model   (CopilotModel)
    - app.modules.intelligence.provider.litellm_model   (LiteLLMModel)
    - pydantic_evals                                    (Case, Dataset)
    - pydantic_evals.evaluators                         (LLMJudge)
    - pydantic_evals.evaluators.llm_as_a_judge          (set_default_judge_model,
                                                          _default_judge_model)
    - pydantic_ai                                       (Agent)
    """
    # Provider stubs --------------------------------------------------------
    _stub_module(
        "app.modules.intelligence.provider.copilot_model",
        CopilotModel=MagicMock(return_value=MagicMock()),
    )
    _stub_module(
        "app.modules.intelligence.provider.litellm_model",
        LiteLLMModel=MagicMock(return_value=MagicMock()),
    )
    # Ensure parent package stubs exist so attribute lookup doesn't fail
    for parent in [
        "app",
        "app.modules",
        "app.modules.intelligence",
        "app.modules.intelligence.provider",
    ]:
        _stub_module(parent)

    # pydantic_evals stubs --------------------------------------------------
    # Case and Dataset are used inside _run_rubrics; we stub them so that
    # LLMJudge rubric-based tests can be mocked without the real package.
    MockCase = MagicMock(name="Case")
    MockDataset = MagicMock(name="Dataset")

    pe_mod = _stub_module("pydantic_evals", Case=MockCase, Dataset=MockDataset)

    MockLLMJudge = MagicMock(name="LLMJudge")
    pe_eval_mod = _stub_module("pydantic_evals.evaluators", LLMJudge=MockLLMJudge)
    pe_eval_mod.LLMJudge = MockLLMJudge

    # The judge-model singleton referenced by _call_llm
    _stub_module(
        "pydantic_evals.evaluators.llm_as_a_judge",
        set_default_judge_model=MagicMock(),
        _default_judge_model=MagicMock(),
    )

    # pydantic_ai stub -------------------------------------------------------
    # Agent is used in _call_llm; individual tests patch it via monkeypatch.
    MockAgent = MagicMock(name="Agent")
    _stub_module("pydantic_ai", Agent=MockAgent)

    yield
