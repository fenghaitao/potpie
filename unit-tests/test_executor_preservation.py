"""
Preservation property tests for LocalSkillScriptExecutor.

These tests verify that existing error-handling and output behavior is UNCHANGED
for non-deadlock inputs (scripts that do NOT call asyncio.run(...) from within
an already-running event loop).

All tests MUST PASS on UNFIXED code — they establish the baseline behavior that
the fix in Task 3 must preserve.

Observations on unfixed code (confirmed before writing these tests):
  - exit 0 + stdout "hello"  → output == 'hello'
  - exit 1                   → output contains 'Script exited with code 1'
  - stderr "err msg"         → output contains 'Stderr:\nerr msg'
  - sleep past timeout       → SkillScriptExecutionError("Script '...' timed out after N seconds")
  - non-existent path        → SkillScriptExecutionError("Failed to execute script '...': ...")
                               with __cause__ being an OSError

Validates: Requirements 3.1, 3.2, 3.3, 3.4
"""

import asyncio
import sys
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from pydantic_ai_skills import SkillScript
from pydantic_ai_skills.exceptions import SkillScriptExecutionError
from pydantic_ai_skills.local import LocalSkillScriptExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_script(tmp_path: Path, body: str, name: str = "test_script") -> SkillScript:
    """Write *body* to a temp .py file and return a SkillScript pointing at it."""
    script_file = tmp_path / f"{name}.py"
    script_file.write_text(body)
    return SkillScript(name=name, uri=str(script_file))


def _run_sync(coro):
    """Run a coroutine synchronously (no outer event loop — safe for anyio.run_process)."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Manual observation unit tests (confirm exact format strings)
# ---------------------------------------------------------------------------

def test_exit_zero_stdout_no_exit_code_suffix(tmp_path):
    """Script exiting 0 with stdout 'hello' → output contains 'hello', no exit-code suffix."""
    script = _make_script(tmp_path, 'print("hello")')
    executor = LocalSkillScriptExecutor(python_executable=sys.executable, timeout=10)
    result = _run_sync(executor.run(script))
    assert "hello" in result
    assert "Script exited with code" not in result


def test_exit_nonzero_output_contains_exit_code(tmp_path):
    """Script exiting 1 → output contains 'Script exited with code 1'."""
    script = _make_script(tmp_path, "import sys; sys.exit(1)")
    executor = LocalSkillScriptExecutor(python_executable=sys.executable, timeout=10)
    result = _run_sync(executor.run(script))
    assert "Script exited with code 1" in result


def test_stderr_output_contains_stderr_section(tmp_path):
    """Script writing to stderr → output contains 'Stderr:' section."""
    script = _make_script(
        tmp_path,
        'import sys; sys.stderr.write("err msg"); sys.stderr.flush()',
    )
    executor = LocalSkillScriptExecutor(python_executable=sys.executable, timeout=10)
    result = _run_sync(executor.run(script))
    assert "Stderr:" in result
    assert "err msg" in result


def test_timeout_raises_skill_script_execution_error(tmp_path):
    """Script sleeping past timeout → SkillScriptExecutionError raised with timeout message."""
    script = _make_script(tmp_path, "import time; time.sleep(60)")
    executor = LocalSkillScriptExecutor(python_executable=sys.executable, timeout=1)
    with pytest.raises(SkillScriptExecutionError) as exc_info:
        _run_sync(executor.run(script))
    assert "timed out" in str(exc_info.value).lower()
    assert "1 seconds" in str(exc_info.value)


def test_nonexistent_script_raises_skill_script_execution_error():
    """Non-existent script path → SkillScriptExecutionError wrapping OSError."""
    script = SkillScript(name="missing", uri="/nonexistent/path/no_such_script.py")
    executor = LocalSkillScriptExecutor(python_executable=sys.executable, timeout=10)
    with pytest.raises(SkillScriptExecutionError) as exc_info:
        _run_sync(executor.run(script))
    assert "Failed to execute script" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, OSError)


# ---------------------------------------------------------------------------
# Property-based tests
# ---------------------------------------------------------------------------

@given(exit_code=st.integers(min_value=1, max_value=255))
@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
def test_property_random_exit_codes_always_contain_exit_code_string(exit_code):
    """
    **Validates: Requirements 3.2**

    For any non-zero exit code 1–255, the output always contains
    'Script exited with code N'.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        script = _make_script(tmp_path, f"import sys; sys.exit({exit_code})")
        executor = LocalSkillScriptExecutor(python_executable=sys.executable, timeout=10)
        result = _run_sync(executor.run(script))
        assert f"Script exited with code {exit_code}" in result


