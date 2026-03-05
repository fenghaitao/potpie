from typing import AsyncGenerator

from app.modules.intelligence.agents.agent_config import (
    AgentConfig,
    TaskConfig,
)
from app.modules.intelligence.agents.chat_agents.multi_agent.agent_factory import (
    create_integration_agents,
)
from app.modules.intelligence.agents.chat_agents.pydantic_agent import PydanticRagAgent
from app.modules.intelligence.agents.chat_agents.pydantic_multi_agent import (
    AgentType as MultiAgentType,
    PydanticMultiAgent,
)
from app.modules.intelligence.agents.multi_agent_config import MultiAgentConfig
from app.modules.intelligence.prompts.prompt_service import PromptService
from app.modules.intelligence.provider.provider_service import ProviderService
from app.modules.intelligence.tools.tool_service import ToolService
from app.modules.utils.logger import setup_logger

from ...chat_agent import ChatAgent, ChatAgentResponse, ChatContext

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
        # Tools for wiki generation — keep lean to stay within context limits
        tools = self.tools_provider.get_tools(
            [
                # Core code reading tools
                "fetch_file",
                "fetch_files_batch",
                "get_code_file_structure",
                "analyze_code_structure",
                "get_code_from_multiple_node_ids",
                "get_code_from_probable_node_name",
                "ask_knowledge_graph_queries",
                "get_node_neighbours_from_node_id",
                # Wiki tools — writes and lists pages in .qoder/repowiki/
                "write_wiki_page",
                "list_wiki_pages",
            ]
        )

        supports_pydantic = self.llm_provider.supports_pydantic("chat")
        should_use_multi = MultiAgentConfig.should_use_multi_agent("wiki_agent")

        logger.info(
            f"WikiAgent: supports_pydantic={supports_pydantic}, should_use_multi={should_use_multi}"
        )
        logger.info(f"Current model: {self.llm_provider.chat_config.model}")

        if supports_pydantic:
            if should_use_multi:
                logger.info("✅ Using PydanticMultiAgent for Wiki generation")

                agent_config = AgentConfig(
                    role="Wiki Architect",
                    goal="Oversee the generation of a comprehensive, well-structured repository wiki by conducting deep research and coordinating specialized writers.",
                    backstory="""
                        You are a senior software architect and technical documentation lead.
                        You excel at understanding complex system designs and planning how they
                        should be documented. You don't just write pages; you architect a
                        knowledge base. You use specialized writers to produce the actual
                        content while you focus on deep code research, structural integrity,
                        and ensuring every claim is backed by source code.
                    """,
                    tasks=[
                        TaskConfig(
                            description=WIKI_RESEARCH_INSTRUCTIONS,
                            expected_output="A complete, well-structured wiki written to disk, with all research and writing coordinated.",
                        )
                    ],
                )

                # Delegate agents for specialized tasks
                integration_agents = create_integration_agents()
                delegate_agents = {
                    MultiAgentType.THINK_EXECUTE: AgentConfig(
                        role="Documentation Writer",
                        goal="Transform technical research and code snippets into professional, high-quality wiki pages",
                        backstory="""You are an elite technical writer who specializes in creating
                        developer-centric documentation. You take raw research, code analysis,
                        and requirements and produce beautiful Markdown pages with diagrams,
                        tables, and precise citations. You follow strict formatting guidelines
                        to ensure consistency and clarity.""",
                        tasks=[
                            TaskConfig(
                                description=WIKI_WRITING_INSTRUCTIONS,
                                expected_output="Professional wiki page content in Markdown format, ready to be written to disk.",
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
                logger.info(
                    "Using PydanticRagAgent for Wiki generation (Single Agent Mode)"
                )
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
                            description=SINGLE_AGENT_WIKI_PROMPT,
                            expected_output="Comprehensive wiki documentation in requested format",
                        )
                    ],
                )
                return PydanticRagAgent(self.llm_provider, agent_config, tools)
        else:
            logger.error(
                f"Model '{self.llm_provider.chat_config.model}' does not support Pydantic"
            )
            # Fallback for non-pydantic models
            agent_config = AgentConfig(
                role="Documentation Specialist",
                goal="Generate comprehensive, well-structured wiki documentation from code",
                tasks=[
                    TaskConfig(
                        description=SINGLE_AGENT_WIKI_PROMPT,
                        expected_output="Markdown wiki",
                    )
                ],
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
            code_results = (
                await self.tools_provider.get_code_from_multiple_node_ids_tool.run_multiple(
                    ctx.project_id, ctx.node_ids
                )
            )
            ctx.additional_context += (
                f"\nTarget Code for Documentation:\n{code_results}\n"
            )

        return ctx

    async def run(self, ctx: ChatContext) -> ChatAgentResponse:
        return await self._build_agent().run(await self._enriched_context(ctx))

    async def run_stream(
        self, ctx: ChatContext
    ) -> AsyncGenerator[ChatAgentResponse, None]:
        ctx = await self._enriched_context(ctx)
        async for chunk in self._build_agent().run_stream(ctx):
            yield chunk


# --- PROMPT DEFINITIONS ---

WIKI_WRITING_INSTRUCTIONS = """
WIKI WRITING & FORMATTING REQUIREMENTS - PROFESSIONAL EDITION

You are a Documentation Writer. Your task is to take the research findings provided
by the Architect and transform them into a high-quality, professional wiki page.

═══════════════════════════════════════════════════════════════════════════
CRITICAL FORMATTING REQUIREMENTS:
═══════════════════════════════════════════════════════════════════════════

1. START WITH SOURCE FILES DISCLOSURE
   The VERY FIRST thing on the page MUST be a <details> block listing ALL source files used:
   
   <details>
   <summary>Relevant source files</summary>
   
   The following files were used as context for generating this wiki page:
   
   - [file1.py](path/to/file1.py)
   - [file2.py](path/to/file2.py)
   <!-- List all files identified in research -->
   </details>

2. MAIN TITLE - Immediately after <details> block:
   # [Topic Title]

3. NO PREAMBLE
   - DO NOT include acknowledgements, disclaimers, or apologies
   - DO NOT wrap content in ```markdown fences
   - START directly with the <details> block

═══════════════════════════════════════════════════════════════════════════
CONTENT STRUCTURE:
═══════════════════════════════════════════════════════════════════════════

1. INTRODUCTION (1-2 paragraphs)
   - Purpose and scope of the topic
   - High-level overview
   - Context within the overall project

2. DETAILED SECTIONS (Use ## and ### headings)
   - Explain architecture, components, data flow, logic
   - Identify key functions, classes, data structures
   - Reference API endpoints, configuration elements
   - Show relationships and dependencies

3. MERMAID DIAGRAMS (EXTENSIVE USE REQUIRED - Minimum 3 diagrams per major topic)
   
   CRITICAL DIAGRAM RULES:
   - ALL diagrams MUST use vertical orientation: "flowchart TD"
   - Use Sequence Diagrams for complex interactions
   - Use Class/ER Diagrams for data structures
   - Provide context before/after each diagram

4. TABLES (For Structured Information)
   - Use for API parameters, config options, data model fields

5. CODE SNIPPETS
   - Include short, relevant, verbatim snippets with proper language identifiers

6. SOURCE CITATIONS (EXTREMELY IMPORTANT)
   - Cite sources for EVERY significant piece of information!
   - Format: Sources: [file.py:42]() or [file.py:10-25]()
   - REQUIRED: Cite AT LEAST 5 different source files if available

7. TECHNICAL ACCURACY
   - Base ALL information SOLELY on provided research
   - Use correct technical terms

8. QUALITY CHECKLIST:
   □ Starts with <details> block
   □ H1 title immediately after
   □ No markdown fences wrapping the whole page
   □ Minimum 5 ## sections
   □ 3+ Mermaid diagrams (vertical TD)
   □ Line-level source citations throughout
   □ Clear, professional language

Produce the full Markdown content now.
"""

WIKI_RESEARCH_INSTRUCTIONS = """
WIKI ARCHITECT - RESEARCH & COORDINATION WORKFLOW

You are the Wiki Architect. Your mission is to generate a comprehensive,
highly accurate technical wiki for the repository.

═══════════════════════════════════════════════════════════════════════════
YOUR WORKFLOW:
═══════════════════════════════════════════════════════════════════════════

Step 1: DISCOVER & ANALYZE (MANDATORY)
   - Call list_wiki_pages to see what already exists.
   - Call get_code_file_structure to understand the repository layout.
   - Call ask_knowledge_graph_queries to find key components for the topic.
   - Use analyze_code_structure on core files to map classes and methods.

Step 2: DEEP READ (MANDATORY)
   - Use fetch_files_batch to read 8-10 relevant files in detail.
   - Trace data flows and dependencies using get_node_neighbours_from_node_id.

Step 3: PLAN & DELEGATE (MANDATORY)
   - Create a detailed plan for the wiki page(s).
   - DELEGATE THE WRITING TASK to the 'Documentation Writer' subagent.
   - Provide the writer with:
     a) The specific topic and title
     b) A list of all relevant source files and line numbers
     c) Key findings from your research (data flows, API params, logic)
     d) Any specific diagrams or tables you want included

Step 4: REVIEW & PERSIST
   - Once the writer returns the content, review it for completeness.
   - CALL write_wiki_page to save the content to the correct section.
   - VALID SECTIONS: "API Reference", "Architecture & Design",
     "Authentication & Security", "Core Modules", "Data Models & Persistence",
     "Deployment & Infrastructure", "Development Guide", "External Integrations",
     "Project Overview", "System Requirements", "Root".
   - Use "Root" as the section for files like '_sidebar.md' or 'README.md'.

Step 5: NAVIGATION SUPPORT
   - After generating content pages, generate or update a '_sidebar.md'
     and 'README.md' in the wiki root to provide an index and navigation.
   - Use list_wiki_pages to ensure all pages are linked.
   - Call write_wiki_page with section="Root" for these files.

═══════════════════════════════════════════════════════════════════════════
FULL-REPO WIKI GENERATION:
═══════════════════════════════════════════════════════════════════════════

If asked for the entire repository:
1. Map the whole codebase to the valid sections.
2. For each section, conduct research then delegate writing for:
   - A Section Overview page
   - Detailed pages for major modules/sub-systems
3. Ensure cross-linking between sections.
4. Finalize with a comprehensive Sidebar and Main README using section="Root".

REMEMBER: Deep research first, then delegate writing, then persist to disk.
"""

# Combined prompt for single-agent mode - performs both research and writing without delegation
SINGLE_AGENT_WIKI_PROMPT = f"""
WIKI DOCUMENTATION GENERATION - PROFESSIONAL EDITION

{WIKI_WRITING_INSTRUCTIONS}

═══════════════════════════════════════════════════════════════════════════
RESEARCH & WRITING WORKFLOW:
═══════════════════════════════════════════════════════════════════════════

Step 1: DISCOVER & ANALYZE
   - Call list_wiki_pages to see what already exists.
   - Call get_code_file_structure to understand the repository layout.
   - Call ask_knowledge_graph_queries to find key components for the topic.
   - Use analyze_code_structure on core files to map classes and methods.

Step 2: DEEP READ
   - Use fetch_files_batch to read 8-10 relevant files in detail.
   - Trace data flows and dependencies using get_node_neighbours_from_node_id.

Step 3: WRITE THE WIKI PAGE
   - Generate the full Markdown content based on your research.
   - Ensure you follow ALL formatting requirements listed above.

Step 4: PERSIST TO DISK
   - CALL write_wiki_page to save the content to the correct section.
   - VALID SECTIONS: "API Reference", "Architecture & Design",
     "Authentication & Security", "Core Modules", "Data Models & Persistence",
     "Deployment & Infrastructure", "Development Guide", "External Integrations",
     "Project Overview", "System Requirements", "Root".
   - Use "Root" as the section for files like '_sidebar.md' or 'README.md'.

Step 5: NAVIGATION SUPPORT
   - Generate or update a '_sidebar.md' and 'README.md' in the wiki root.
   - Call write_wiki_page with section="Root" for these files.

REMEMBER: Perform deep research first, then write the page yourself, then persist to disk.
"""

# Kept for backward compatibility
wiki_task_prompt = SINGLE_AGENT_WIKI_PROMPT
