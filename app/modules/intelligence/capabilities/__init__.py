"""Pydantic-AI capabilities for potpie agents.

Wraps potpie's ToolService tools and pydantic-deep capabilities
as pydantic-ai AbstractCapability instances, enabling clean
composition via Agent(capabilities=[...]).
"""

from app.modules.intelligence.capabilities.tools_capability import (
    PotpieToolsCapability,
)
from app.modules.intelligence.capabilities.audit_capability import (
    AuditCapability,
)
from app.modules.intelligence.capabilities.eviction_capability import (
    make_eviction_processor,
)

__all__ = [
    "PotpieToolsCapability",
    "AuditCapability",
    "make_eviction_processor",
]
