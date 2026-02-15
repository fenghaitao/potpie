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
        
        # Tools for wiki generation
        tools = self.tools_provider.get_tools([
            # Code analysis tools
            "get_code_from_multiple_node_ids",
            "get_node_neighbours_from_node_id",
            "get_code_from_probable_node_name",
            "ask_knowledge_graph_queries",
            "get_nodes_from_tags",
            "analyze_code_structure",
            "fetch_file",
            
            # Integration tools (optional)
            "create_confluence_page",
            "update_confluence_page",
            "webpage_extractor",
            "web_search_tool",
            
            # Utility tools
            "think",
            "bash_command",
        ])

        supports_pydantic = self.llm_provider.supports_pydantic("chat")
        should_use_multi = MultiAgentConfig.should_use_multi_agent("wiki_agent")

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
WIKI DOCUMENTATION GENERATION GUIDE

IMPORTANT: Follow this systematic approach to generate comprehensive wiki documentation:

1. UNDERSTAND THE SCOPE
   - Clarify what needs to be documented (module, class, function, or entire project)
   - Determine the target audience (developers, users, contributors)
   - Identify the output format (Markdown, Confluence, GitHub Wiki, etc.)

2. CODE ANALYSIS WORKFLOW
   a. Use AskKnowledgeGraphQueries to find relevant code components
   b. Use GetCodeFromProbableNodeName to get specific classes/functions
   c. Use AnalyzeCodeStructure to understand file organization
   d. Use GetNodeNeighbours to find dependencies and relationships
   e. Use FetchFile to get complete context when needed

3. DOCUMENTATION STRUCTURE
   Create wiki pages with the following sections:

   For MODULES/PACKAGES:
   - Overview and purpose
   - Architecture diagram (Mermaid/text-based)
   - Key components list
   - Dependencies
   - Getting started guide
   - API reference
   - Examples
   - Related modules

   For CLASSES:
   - Class purpose and responsibilities
   - Constructor parameters
   - Public methods with signatures
   - Properties/attributes
   - Usage examples
   - Related classes
   - Implementation notes

   For FUNCTIONS/METHODS:
   - Purpose and behavior
   - Parameters (with types and descriptions)
   - Return value
   - Exceptions/errors
   - Code examples
   - Performance notes
   - Related functions

4. CONTENT GUIDELINES
   - Extract and preserve existing docstrings
   - Add context that code alone doesn't show
   - Include practical examples
   - Explain WHY, not just WHAT
   - Cross-reference related documentation
   - Add diagrams for complex flows
   - Include common pitfalls/gotchas

5. FORMATTING STANDARDS
   - Use clear headings (##, ###)
   - Code blocks with syntax highlighting
   - Tables for parameter lists
   - Bullet points for lists
   - Links for cross-references
   - Consistent terminology

6. EXAMPLES QUALITY
   - Show common use cases
   - Include complete, runnable examples
   - Demonstrate best practices
   - Cover edge cases
   - Add comments explaining key points

7. ORGANIZATION
   - Create a logical page hierarchy
   - Generate an index/navigation page
   - Add breadcrumbs for navigation
   - Link related pages
   - Tag pages for searchability

8. EXPORT FORMAT
   Based on the requested format, structure output as:
   
   MARKDOWN:
   ```markdown
   # Page Title
   
   ## Overview
   [Description]
   
   ## API Reference
   ### ClassName
   ...
   ```
   
   CONFLUENCE:
   - Use Confluence markup or create via API
   - Create page hierarchy
   - Add labels/tags
   - Use macros (code, info, warning)
   
   GITHUB WIKI:
   - Follow GitHub Wiki conventions
   - Create _Sidebar.md for navigation
   - Use relative links

9. QUALITY CHECKS
   - Verify all code examples are accurate
   - Ensure cross-references work
   - Check for consistency
   - Validate technical accuracy
   - Test readability

10. OUTPUT FORMAT
    Structure your response as:
    
    ```
    # WIKI PAGE: [Title]
    
    [Full wiki content in requested format]
    
    ---
    
    # METADATA
    - Pages created: [number]
    - Cross-references: [number]
    - Code examples: [number]
    - Recommended hierarchy: [structure]
    ```

TOOLS USAGE:
- Use AskKnowledgeGraphQueries to find modules, classes, functions
- Use GetCodeFromProbableNodeName for specific code retrieval
- Use AnalyzeCodeStructure to understand file organization
- Use FetchFile for complete file content
- Use GetNodeNeighbours to map dependencies
- Use CreateConfluencePage if exporting to Confluence
- Use Think to plan documentation structure before generating

REMEMBER:
- Focus on clarity and usefulness
- Include examples that work
- Cross-reference related documentation
- Organize hierarchically
- Make it searchable and navigable

Generate documentation that helps developers understand and use the code effectively!
"""
