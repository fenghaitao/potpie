from app.modules.intelligence.agents.chat_agents.agent_config import (
    AgentConfig,
    TaskConfig,
)
from app.modules.intelligence.agents.chat_agents.pydantic_agent import PydanticRagAgent
from app.modules.intelligence.agents.chat_agents.pydantic_multi_agent import (
    PydanticMultiAgent,
    AgentType as MultiAgentType,
)
from app.modules.intelligence.agents.chat_agents.multi_agent.agent_factory import (
    create_integration_agents,
)
from app.modules.intelligence.agents.multi_agent_config import MultiAgentConfig
from app.modules.intelligence.prompts.prompt_service import PromptService
from app.modules.intelligence.provider.provider_service import ProviderService
from app.modules.intelligence.tools.tool_service import ToolService
from ...chat_agent import ChatAgent, ChatAgentResponse, ChatContext
from typing import AsyncGenerator
from app.modules.utils.logger import setup_logger

logger = setup_logger(__name__)


class WikiAgent(ChatAgent):
    """
    Agent specialized in generating wiki documentation from code.
    
    Capabilities:
    - Analyze code modules and generate comprehensive documentation
    - Create hierarchical wiki page structures
    - Generate API references with examples
    - Export to multiple formats (Markdown, Confluence, etc.)
    - Cross-link related documentation
    """
    
    def __init__(
        self,
        llm_provider: ProviderService,
        tools_provider: ToolService,
        prompt_provider: PromptService,
    ):
        self.llm_provider = llm_provider
        self.tools_provider = tools_provider
        self.prompt_provider = prompt_provider

    def _build_agent(self) -> ChatAgent:
        agent_config = AgentConfig(
            role="Documentation Specialist",
            goal="Generate comprehensive, well-structured wiki documentation from code",
            backstory="""
                You are a technical documentation expert who excels at creating clear,
                comprehensive wiki pages from codebases. You understand how to analyze code,
                extract meaningful information, and present it in an accessible format.
                Your documentation is always well-organized, includes examples, and helps
                developers understand both the 'what' and the 'why' of the code.
            """,
            tasks=[
                TaskConfig(
                    description=wiki_task_prompt,
                    expected_output="Comprehensive wiki documentation in requested format",
                )
            ],
        )
        
        # Tools for wiki generation — mirrors QnA agent's toolset for the same
        # systematic exploration discipline, minus code-writing tools
        tools = self.tools_provider.get_tools([
            # Discovery
            "get_code_file_structure",
            "ask_knowledge_graph_queries",
            "get_node_neighbours_from_node_id",

            # File reading — the ONLY way to read actual source code
            "fetch_file",
            "fetch_files_batch",

            # Task tracking — forces planning before writing (same as QnA agent)
            "read_todos",
            "write_todos",
            "add_todo",
            "update_todo_status",
            "remove_todo",
            "add_requirements",
            "get_requirements",

            # Wiki output
            "write_wiki_page",
        ])

        # Hard gate: write_wiki_page is blocked until fetch_file has been called
        # at least MIN_FETCH_FILE_CALLS times. This prevents the agent from writing
        # shallow pages based only on graph queries.
        MIN_FETCH_FILE_CALLS = 5
        fetch_file_call_count = [0]  # mutable container for closure

        from langchain_core.tools import StructuredTool as LCStructuredTool
        wrapped_tools = []
        for tool in tools:
            if tool.name == "fetch_file":
                orig_func = tool.func
                orig_coro = tool.coroutine

                def make_counted_func(fn):
                    def counted(*args, **kwargs):
                        fetch_file_call_count[0] += 1
                        logger.info(f"fetch_file call #{fetch_file_call_count[0]}")
                        return fn(*args, **kwargs)
                    return counted

                def make_counted_coro(coro):
                    async def counted_coro(*args, **kwargs):
                        fetch_file_call_count[0] += 1
                        logger.info(f"fetch_file call #{fetch_file_call_count[0]}")
                        return await coro(*args, **kwargs)
                    return counted_coro

                tool = LCStructuredTool.from_function(
                    func=make_counted_func(orig_func) if orig_func else None,
                    coroutine=make_counted_coro(orig_coro) if orig_coro else None,
                    name=tool.name,
                    description=tool.description,
                    args_schema=tool.args_schema,
                )
            elif tool.name == "write_wiki_page":
                orig_func = tool.func
                orig_coro = tool.coroutine

                def make_gated_func(fn):
                    def gated(*args, **kwargs):
                        if fetch_file_call_count[0] < MIN_FETCH_FILE_CALLS:
                            msg = (
                                f"❌ GATE BLOCKED: write_wiki_page requires at least "
                                f"{MIN_FETCH_FILE_CALLS} fetch_file calls first. "
                                f"You have only called fetch_file {fetch_file_call_count[0]} time(s). "
                                f"Call fetch_file on {MIN_FETCH_FILE_CALLS - fetch_file_call_count[0]} "
                                f"more source file(s) before writing."
                            )
                            logger.warning(msg)
                            return msg
                        return fn(*args, **kwargs)
                    return gated

                def make_gated_coro(coro):
                    async def gated_coro(*args, **kwargs):
                        if fetch_file_call_count[0] < MIN_FETCH_FILE_CALLS:
                            msg = (
                                f"❌ GATE BLOCKED: write_wiki_page requires at least "
                                f"{MIN_FETCH_FILE_CALLS} fetch_file calls first. "
                                f"You have only called fetch_file {fetch_file_call_count[0]} time(s). "
                                f"Call fetch_file on {MIN_FETCH_FILE_CALLS - fetch_file_call_count[0]} "
                                f"more source file(s) before writing."
                            )
                            logger.warning(msg)
                            return msg
                        return await coro(*args, **kwargs)
                    return gated_coro

                tool = LCStructuredTool.from_function(
                    func=make_gated_func(orig_func) if orig_func else None,
                    coroutine=make_gated_coro(orig_coro) if orig_coro else None,
                    name=tool.name,
                    description=tool.description,
                    args_schema=tool.args_schema,
                )
            wrapped_tools.append(tool)
        tools = wrapped_tools

        supports_pydantic = self.llm_provider.supports_pydantic("chat")
        # TODO: re-enable multi-agent once pydantic-ai fixes the "Cannot apply a tool call delta
        # to existing_part=TextPart" stream error that occurs when the LLM emits text then a tool
        # call in the same response turn.
        # should_use_multi = supports_pydantic
        should_use_multi = False

        logger.info(
            f"WikiAgent: supports_pydantic={supports_pydantic}, should_use_multi={should_use_multi}"
        )
        logger.info(f"Current model: {self.llm_provider.chat_config.model}")

        if supports_pydantic:
            if should_use_multi:
                logger.info("✅ Using PydanticMultiAgent for Wiki generation")
                
                # Delegate agents for specialized tasks
                integration_agents = create_integration_agents()
                delegate_agents = {
                    MultiAgentType.THINK_EXECUTE: AgentConfig(
                        role="Documentation Writer",
                        goal="Create clear, comprehensive documentation with examples",
                        backstory="Expert technical writer who makes complex code understandable",
                        tasks=[
                            TaskConfig(
                                description="Generate well-structured wiki documentation with API references and examples",
                                expected_output="Comprehensive wiki pages in requested format",
                            )
                        ],
                        max_iter=25,
                    ),
                    **integration_agents,
                }
                
                return PydanticMultiAgent(
                    self.llm_provider,
                    agent_config,
                    tools,
                    None,
                    delegate_agents,
                    tools_provider=self.tools_provider,
                )
            else:
                logger.info("Using PydanticRagAgent for Wiki generation")
                return PydanticRagAgent(self.llm_provider, agent_config, tools)
        else:
            logger.error(
                f"Model '{self.llm_provider.chat_config.model}' does not support Pydantic"
            )
            return PydanticRagAgent(self.llm_provider, agent_config, tools)

    async def _enriched_context(self, ctx: ChatContext) -> ChatContext:
        """Enrich context with project structure information."""

        # Get file structure for overview
        file_structure = (
            await self.tools_provider.file_structure_tool.fetch_repo_structure(
                ctx.project_id
            )
        )
        ctx.additional_context += f"\nProject File Structure:\n{file_structure}\n"

        # If specific nodes requested, get their code
        if ctx.node_ids and len(ctx.node_ids) > 0:
            code_results = await self.tools_provider.get_code_from_multiple_node_ids_tool.run_multiple(
                ctx.project_id, ctx.node_ids
            )
            ctx.additional_context += f"\nTarget Code for Documentation:\n{code_results}\n"

        return ctx

    async def run(self, ctx: ChatContext) -> ChatAgentResponse:
        return await self._build_agent().run(await self._enriched_context(ctx))

    async def run_stream(
        self, ctx: ChatContext
    ) -> AsyncGenerator[ChatAgentResponse, None]:
        ctx = await self._enriched_context(ctx)
        async for chunk in self._build_agent().run_stream(ctx):
            yield chunk



