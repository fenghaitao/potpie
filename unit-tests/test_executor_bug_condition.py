"""
Bug condition exploration test for LocalSkillScriptExecutor.

This test MUST FAIL on unfixed code (with anyio.run_process still in place).
Failure confirms the deadlock bug exists:
  - LocalSkillScriptExecutor.run() is awaited inside asyncio.run(...)
  - The child script calls asyncio.run(...) internally
  - anyio.run_process blocks the outer event loop while the child tries to start its own loop
  - Result: deadlock — neither side makes progress, no output, no error, hangs forever

Counterexample documented:
  LocalSkillScriptExecutor.run(<script calling asyncio.run(...)>)
  never returns when called from asyncio.run(...)

Requirements: 1.1, 1.2
"""

import asyncio
import sys
import tempfile
from pathlib import Path

import pytest

from pydantic_ai_skills.local import LocalSkillScriptExecutor
from pydantic_ai_skills import SkillScript


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_script(tmp_path: Path, body: str) -> SkillScript:
    """Write *body* to a temp .py file and return a SkillScript pointing at it."""
    script_file = tmp_path / "test_script.py"
    script_file.write_text(body)
    return SkillScript(name="test_script", uri=str(script_file))


# ---------------------------------------------------------------------------
# Bug condition exploration test
#
# Validates: Requirements 1.1, 1.2
#
# This test is EXPECTED TO FAIL on unfixed code (hang / timeout).
# When it fails, that IS the success case for the exploration phase —
# it confirms the deadlock root cause.
# ---------------------------------------------------------------------------

def test_executor_completes_when_called_from_running_event_loop(tmp_path):
    """
    Call LocalSkillScriptExecutor.run() from inside asyncio.run(...) with a
    minimal script that itself calls asyncio.run(asyncio.sleep(0)).

    Expected on UNFIXED code: hangs / times out (confirms deadlock).
    Expected on FIXED code:   completes within 5 s and returns output containing "ok".

    Counterexample (unfixed):
        LocalSkillScriptExecutor.run(<script calling asyncio.run(...)>)
        never returns when called from asyncio.run(...)
    """
    script_body = (
        "import asyncio\n"
        "asyncio.run(asyncio.sleep(0))\n"
        "print('ok')\n"
    )
    skill_script = _make_script(tmp_path, script_body)
    executor = LocalSkillScriptExecutor(
        python_executable=sys.executable,
        timeout=5,
    )

    async def _run():
        # Wrap with asyncio.wait_for so the test itself doesn't hang forever.
        # On unfixed code, anyio.run_process deadlocks and asyncio.wait_for
        # raises asyncio.TimeoutError after 8 seconds.
        return await asyncio.wait_for(executor.run(skill_script, args=None), timeout=8)

    result = asyncio.run(_run())

    assert "ok" in result, f"Expected 'ok' in output, got: {result!r}"
