"""
Property-based tests for StreamingLocalSkillScriptExecutor.

Validates: Design §Correctness Properties
"""

import asyncio
import sys
import tempfile
from pathlib import Path

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from pydantic_ai_skills import SkillScript
from pydantic_ai_skills.local import LocalSkillScriptExecutor
from potpie_cli import StreamingLocalSkillScriptExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_sync(coro):
    return asyncio.run(coro)


def _make_script(tmp_dir: str, body: str, name: str = "test_script") -> SkillScript:
    script_file = Path(tmp_dir) / f"{name}.py"
    script_file.write_text(body)
    return SkillScript(name=name, uri=str(script_file))


# ---------------------------------------------------------------------------
# Property 1 — Streaming completeness
# ---------------------------------------------------------------------------

@given(
    lines=st.lists(
        st.text(
            # Restrict to printable ASCII (0x21–0x7e) to avoid control characters
            # that output.strip() would remove (pre-existing executor behavior).
            # The property is about "non-empty lines" that survive the executor's
            # strip() call — control-character-only lines are not meaningful output.
            alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E),
            min_size=1,
            max_size=80,
        ),
        min_size=1,
        max_size=20,
    )
)
@settings(
    max_examples=20,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_property1_streaming_completeness(lines):
    """
    **Validates: Design §Correctness Properties — Property 1**

    For any invocation where the script produces N non-empty lines on stdout,
    the callback is called exactly N times and the returned string contains
    all N lines.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Write lines to a data file so the script can read them without escaping issues
        data_file = Path(tmp_dir) / "lines.txt"
        data_file.write_text("\n".join(repr(line) for line in lines), encoding="utf-8")

        script_body = (
            "import sys\n"
            f"data = open({repr(str(data_file))}, encoding='utf-8').read().splitlines()\n"
            "for encoded_line in data:\n"
            "    print(eval(encoded_line))\n"
        )

        script = _make_script(tmp_dir, script_body)

        received_lines = []
        executor = StreamingLocalSkillScriptExecutor(
            callback=received_lines.append,
            python_executable=sys.executable,
            timeout=15,
        )

        result = _run_sync(executor.run(script))

        # Callback called exactly once per line
        assert len(received_lines) == len(lines), (
            f"Expected {len(lines)} callback calls, got {len(received_lines)}. "
            f"lines={lines!r}, received={received_lines!r}"
        )

        # Returned string contains all lines
        for line in lines:
            assert line in result, (
                f"Line {line!r} not found in result {result!r}"
            )


# ---------------------------------------------------------------------------
# Property 2 — Non-verbose equivalence
# ---------------------------------------------------------------------------

# Printable ASCII alphabet (same as Property 1)
_PRINTABLE_ASCII = st.characters(min_codepoint=0x21, max_codepoint=0x7E)
_LINE = st.text(alphabet=_PRINTABLE_ASCII, min_size=1, max_size=80)
_LINES = st.lists(_LINE, min_size=0, max_size=10)


@given(
    exit_code=st.integers(min_value=0, max_value=1),
    stdout_lines=_LINES,
    stderr_lines=_LINES,
)
@settings(
    max_examples=15,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_property2_nonverbose_equivalence(exit_code, stdout_lines, stderr_lines):
    """
    **Validates: Design §Correctness Properties — Property 2**

    For any invocation of LocalSkillScriptExecutor.run(script, args) (no callback),
    the returned string is identical (in content) to the string returned by the
    streaming path for the same script and args.

    Because the two executors format stderr differently (buffered: block at end;
    streaming: per-line prefix), we compare by checking that every individual
    stdout/stderr line appears in both outputs rather than requiring byte equality.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Write lines to data files to avoid shell-escaping issues
        stdout_data = Path(tmp_dir) / "stdout_lines.txt"
        stderr_data = Path(tmp_dir) / "stderr_lines.txt"
        stdout_data.write_text("\n".join(repr(l) for l in stdout_lines), encoding="utf-8")
        stderr_data.write_text("\n".join(repr(l) for l in stderr_lines), encoding="utf-8")

        script_body = (
            "import sys\n"
            f"stdout_data = open({repr(str(stdout_data))}, encoding='utf-8').read().splitlines()\n"
            f"stderr_data = open({repr(str(stderr_data))}, encoding='utf-8').read().splitlines()\n"
            "for encoded in stdout_data:\n"
            "    if encoded:\n"
            "        print(eval(encoded))\n"
            "for encoded in stderr_data:\n"
            "    if encoded:\n"
            "        print(eval(encoded), file=sys.stderr)\n"
            f"sys.exit({exit_code})\n"
        )

        script = _make_script(tmp_dir, script_body, name="prop2_script")

        # --- Buffered path ---
        buffered_executor = LocalSkillScriptExecutor(
            python_executable=sys.executable,
            timeout=15,
        )
        buffered_result = _run_sync(buffered_executor.run(script))

        # --- Streaming path ---
        streaming_executor = StreamingLocalSkillScriptExecutor(
            callback=lambda _: None,  # discard; we only care about the return value
            python_executable=sys.executable,
            timeout=15,
        )
        streaming_result = _run_sync(streaming_executor.run(script))

        # Both paths must contain all stdout lines
        for line in stdout_lines:
            assert line in buffered_result, (
                f"stdout line {line!r} missing from buffered result:\n{buffered_result!r}"
            )
            assert line in streaming_result, (
                f"stdout line {line!r} missing from streaming result:\n{streaming_result!r}"
            )

        # Both paths must contain all stderr lines
        for line in stderr_lines:
            assert line in buffered_result, (
                f"stderr line {line!r} missing from buffered result:\n{buffered_result!r}"
            )
            assert line in streaming_result, (
                f"stderr line {line!r} missing from streaming result:\n{streaming_result!r}"
            )

        # Both paths must agree on exit-code suffix presence
        exit_suffix = f"Script exited with code {exit_code}"
        if exit_code != 0:
            assert exit_suffix in buffered_result, (
                f"Exit suffix missing from buffered result:\n{buffered_result!r}"
            )
            assert exit_suffix in streaming_result, (
                f"Exit suffix missing from streaming result:\n{streaming_result!r}"
            )
        else:
            assert exit_suffix not in buffered_result, (
                f"Unexpected exit suffix in buffered result:\n{buffered_result!r}"
            )
            assert exit_suffix not in streaming_result, (
                f"Unexpected exit suffix in streaming result:\n{streaming_result!r}"
            )


# ---------------------------------------------------------------------------
# Property 3 — Error handling preservation
# ---------------------------------------------------------------------------

@given(exit_code=st.integers(min_value=1, max_value=127))
@settings(
    max_examples=10,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
def test_property3_error_handling_preservation(exit_code):
    """
    **Validates: Design §Correctness Properties — Property 3**

    For any non-zero exit code (1–127), both the buffered path and the streaming
    path must include "Script exited with code N" in the returned string.
    """
    import pytest
    from pydantic_ai_skills.exceptions import SkillScriptExecutionError

    with tempfile.TemporaryDirectory() as tmp_dir:
        script_body = f"import sys; sys.exit({exit_code})\n"
        script = _make_script(tmp_dir, script_body, name="prop3_exit_script")

        # --- Buffered path ---
        buffered_executor = LocalSkillScriptExecutor(
            python_executable=sys.executable,
            timeout=15,
        )
        buffered_result = _run_sync(buffered_executor.run(script))

        # --- Streaming path ---
        streaming_executor = StreamingLocalSkillScriptExecutor(
            callback=lambda _: None,
            python_executable=sys.executable,
            timeout=15,
        )
        streaming_result = _run_sync(streaming_executor.run(script))

        expected_suffix = f"Script exited with code {exit_code}"

        assert expected_suffix in buffered_result, (
            f"Buffered path missing exit-code suffix for code {exit_code}:\n{buffered_result!r}"
        )
        assert expected_suffix in streaming_result, (
            f"Streaming path missing exit-code suffix for code {exit_code}:\n{streaming_result!r}"
        )


def test_property3_timeout_raises_same_error_type():
    """
    **Validates: Design §Correctness Properties — Property 3**

    When the script exceeds the timeout, both the buffered path and the streaming
    path raise SkillScriptExecutionError with a message containing "timed out".
    """
    import pytest
    from pydantic_ai_skills.exceptions import SkillScriptExecutionError

    with tempfile.TemporaryDirectory() as tmp_dir:
        script_body = "import time; time.sleep(60)\n"
        script = _make_script(tmp_dir, script_body, name="prop3_timeout_script")

        # --- Buffered path ---
        buffered_executor = LocalSkillScriptExecutor(
            python_executable=sys.executable,
            timeout=1,
        )
        with pytest.raises(SkillScriptExecutionError) as buffered_exc:
            _run_sync(buffered_executor.run(script))

        # --- Streaming path ---
        streaming_executor = StreamingLocalSkillScriptExecutor(
            callback=lambda _: None,
            python_executable=sys.executable,
            timeout=1,
        )
        with pytest.raises(SkillScriptExecutionError) as streaming_exc:
            _run_sync(streaming_executor.run(script))

        assert "timed out" in str(buffered_exc.value).lower(), (
            f"Buffered timeout message missing 'timed out': {buffered_exc.value!r}"
        )
        assert "timed out" in str(streaming_exc.value).lower(), (
            f"Streaming timeout message missing 'timed out': {streaming_exc.value!r}"
        )