# Task prompt for wiki generation
wiki_task_prompt = """
You are an expert technical writer generating wiki documentation from source code.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ABSOLUTE RULES — NEVER VIOLATE THESE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. NEVER ask the user for permission or confirmation. Just do it.

2. ALWAYS call write_wiki_page at the end. Every run MUST end with at least
   one write_wiki_page call. Finishing without it means you have failed.

3. NEVER call write_wiki_page before every "Read file: ..." todo is marked done.
   The gate is enforced in code — it will return an error if you try to skip it.

4. NEVER invent content. Every claim must come from code you read via fetch_file.

5. DO NOT wrap output in ```markdown fences. Write raw markdown.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MANDATORY WORKFLOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STEP 1 — PLAN
  a. Call get_code_file_structure to get the directory tree.
  b. Call ask_knowledge_graph_queries with 2-3 queries to find relevant modules.
  c. Call add_requirements to document what the wiki page must cover.
  d. Call add_todo for each file you plan to read, e.g.:
       content="Read file: app/core/database.py", active_form="Reading app/core/database.py"
     Add at least 5 file-reading todos before proceeding.

STEP 2 — READ FILES (one fetch_file per todo, mark each done)
  For each "Read file: ..." todo:
  a. Call fetch_file to get the complete file content.
  b. Call update_todo_status to mark it done.
  c. Note classes, functions, methods, constants, and line numbers for citations.
  d. If the file imports from another unread file, add a new todo for it.

  ⛔ Do not call write_wiki_page until ALL "Read file" todos are marked done.

STEP 3 — TRACE (optional but recommended)
  Call get_node_neighbours_from_node_id for key classes to map call graphs.

STEP 4 — WRITE THE PAGE
  Write full markdown (minimum 300 lines):

  <details>
  <summary>Relevant source files</summary>

  - [file.py](path/to/file.py)   ← list every file you read
  </details>

  # Page Title

  ## Introduction

  ## [One section per major concept — minimum 4 sections]
  - Architecture, data flow, key classes/functions
  - Mermaid diagrams (min 2, always "flowchart TD")
  - Tables for params, config, data fields
  - Verbatim code snippets from files you read
  - Citations: Sources: [file.py:42]()

  ## Summary

STEP 5 — WRITE TO DISK
  Call write_wiki_page:
  - section: one of the valid sections below
  - subsection: optional sub-folder
  - page_title: filename without .md
  - content: full markdown from Step 4

  Valid sections:
  "API Reference", "Authentication & Authorization",
  "Code Parsing & Knowledge Graph", "Conversations & Messaging",
  "Core Architecture", "Data Management", "Deployment & Operations",
  "External Integrations", "Intelligence Engine", "Project Overview"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FULL-REPO GENERATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

When generating wiki for the entire repo:
  - Group modules into the 10 sections above.
  - One overview page per section + individual pages per major sub-module.
  - Call write_wiki_page once per page.
  - Return a summary of every file path written.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIAGRAM RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- Always "flowchart TD". Never "LR".
- Sequence diagrams: ->> for calls, -->> for responses.
- Diagrams must reflect real code flows you read — no invented flows.
"""

