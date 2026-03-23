"""
conftest.py for wiki-evaluator unit tests.

Provides a session-scoped autouse fixture that stubs the bare minimum of
heavy dependencies so the skill modules can be imported without a live
database, Redis, or network connection.

NOTE: potpie / potpie_cli stubs are NOT applied here — those are managed
      per-test inside TestEvaluateWikiCLICommand._fresh_cli() to avoid
      polluting sys.modules for test_eval_ask_pipeline.py which needs the
      real potpie package.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest


def _stub_module(name: str, **attrs) -> types.ModuleType:
    """Insert a stub only if the module isn't already loaded."""
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


@pytest.fixture(scope="session", autouse=True)
def _wiki_eval_stubs():
    """
    Register stubs for heavy dependencies needed by the skill modules.
    Runs once per test session, before any wiki-evaluator test.

    The new wiki_evaluator.py uses direct LLM calls (no pydantic_evals),
    so we only need to stub the provider modules used by graph_rubric_generator.

    We do NOT stub 'potpie' here — see TestEvaluateWikiCLICommand._fresh_cli().
    """
    # Provider stubs (used by graph_rubric_generator._llm_generate)
    _stub_module("app.modules.intelligence.provider.copilot_model",
                 CopilotModel=MagicMock(return_value=MagicMock()))
    _stub_module("app.modules.intelligence.provider.litellm_model",
                 LiteLLMModel=MagicMock(return_value=MagicMock()))

    yield
