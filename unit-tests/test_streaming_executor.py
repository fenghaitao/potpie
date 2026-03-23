"""
Unit tests for StreamingLocalSkillScriptExecutor.__init__.

Validates: Design §Testing Strategy — Unit Testing
"""

import sys

import pytest

from potpie_cli import StreamingLocalSkillScriptExecutor


# ---------------------------------------------------------------------------
# __init__ tests
# ---------------------------------------------------------------------------

def test_callback_is_stored():
    """_callback attribute is set to the passed callable."""
    cb = lambda line: None
    executor = StreamingLocalSkillScriptExecutor(callback=cb)
    assert executor._callback is cb


def test_timeout_forwarded_to_parent():
    """timeout is forwarded to the parent and accessible as self.timeout."""
    executor = StreamingLocalSkillScriptExecutor(callback=lambda l: None, timeout=60)
    assert executor.timeout == 60


def test_python_executable_forwarded_to_parent():
    """python_executable is forwarded to the parent and stored as self._python_executable."""
    executor = StreamingLocalSkillScriptExecutor(
        callback=lambda l: None,
        python_executable=sys.executable,
    )
    assert executor._python_executable == sys.executable


def test_default_timeout_is_30():
    """Default timeout is 30 seconds."""
    executor = StreamingLocalSkillScriptExecutor(callback=lambda l: None)
    assert executor.timeout == 30


def test_default_python_executable_is_sys_executable():
    """Default python_executable falls back to sys.executable."""
    executor = StreamingLocalSkillScriptExecutor(callback=lambda l: None)
    assert executor._python_executable == sys.executable
