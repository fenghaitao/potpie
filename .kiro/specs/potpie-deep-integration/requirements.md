# Requirements: potpie-deep-integration

## Introduction

This feature replaces `potpie_cli.py` with `pydantic-deep chat` as the primary user interface for potpie's code intelligence. The implementation is a new package at `pydantic-deepagents/apps/potpie/` that wires potpie's knowledge graph tools into a `create_deep_agent()` call. All existing backend code (`app/`, `potpie/`) is unchanged.

---

## Requirements

### Requirement 1: Potpie KG Toolset

**User Story**: As a developer using the pydantic-deep CLI, I want potpie's knowledge graph tools available to the agent so I can ask questions about my codebase.

#### Acceptance Criteria

1.1 `create_potpie_toolset(runtime, project_id, user_id)` returns a `FunctionToolset` containing at minimum these tools: `ask_knowledge_graph_queries`, `get_code_from_multiple_node_ids`, `get_code_from_probable_node_name`, `get_code_file_structure`, `fetch_file`, `fetch_files_batch`, `get_node_neighbours_from_node_id`, `analyze_code_structure`.

1.2 All tool names in the returned toolset satisfy the regex `^[a-zA-Z0-9_-]+$` (OpenAI-compatible API requirement).

1.3 Tool functions are wrapped with `handle_exception` so that any exception raised by a KG tool is caught and returned as an error string rather than crashing the agent.

1.4 The `user_id` passed to `create_potpie_toolset` is forwarded to `ToolService` so that potpie's per-user access control is preserved.

1.5 The same `FunctionToolset` instance can be passed to both `toolsets` and `subagent_extra_toolsets` in `create_deep_agent` without error.

---

### Requirement 2: Potpie Agent Factory

**User Story**: As a developer, I want a single factory function that creates a fully-configured pydantic-deep agent with potpie KG tools available to both the main agent and all spawned subagents.

#### Acceptance Criteria

2.1 `create_potpie_agent(runtime, project_id, user_id)` calls `create_deep_agent` with `kg_toolset` in both `toolsets` and `subagent_extra_toolsets`.

2.2 The agent is created with `include_subagents=True`, `include_teams=True`, `include_memory=True`, and `context_manager=True` as defaults.

2.3 The agent is created with `eviction_token_limit=20_000` so that tool outputs exceeding 20K tokens are evicted to prevent context overflow.

2.4 `DeepAgentDeps` is constructed with `backend=StateBackend()` (in-memory), not a filesystem backend.

2.5 The factory accepts `**kwargs` that are forwarded to `create_deep_agent`, allowing callers to override model, instructions, and other parameters.

---

### Requirement 3: CLI — `parse` command

**User Story**: As a developer, I want to parse a local repository from the command line so that its knowledge graph is built and I receive a `project_id` to use in subsequent queries.

#### Acceptance Criteria

3.1 `potpie-deep parse <repo_path>` initializes `PotpieRuntime.from_env()`, calls `runtime.projects.register(...)`, and calls `runtime.parsing.parse_project(project_id)`.

3.2 On success, the command prints the `project_id` to stdout.

3.3 If `POSTGRES_SERVER`, `NEO4J_URI`, `NEO4J_USERNAME`, or `NEO4J_PASSWORD` are not set, the command prints a clear error message and exits with code 1.

3.4 If the backend services are unreachable (connection error), the command prints an actionable error message (e.g., "Ensure PostgreSQL and Neo4j are running") and exits with code 1.

3.5 The runtime is always closed (via `runtime.close()`) after the command completes, whether it succeeds or fails.

---

### Requirement 4: CLI — `chat` command

**User Story**: As a developer, I want an interactive chat session with potpie's code intelligence so I can explore my codebase conversationally.

#### Acceptance Criteria

4.1 `potpie-deep chat --project-id <id>` creates a potpie agent via `create_potpie_agent` and starts an interactive loop.

4.2 The interactive loop streams agent responses to the terminal using Rich markdown rendering (consistent with `apps/cli/interactive.py` patterns).

4.3 On `KeyboardInterrupt` or `/quit`, the session exits cleanly and the runtime is closed.

4.4 If the backend is unreachable at startup, the command prints an error and exits with code 1 before entering the interactive loop.

4.5 The `--model` flag allows overriding the default model.

---

### Requirement 5: CLI — `ask` command

**User Story**: As a developer, I want to run a one-shot query against my codebase without entering an interactive session.

#### Acceptance Criteria

5.1 `potpie-deep ask "<query>" --project-id <id>` runs a single `agent.run(query, deps=deps)` call and prints the result to stdout.

5.2 The command exits with code 0 on success and code 1 on any error.

5.3 The runtime is closed after the query completes.

5.4 The `--model` flag allows overriding the default model.

---

### Requirement 6: Additive — no existing files modified

**User Story**: As a maintainer, I want the integration to be purely additive so that existing potpie and pydantic-deep functionality is not broken.

#### Acceptance Criteria

6.1 No files in `app/` are modified.

6.2 No files in `potpie/` are modified.

6.3 No files in `pydantic-deepagents/pydantic_deep/` are modified.

6.4 The new package is self-contained at `pydantic-deepagents/apps/potpie/` with its own `__init__.py`.

---

## Correctness Properties

### Property 1: Tool name sanitization is total and safe

For any non-empty string `s`, `sanitize_tool_name_for_api(s)` returns a non-empty string matching `^[a-zA-Z0-9_-]+$`.

```python
# hypothesis property test
from hypothesis import given, strategies as st
import re
from app.modules.intelligence.agents.chat_agents.multi_agent.utils.tool_utils import sanitize_tool_name_for_api

@given(st.text(min_size=1))
def test_sanitize_tool_name_always_valid(name: str):
    result = sanitize_tool_name_for_api(name)
    assert re.match(r'^[a-zA-Z0-9_-]+$', result)
    assert len(result) > 0
```

### Property 2: Subagent toolset propagation

For any `FunctionToolset` passed as `subagent_extra_toolsets`, every subagent created by `_default_deep_agent_factory` receives that toolset in its `subagent_extra_toolsets` argument.

```python
# Verifiable by inspecting the _default_deep_agent_factory closure in create_deep_agent:
# _sub_extra = list(subagent_extra_toolsets) if subagent_extra_toolsets else []
# ...
# subagent_extra_toolsets=_sub_extra or None
assert kg_toolset in agent._subagent_extra_toolsets
```

### Property 3: Context eviction threshold

For any tool result string with token count > 20,000, the eviction processor replaces it with a preview. For any tool result with token count ≤ 20,000, it is passed through unchanged.

```python
# Verifiable by asserting eviction_token_limit=20_000 is passed to create_deep_agent
# and by testing EvictionProcessor directly with a large mock result
```
