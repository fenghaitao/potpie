"""AuditCapability — tool lifecycle hooks for potpie agents.

Provides:
- Background audit logging of every tool call and result
- Pre-execution safety gate for bash/git/apply tools
- Post-execution result truncation logging for large outputs

Usage::

    from app.modules.intelligence.capabilities import AuditCapability

    cap = AuditCapability(
        log_calls=True,
        block_dangerous_bash=True,
    )
    agent = Agent(model=..., capabilities=[cap])
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition

from app.modules.utils.logger import setup_logger

logger = setup_logger(__name__)

# Tools that touch the filesystem or run code — worth auditing at INFO level
_HIGH_VALUE_TOOLS = frozenset(
    {
        "bash_command",
        "apply_changes",
        "git_commit",
        "git_push",
        "code_provider_create_pr",
        "code_provider_update_file",
        "execute_terminal_command",
        "add_file_to_changes",
        "update_file_in_changes",
        "update_file_lines",
        "replace_in_file",
        "insert_lines",
        "delete_lines",
        "delete_file_in_changes",
    }
)

# Patterns that should never run via bash_command / execute_terminal_command
_DANGEROUS_BASH_PATTERNS = [
    re.compile(r"rm\s+-rf\s+/"),
    re.compile(r"rm\s+-rf\s+\*"),
    re.compile(r"mkfs\."),
    re.compile(r"dd\s+if=.*of=/dev/"),
    re.compile(r"chmod\s+-R\s+777\s+/"),
    re.compile(r":\(\)\{"),  # fork bomb
    re.compile(r">\s*/dev/sda"),
]

_BASH_TOOL_NAMES = frozenset({"bash_command", "execute_terminal_command"})


@dataclass
class AuditCapability(AbstractCapability[Any]):
    """Capability that audits tool calls and enforces safety gates.

    Args:
        log_calls: Log every tool call at DEBUG, high-value tools at INFO.
        log_results: Log result size for every tool call.
        block_dangerous_bash: Block dangerous shell patterns before execution.
    """

    log_calls: bool = True
    log_results: bool = True
    block_dangerous_bash: bool = False

    # Counters — reset per agent instance, not per run
    _call_count: int = field(default=0, init=False, repr=False)
    _blocked_count: int = field(default=0, init=False, repr=False)

    async def before_tool_execute(
        self,
        ctx: RunContext[Any],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: Any,
    ) -> Any:
        tool_name = call.tool_name
        self._call_count += 1

        if self.log_calls:
            args_preview = str(args)[:200]
            if tool_name in _HIGH_VALUE_TOOLS:
                logger.info(
                    "TOOL CALL [%s] args=%s", tool_name, args_preview
                )
            else:
                logger.debug(
                    "TOOL CALL [%s] args=%s", tool_name, args_preview
                )

        # Safety gate: block dangerous bash patterns
        if self.block_dangerous_bash and tool_name in _BASH_TOOL_NAMES:
            command = ""
            if isinstance(args, dict):
                command = str(args.get("command", args.get("cmd", "")))
            elif isinstance(args, str):
                command = args

            for pattern in _DANGEROUS_BASH_PATTERNS:
                if pattern.search(command):
                    self._blocked_count += 1
                    from pydantic_ai.exceptions import ModelRetry

                    raise ModelRetry(
                        f"BLOCKED: command matches dangerous pattern "
                        f"({pattern.pattern!r}). Refusing to execute: {command[:100]!r}"
                    )

        return args

    async def after_tool_execute(
        self,
        ctx: RunContext[Any],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: Any,
        result: Any,
    ) -> Any:
        if self.log_results:
            result_len = len(str(result)) if result is not None else 0
            logger.debug(
                "TOOL RESULT [%s] size=%d chars", call.tool_name, result_len
            )
        return result

    @property
    def stats(self) -> dict[str, int]:
        """Return audit statistics."""
        return {
            "calls": self._call_count,
            "blocked": self._blocked_count,
        }
