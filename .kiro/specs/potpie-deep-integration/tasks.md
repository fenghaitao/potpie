# Tasks: potpie-deep-integration

## Task List

- [x] 1. Create package scaffold
  - [x] 1.1 Create `pydantic-deepagents/apps/potpie/__init__.py`
  - [x] 1.2 Verify `pydantic-deepagents/apps/potpie/` directory exists alongside `apps/cli/` and `apps/deepresearch/`

- [x] 2. Implement `toolset.py`
  - [x] 2.1 Create `pydantic-deepagents/apps/potpie/toolset.py` with `create_potpie_toolset(runtime, project_id, user_id, toolset_id)` that opens a DB session, instantiates `ToolService`, calls `get_tools([...KG_TOOL_NAMES...])`, wraps via `wrap_structured_tools`, and returns a `FunctionToolset`
  - [x] 2.2 Define `KG_TOOL_NAMES` constant listing all 8 KG tools
  - [x] 2.3 Add a `_close_session` cleanup helper so the DB session can be closed after agent run

- [x] 3. Implement `agent.py`
  - [x] 3.1 Create `pydantic-deepagents/apps/potpie/agent.py` with `create_potpie_agent(runtime, project_id, user_id, model, **kwargs)` factory
  - [x] 3.2 Ensure `kg_toolset` is passed to both `toolsets` and `subagent_extra_toolsets` in `create_deep_agent`
  - [x] 3.3 Set defaults: `include_subagents=True`, `include_teams=True`, `include_memory=True`, `context_manager=True`, `eviction_token_limit=20_000`
  - [x] 3.4 Construct `DeepAgentDeps(backend=StateBackend())` and return `(agent, deps)`

- [x] 4. Implement `cli.py`
  - [x] 4.1 Create `pydantic-deepagents/apps/potpie/cli.py` with Typer app named `potpie-deep`
  - [x] 4.2 Implement `parse` command: init runtime, register project, parse, print project_id, handle errors
  - [x] 4.3 Implement `chat` command: init runtime, create agent, run interactive loop (reuse `apps.cli.interactive` pattern), handle errors
  - [x] 4.4 Implement `ask` command: init runtime, create agent, run single query, print result, handle errors
  - [x] 4.5 Add graceful error handling for `PotpieError`, `ConfigurationError`, and connection errors in all three commands
  - [x] 4.6 Ensure runtime is always closed in a `finally` block

- [x] 5. Write tests
  - [x] 5.1 Create `pydantic-deepagents/apps/potpie/tests/test_toolset.py`: mock `PotpieRuntime` and `ToolService`, assert toolset has correct tool names and all names are sanitized
  - [x] 5.2 Create `pydantic-deepagents/apps/potpie/tests/test_agent.py`: mock `create_potpie_toolset`, assert `create_deep_agent` is called with `kg_toolset` in both `toolsets` and `subagent_extra_toolsets`, assert `deps.backend` is `StateBackend`
  - [x] 5.3 Create `pydantic-deepagents/apps/potpie/tests/test_cli.py`: use `typer.testing.CliRunner` to test `parse`, `chat`, `ask` commands including backend-down error paths
  - [x] 5.4 Add hypothesis property test for `sanitize_tool_name_for_api` (Requirement Correctness Property 1)
