"""
Unit tests for StreamingLocalSkillScriptExecutor.run().

Validates: Design §Testing Strategy — Unit Testing; Property 1
"""

import asyncio
import sys
import textwrap

import pytest

from pydantic_ai_skills import SkillScript
from potpie_cli import StreamingLocalSkillScriptExecutor


def _run_sync(coro):
    return asyncio.run(coro)


def _make_executor(callback):
    return StreamingLocalSkillScriptExecutor(
        callback=callback,
        python_executable=sys.executable,
        timeout=10,
    )


def test_callback_receives_all_stdout_lines(tmp_path):
    """
    Spawn a real subprocess that prints 3 known lines; assert callback called
    exactly 3 times with correct content, and returned string contains all lines.

    Validates: Design §Testing Strategy — Unit Testing; Property 1
    """
    script_file = tmp_path / "print_lines.py"
    script_file.write_text(textwrap.dedent("""\
        print("line1")
        print("line2")
        print("line3")
    """))

    script = SkillScript(name="test_script", uri=str(script_file))

    received_lines = []
    executor = _make_executor(callback=received_lines.append)

    result = _run_sync(executor.run(script))

    # Callback called exactly 3 times
    assert len(received_lines) == 3, f"Expected 3 callback calls, got {len(received_lines)}: {received_lines}"

    # Each call had the correct content
    assert received_lines[0] == "line1"
    assert received_lines[1] == "line2"
    assert received_lines[2] == "line3"

    # Returned string contains all lines
    assert "line1" in result
    assert "line2" in result
    assert "line3" in result


def test_stderr_lines_have_prefix(tmp_path):
    """
    Spawn a subprocess that writes to stderr; assert lines in returned string
    are prefixed '[stderr] ' and the callback received lines with that prefix.

    Validates: Design §Testing Strategy — Unit Testing
    """
    script_file = tmp_path / "write_stderr.py"
    script_file.write_text(
        "import sys\nsys.stderr.write('err_line\\n')\n"
    )

    script = SkillScript(name="test_stderr", uri=str(script_file))

    received_lines = []
    executor = _make_executor(callback=received_lines.append)

    result = _run_sync(executor.run(script))

    # Returned string contains the prefixed stderr line
    assert "[stderr] err_line" in result

    # Callback received a line with the [stderr] prefix
    assert any(line.startswith("[stderr] ") for line in received_lines), (
        f"No [stderr] prefixed line in callback calls: {received_lines}"
    )
    assert "[stderr] err_line" in received_lines


def test_nonzero_exit_code_appends_suffix(tmp_path):
    """
    Spawn a subprocess that exits with code 1; assert returned string contains
    'Script exited with code 1'.

    Validates: Design §Error Handling — Non-zero exit code
    """
    script_file = tmp_path / "exit_one.py"
    script_file.write_text("import sys\nsys.exit(1)\n")

    script = SkillScript(name="test_exit_one", uri=str(script_file))

    received_lines = []
    executor = _make_executor(callback=received_lines.append)

    result = _run_sync(executor.run(script))

    assert "Script exited with code 1" in result, (
        f"Expected exit-code suffix in result, got: {repr(result)}"
    )


def test_timeout_raises_error(tmp_path):
    """
    Spawn a subprocess that sleeps longer than the timeout; assert
    SkillScriptExecutionError is raised and message contains 'timed out'.

    Validates: Design §Error Handling — Timeout during streaming
    """
    from pydantic_ai_skills.exceptions import SkillScriptExecutionError

    script_file = tmp_path / "sleep_forever.py"
    script_file.write_text("import time; time.sleep(60)\n")

    script = SkillScript(name="test_timeout", uri=str(script_file))

    executor = StreamingLocalSkillScriptExecutor(
        callback=lambda line: None,
        python_executable=sys.executable,
        timeout=1,
    )

    with pytest.raises(SkillScriptExecutionError) as exc_info:
        _run_sync(executor.run(script))

    assert "timed out" in str(exc_info.value).lower(), (
        f"Expected 'timed out' in error message, got: {str(exc_info.value)}"
    )


def test_bad_executable_raises_error(tmp_path):
    """
    Pass a non-existent python executable; assert SkillScriptExecutionError is raised.

    Validates: Design §Error Handling — OSError on subprocess launch
    """
    from pydantic_ai_skills.exceptions import SkillScriptExecutionError

    script_file = tmp_path / "any_script.py"
    script_file.write_text("print('hello')\n")

    script = SkillScript(name="test_bad_exec", uri=str(script_file))

    executor = StreamingLocalSkillScriptExecutor(
        callback=lambda line: None,
        python_executable="/nonexistent/python",
        timeout=10,
    )

    with pytest.raises(SkillScriptExecutionError):
        _run_sync(executor.run(script))