@given(
    stdout_text=st.text(
        # Restrict to printable ASCII (0x21–0x7e) to avoid whitespace characters
        # that output.strip() would remove (pre-existing executor behavior).
        alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E),
        min_size=1,
        max_size=200,
    ),
    stderr_text=st.text(
        alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E),
        min_size=1,
        max_size=200,
    ),
)
@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
def test_property_stdout_and_stderr_both_appear_in_output(stdout_text, stderr_text):
    """
    **Validates: Requirements 3.1, 3.2**

    For any printable ASCII stdout and stderr text, both appear decoded in the
    combined output. The output also contains a 'Stderr:' section header.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # Write the texts to a data file so the script can read them without escaping
        data_file = tmp_path / "data.txt"
        data_file.write_text(
            repr(stdout_text) + "\n" + repr(stderr_text) + "\n",
            encoding="utf-8",
        )

        script_body = (
            "import sys\n"
            f"data = open({repr(str(data_file))}, encoding='utf-8').read().splitlines()\n"
            "stdout_text = eval(data[0])\n"
            "stderr_text = eval(data[1])\n"
            "sys.stdout.write(stdout_text)\n"
            "sys.stdout.flush()\n"
            "sys.stderr.write(stderr_text)\n"
            "sys.stderr.flush()\n"
        )

        script = _make_script(tmp_path, script_body)
        executor = LocalSkillScriptExecutor(python_executable=sys.executable, timeout=10)
        result = _run_sync(executor.run(script))

        assert "Stderr:" in result
        # The decoded stdout and stderr should appear in the combined output
        assert stdout_text in result
        assert stderr_text in result


@given(timeout_seconds=st.integers(min_value=1, max_value=3))
@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=15000)
def test_property_timeout_raises_skill_script_execution_error(timeout_seconds):
    """
    **Validates: Requirements 3.3**

    For any timeout value, a script sleeping longer than the timeout raises
    SkillScriptExecutionError with a message containing 'timed out' and the
    timeout duration.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        script = _make_script(tmp_path, "import time; time.sleep(60)")
        executor = LocalSkillScriptExecutor(python_executable=sys.executable, timeout=timeout_seconds)
        with pytest.raises(SkillScriptExecutionError) as exc_info:
            _run_sync(executor.run(script))
        error_msg = str(exc_info.value)
        assert "timed out" in error_msg.lower()
        assert f"{timeout_seconds} seconds" in error_msg


@given(script_name=st.text(
    # Exclude surrogates, null bytes (invalid in paths), and path separators
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="/\\:*?\"<>|\x00"),
    min_size=1,
    max_size=50,
))
@settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_oserror_raises_skill_script_execution_error(script_name):
    """
    **Validates: Requirements 3.4**

    For any script name pointing to a non-existent path, SkillScriptExecutionError
    is raised wrapping the underlying OSError.
    """
    script = SkillScript(name=script_name, uri=f"/nonexistent/path/{script_name}.py")
    executor = LocalSkillScriptExecutor(python_executable=sys.executable, timeout=10)
    with pytest.raises(SkillScriptExecutionError) as exc_info:
        _run_sync(executor.run(script))
    assert "Failed to execute script" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, OSError)
