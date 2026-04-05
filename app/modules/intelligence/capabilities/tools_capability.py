"""PotpieToolsCapability — wraps potpie StructuredTools as a pydantic-ai capability.

Converts LangChain StructuredTool instances (from ToolService) into a
pydantic-ai FunctionToolset and exposes it via AbstractCapability.get_toolset().

Usage::

    from app.modules.intelligence.capabilities import PotpieToolsCapability

    tools = tools_provider.get_tools(["ask_knowledge_graph_queries", "fetch_file"])
    cap = PotpieToolsCapability(tools, id="potpie-tools")

    agent = Agent(
        model=llm_provider.get_pydantic_model(),
        capabilities=[cap],
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import AbstractToolset

from app.modules.intelligence.agents.chat_agents.multi_agent.utils.tool_utils import (
    wrap_structured_tools,
)
from app.modules.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class PotpieToolsCapability(AbstractCapability[Any]):
    """Capability that registers potpie StructuredTools with a pydantic-ai agent.

    Converts LangChain StructuredTool instances into a pydantic-ai
    FunctionToolset via the existing wrap_structured_tools() helper,
    preserving all schema inlining, name sanitization, and exception
    handling that the multi-agent system already relies on.

    Args:
        tools: List of LangChain StructuredTool instances from ToolService.
        toolset_id: Optional ID for the toolset (used in error messages).
    """

    tools: Sequence[Any] = field(default_factory=list)
    toolset_id: str = "potpie-tools"
    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False
    )

    def __post_init__(self) -> None:
        from pydantic_ai.toolsets import FunctionToolset

        wrapped = wrap_structured_tools(self.tools)
        toolset: FunctionToolset[Any] = FunctionToolset(
            tools=wrapped,
            id=self.toolset_id,
        )
        self._toolset = toolset
        logger.debug(
            "PotpieToolsCapability: registered %d tools (id=%s)",
            len(wrapped),
            self.toolset_id,
        )

    def get_toolset(self) -> AbstractToolset[Any] | None:
        return self._toolset
