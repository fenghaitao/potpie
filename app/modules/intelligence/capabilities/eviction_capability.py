"""make_eviction_processor — large tool output eviction for potpie agents.

Wraps pydantic-deep's EvictionProcessor with a StateBackend so large
knowledge-graph / code-fetch results are saved to an in-memory store
and replaced with a preview + read instruction, keeping the context lean.

Usage::

    from app.modules.intelligence.capabilities import make_eviction_processor

    processor = make_eviction_processor(token_limit=20_000)
    agent = Agent(model=..., history_processors=[processor])
"""

from __future__ import annotations

from typing import Any


def make_eviction_processor(
    token_limit: int = 20_000,
    eviction_path: str = "/potpie_evicted",
    head_lines: int = 8,
    tail_lines: int = 8,
    on_eviction: Any | None = None,
) -> Any:
    """Create an EvictionProcessor backed by an in-memory StateBackend.

    Large tool outputs (knowledge graph results, code fetches, etc.) that
    exceed ``token_limit`` tokens are saved to the in-memory backend and
    replaced with a head/tail preview plus a ``read_file`` instruction.

    Args:
        token_limit: Approximate token threshold before eviction (default 20K).
        eviction_path: Directory path in the backend for evicted files.
        head_lines: Lines to show from the start of evicted content.
        tail_lines: Lines to show from the end of evicted content.
        on_eviction: Optional callback(tool_name, file_path, orig_chars, preview_chars).

    Returns:
        A configured EvictionProcessor instance.
    """
    from pydantic_ai_backends import StateBackend
    from pydantic_deep.processors.eviction import EvictionProcessor

    backend = StateBackend()
    return EvictionProcessor(
        backend=backend,
        token_limit=token_limit,
        eviction_path=eviction_path,
        head_lines=head_lines,
        tail_lines=tail_lines,
        on_eviction=on_eviction,
    )
