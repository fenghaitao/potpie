"""
Unit tests for the _eval() verbose branch.

Validates: Design §Testing Strategy — Unit Testing
           Design §_eval / _wiki call sites
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

import pytest

from potpie_cli import StreamingLocalSkillScriptExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_sync(coro):
    return asyncio.run(coro)


def _make_eval_patches(captured: dict):
    """
    Return a context-manager stack that patches all external dependencies of
    _eval() so the function can run without real infrastructure.

    captured["executor"] is set to the script_executor kwarg passed to
    SkillsDirectory when the patched constructor is called.
    """
    fake_skills_dir = MagicMock()
    fake_toolset = MagicMock()
    fake_toolset.get_instructions = AsyncMock(return_value=None)

    fake_node_end = MagicMock()
    fake_node_end.data.output = "result"

    async def _async_iter():
        yield fake_node_end

    fake_agent_run = MagicMock()
    fake_agent_run.__aenter__ = AsyncMock(return_value=fake_agent_run)
    fake_agent_run.__aexit__ = AsyncMock(return_value=False)
    fake_agent_run.__aiter__ = lambda self: _async_iter().__aiter__()

    fake_agent = MagicMock()
    fake_agent.iter.return_value = fake_agent_run
    fake_agent.is_call_tools_node.return_value = False
    fake_agent.is_end_node.return_value = True
    fake_agent.instructions = lambda fn: fn  # decorator no-op

    def capture_skills_directory(*args, **kwargs):
        captured["executor"] = kwargs.get("script_executor")
        return fake_skills_dir

    patches = [
        # Patch SkillsDirectory to capture the script_executor kwarg
        patch(
            "pydantic_ai_skills.directory.SkillsDirectory",
            side_effect=capture_skills_directory,
        ),
        # Patch SkillsToolset
        patch("pydantic_ai_skills.SkillsToolset", return_value=fake_toolset),
        # Patch Agent
        patch("pydantic_ai.Agent", return_value=fake_agent),
        # Patch LiteLLMModel
        patch(
            "app.modules.intelligence.provider.litellm_model.LiteLLMModel",
            return_value=MagicMock(),
        ),
        # Patch prompt file I/O so no real file is needed
        patch("builtins.open", mock_open(read_data="evaluate something")),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.read_text", return_value="evaluate something"),
        patch("pathlib.Path.is_absolute", return_value=True),
    ]
    return patches


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_verbose_true_uses_streaming_executor():
    """
    When verbose=True, _eval() passes a StreamingLocalSkillScriptExecutor
    instance as script_executor to SkillsDirectory.
    """
    captured: dict = {}
    patches = _make_eval_patches(captured)

    from potpie_cli import _eval

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
        _run_sync(_eval(
            prompt_path="/fake/prompt.txt",
            skills_dir="/fake/skills",
            timeout=30,
            verbose=True,
        ))

    assert "executor" in captured, "SkillsDirectory was not called"
    assert isinstance(captured["executor"], StreamingLocalSkillScriptExecutor), (
        f"Expected StreamingLocalSkillScriptExecutor, got {type(captured['executor'])}"
    )


def test_verbose_false_uses_plain_executor():
    """
    When verbose=False, _eval() passes a plain LocalSkillScriptExecutor
    instance (not StreamingLocalSkillScriptExecutor) as script_executor to
    SkillsDirectory.
    """
    from pydantic_ai_skills.local import LocalSkillScriptExecutor

    captured: dict = {}
    patches = _make_eval_patches(captured)

    from potpie_cli import _eval

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
        _run_sync(_eval(
            prompt_path="/fake/prompt.txt",
            skills_dir="/fake/skills",
            timeout=30,
            verbose=False,
        ))

    assert "executor" in captured, "SkillsDirectory was not called"
    executor = captured["executor"]
    assert isinstance(executor, LocalSkillScriptExecutor), (
        f"Expected LocalSkillScriptExecutor, got {type(executor)}"
    )
    assert not isinstance(executor, StreamingLocalSkillScriptExecutor), (
        "verbose=False should NOT use StreamingLocalSkillScriptExecutor"
    )


def test_verbose_true_streaming_executor_has_callback():
    """
    When verbose=True, the StreamingLocalSkillScriptExecutor passed to
    SkillsDirectory has a non-None _callback attribute.
    """
    captured: dict = {}
    patches = _make_eval_patches(captured)

    from potpie_cli import _eval

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
        _run_sync(_eval(
            prompt_path="/fake/prompt.txt",
            skills_dir="/fake/skills",
            timeout=30,
            verbose=True,
        ))

    executor = captured.get("executor")
    assert executor is not None
    assert callable(executor._callback), "StreamingLocalSkillScriptExecutor._callback must be callable"


def test_verbose_true_executor_timeout_matches():
    """
    The timeout passed to _eval() is forwarded to the executor.
    """
    captured: dict = {}
    patches = _make_eval_patches(captured)

    from potpie_cli import _eval

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
        _run_sync(_eval(
            prompt_path="/fake/prompt.txt",
            skills_dir="/fake/skills",
            timeout=120,
            verbose=True,
        ))

    executor = captured.get("executor")
    assert executor is not None
    assert executor.timeout == 120


def test_verbose_false_executor_timeout_matches():
    """
    The timeout passed to _eval() is forwarded to the plain executor too.
    """
    captured: dict = {}
    patches = _make_eval_patches(captured)

    from potpie_cli import _eval

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
        _run_sync(_eval(
            prompt_path="/fake/prompt.txt",
            skills_dir="/fake/skills",
            timeout=90,
            verbose=False,
        ))

    executor = captured.get("executor")
    assert executor is not None
    assert executor.timeout == 90
