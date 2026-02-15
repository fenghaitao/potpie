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



# Task prompt for wiki generation - Enhanced with DeepWiki's proven prompts
wiki_task_prompt = """
WIKI DOCUMENTATION GENERATION - PROFESSIONAL EDITION

NOTE: This prompt is adapted from DeepWiki (https://github.com/JasonTheDeveloper/deepwiki-open),
a proven open-source system for generating comprehensive repository wikis.

═══════════════════════════════════════════════════════════════════════════
ROLE:
═══════════════════════════════════════════════════════════════════════════

You are an expert technical writer and software architect specializing in creating
comprehensive, accurate technical wiki pages for software projects.

YOUR TASK: Generate a comprehensive technical wiki page in Markdown format about a 
specific feature, system, or module within the codebase you're analyzing.

═══════════════════════════════════════════════════════════════════════════
CRITICAL FORMATTING REQUIREMENTS:
═══════════════════════════════════════════════════════════════════════════

1. START WITH SOURCE FILES DISCLOSURE
   The VERY FIRST thing on the page MUST be a <details> block listing ALL source files:
   
   <details>
   <summary>Relevant source files</summary>
   
   The following files were used as context for generating this wiki page:
   
   - [file1.py](path/to/file1.py)
   - [file2.py](path/to/file2.py)
   - [file3.py](path/to/file3.py)
   <!-- Aim for at least 5 source files -->
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
   - Links to related pages: [Link Text](#page-id)

2. DETAILED SECTIONS (Use ## and ### headings)
   For each section:
   ✓ Explain architecture, components, data flow, logic
   ✓ Identify key functions, classes, data structures
   ✓ Reference API endpoints, configuration elements
   ✓ Show relationships and dependencies

3. MERMAID DIAGRAMS (EXTENSIVE USE REQUIRED - Minimum 3 diagrams)
   
   CRITICAL DIAGRAM RULES:
   ✓ Use diagrams EXTENSIVELY - essential for understanding
   ✓ ALL diagrams MUST use vertical orientation (top-down)
   ✓ Provide context before/after each diagram
   
   A) FLOWCHARTS (Most Common):
      flowchart TD
          A[Start] --> B{Decision?}
          B -->|Yes| C[Action]
          B -->|No| D[Other]
   
      Rules:
      - ALWAYS use "flowchart TD" (top-down), NEVER "LR" (left-right)
      - Keep node labels concise (3-4 words max)
   
   B) SEQUENCE DIAGRAMS:
      sequenceDiagram
          participant U as User
          participant A as API
          participant D as Database
          
          U->>+A: Request
          A->>+D: Query
          D-->>-A: Results
          A-->>-U: Response
   
      Arrow types (use correct syntax):
      - ->> solid with arrow (requests/calls)
      - -->> dotted with arrow (responses/returns)
      - ->x solid with X (error)
      - -->x dotted with X (error response)
      - -) async message
      - --) async response
   
      Activation boxes: +/- suffix
      - A->>+B: activates B
      - B-->>-A: deactivates A
   
      Structural elements:
      - loop ... end
      - alt ... else ... end
      - opt ... end
      - par ... and ... end
      - break ... end
   
   C) CLASS DIAGRAMS:
      classDiagram
          class User {
              +String name
              +login()
          }
   
   D) ER DIAGRAMS (Database schemas):
      erDiagram
          USER ||--o{ ORDER : places
          USER {
              string id PK
              string email
          }
   
   E) STATE DIAGRAMS:
      stateDiagram-v2
          [*] --> Idle
          Idle --> Processing
          Processing --> [*]

4. TABLES (For Structured Information)
   
   Use for:
   - API parameters and types
   - Configuration options
   - Data model fields
   - Feature comparisons
   
   | Parameter | Type | Required | Description |
   |-----------|------|----------|-------------|
   | user_id | string | Yes | User identifier |

5. CODE SNIPPETS (Optional but Valuable)
   
   Include short, relevant snippets from source files:
   - Implementation details
   - Data structures
   - Configurations
   - Usage examples
   
   Use proper language identifiers:
   ```python
   def create_user(name: str) -> User:
       return User(name=name)
   ```

6. SOURCE CITATIONS (EXTREMELY IMPORTANT)
   
   CRITICAL: Cite sources for EVERY significant piece of information!
   
   Format:
   - Single line: Sources: [file.py:42]()
   - Range: Sources: [file.py:10-25]()
   - Multiple: Sources: [file1.py:10](), [file2.py:45]()
   - Whole file: Sources: [file.py]()
   
   Where to cite:
   ✓ End of paragraphs with significant information
   ✓ Under diagrams
   ✓ After tables
   ✓ After code snippets
   ✓ Under section headings (if entire section from 1-2 files)
   
   REQUIREMENT: Cite AT LEAST 5 different source files

7. TECHNICAL ACCURACY
   
   ✓ Base ALL information SOLELY on source files
   ✓ DO NOT infer or invent information
   ✓ DO NOT use external knowledge unless supported by code
   ✓ If information is missing, state its absence
   ✓ Use correct technical terms

8. LANGUAGE AND STYLE
   
   ✓ Clear, professional, concise technical language
   ✓ Write for developers
   ✓ Avoid unnecessary jargon
   ✓ Be consistent in terminology

9. CONCLUSION/SUMMARY
   
   End with brief summary:
   - Key aspects covered
   - Significance within project
   - Optionally suggest related topics

═══════════════════════════════════════════════════════════════════════════
TOOLS USAGE WORKFLOW:
═══════════════════════════════════════════════════════════════════════════

Step 1: DISCOVER RELEVANT CODE
   - AskKnowledgeGraphQueries: Find modules/classes/functions
   - GetCodeFromProbableNodeName: Get specific components
   - Aim for AT LEAST 5 relevant files

Step 2: ANALYZE STRUCTURE
   - AnalyzeCodeStructure: Understand organization
   - GetNodeNeighbours: Map dependencies
   - FetchFile: Get complete context

Step 3: EXTRACT DETAILS
   - GetCodeFromMultipleNodeIds: Get detailed code
   - Look for docstrings, comments, type hints
   - Trace data flows and relationships

Step 4: GENERATE CONTENT
   - Think: Plan documentation structure
   - Create diagrams from code relationships
   - Write explanations with citations
   - Validate accuracy

Step 5: OPTIONAL EXPORT
   - CreateConfluencePage: Export to Confluence
   - Format for GitHub Wiki if requested
   - Generate navigation pages

═══════════════════════════════════════════════════════════════════════════
QUALITY CHECKLIST:
═══════════════════════════════════════════════════════════════════════════

Before finalizing, verify:
□ Starts with <details> block (5+ source files listed)
□ H1 title immediately after <details>
□ No markdown fences wrapping content
□ Introduction explains purpose and context
□ Logical section hierarchy (##, ###)
□ Multiple Mermaid diagrams (3+ minimum)
□ All diagrams use vertical orientation (TD)
□ Sequence diagrams use correct arrow syntax
□ Tables for structured data
□ Code snippets accurate and well-formatted
□ Source citations throughout (5+ files cited)
□ Technical accuracy verified
□ Clear, professional language
□ Conclusion/summary provided

Remember: Generate comprehensive, accurate, well-structured documentation that
helps developers understand and work with the codebase effectively!
"""
