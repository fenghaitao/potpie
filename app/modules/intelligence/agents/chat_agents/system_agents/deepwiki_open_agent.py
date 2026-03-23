"""DeepWiki Open Agent - Generate comprehensive wiki documentation using deepwiki-open workflow."""
import re
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional
from xml.etree import ElementTree as ET
from xml.etree.ElementTree import Element, SubElement, ElementTree as XmlTree
from dataclasses import dataclass
from app.modules.intelligence.agents.chat_agents.agent_config import AgentConfig, TaskConfig
from app.modules.intelligence.agents.chat_agents.pydantic_agent import PydanticRagAgent
from app.modules.intelligence.prompts.prompt_service import PromptService
from app.modules.intelligence.provider.provider_service import ProviderService
from app.modules.intelligence.tools.tool_service import ToolService
from ...chat_agent import ChatAgent, ChatAgentResponse, ChatContext
from app.modules.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class WikiPage:
    """Represents a wiki page to generate."""
    id: str
    title: str
    description: str
    file_paths: List[str]
    importance: str
    related_pages: List[str]


@dataclass
class WikiStructure:
    """Represents the complete wiki structure."""
    title: str
    description: str
    pages: List[WikiPage]


class DeepWikiOpenAgent(ChatAgent):
    """Agent for generating comprehensive wiki documentation using deepwiki-open workflow."""

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
        """Build a simple agent for structure/content generation."""
        agent_config = AgentConfig(
            role="Technical Documentation Specialist",
            goal="Generate wiki structure or page content",
            backstory="Expert technical writer creating structured documentation.",
            tasks=[
                TaskConfig(
                    description="Generate requested wiki structure or content",
                    expected_output="XML structure or markdown content",
                )
            ],
        )
        # No tools needed - agent just generates text based on prompts
        return PydanticRagAgent(self.llm_provider, agent_config, [])

    async def _get_repo_structure(self, ctx: ChatContext) -> str:
        """Get file structure and README, create wiki structure prompt."""
        # Get file structure
        file_structure = await self.tools_provider.file_structure_tool.fetch_repo_structure(ctx.project_id)
        
        # Get README content if provided in context
        readme_content = ""
        if ctx.additional_context and "README Content:" in ctx.additional_context:
            readme_content = ctx.additional_context.split("README Content:")[1].strip()
        
        # Create wiki structure prompt (from repo_wiki_gen.py)
        # Default page count for a standard wiki
        pages_count = '8-12'

        # Allow overrides from context (e.g., CLI flags or additional metadata)
        # 1) Explicit pages_count in additional_context, e.g. "pages_count=4-6"
        if getattr(ctx, "additional_context", None):
            match = re.search(r"pages_count\s*=\s*([0-9]+(?:\s*-\s*[0-9]+)?)", ctx.additional_context)
            if match:
                pages_count = match.group(1)
            # 2) Concise mode marker in additional_context, e.g. "mode=concise"
            elif re.search(r"\bmode\s*=\s*concise\b", ctx.additional_context, re.IGNORECASE):
                pages_count = '4-6'

        # 3) Concise mode marker in the query itself, e.g. a CLI flag "--concise"
        if hasattr(ctx, "query") and ctx.query and "--concise" in ctx.query:
            pages_count = '4-6'
        
        structure_section = '''
Create a structured wiki with the following main sections:
- Overview (general information about the project)
- System Architecture (how the system is designed)
- Core Features (key functionality)
- Data Management/Flow (how data is stored, processed, and managed)
- Frontend Components (UI elements, if applicable)
- Backend Systems (server-side components)
- Model Integration (AI model connections, if applicable)
- Deployment/Infrastructure (how to deploy)
- Extensibility and Customization (how to extend functionality)

Return your analysis in the following XML format:

<wiki_structure>
  <title>[Overall title for the wiki]</title>
  <description>[Brief description of the repository]</description>
  <pages>
    <page id="page-1">
      <title>[Page title]</title>
      <description>[Brief description of what this page will cover]</description>
      <importance>high|medium|low</importance>
      <relevant_files>
        <file_path>[Path to a relevant file]</file_path>
      </relevant_files>
      <related_pages>
        <related>page-2</related>
      </related_pages>
    </page>
  </pages>
</wiki_structure>
'''
        
        prompt = f'''Analyze this repository and create a wiki structure for it.

1. The complete file tree of the project:
<file_tree>
{file_structure}
</file_tree>

2. The README file of the project:
<readme>
{readme_content if readme_content else "No README provided"}
</readme>

I want to create a wiki for this repository. Determine the most logical structure for a wiki based on the repository's content.

{structure_section}

IMPORTANT FORMATTING INSTRUCTIONS:
- Return ONLY the valid XML structure specified above
- DO NOT wrap the XML in markdown code blocks (no ``` or ```xml)
- DO NOT include any explanation text before or after the XML
- Ensure the XML is properly formatted and valid
- Start directly with <wiki_structure> and end with </wiki_structure>
- Avoid using ampersands (&) or the abbreviation "Q&A" in any titles

IMPORTANT:
1. Create {pages_count} pages that would make a comprehensive wiki
2. Each page should focus on a specific aspect of the codebase
3. The relevant_files should be actual files from the repository
4. Return ONLY valid XML with the structure specified above'''
        
        return prompt

    def _parse_wiki_structure(self, xml_text: str) -> Optional[WikiStructure]:
        """Parse XML response to extract wiki structure."""
        try:
            # Clean up control characters
            xml_text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', xml_text)
            # Strip any markdown code fences (```xml ... ``` or ``` ... ```) anywhere in text
            xml_text = re.sub(r'```(?:xml)?\s*', '', xml_text, flags=re.IGNORECASE)

            # Extract XML
            match = re.search(r'<wiki_structure>[\s\S]*</wiki_structure>', xml_text)
            if not match:
                logger.error(
                    'No valid XML found in response. Raw response (first 500 chars): %s',
                    xml_text[:500]
                )
                return None
            
            xml_text = match.group(0)
            root = ET.fromstring(xml_text)
            
            title = root.findtext('title', '')
            description = root.findtext('description', '')
            
            pages = []
            pages_elem = root.find('pages')
            page_elements = pages_elem.findall('page') if pages_elem is not None else root.findall('page')
            
            for page_elem in page_elements:
                page_id = page_elem.get('id', f'page-{len(pages) + 1}')
                page_title = page_elem.findtext('title', '')
                page_desc = page_elem.findtext('description', '')
                importance = page_elem.findtext('importance', 'medium')
                
                if importance not in ['high', 'medium', 'low']:
                    importance = 'medium'
                
                file_paths = []
                relevant_files = page_elem.find('relevant_files')
                if relevant_files is not None:
                    for file_path_elem in relevant_files.findall('file_path'):
                        if file_path_elem.text:
                            file_paths.append(file_path_elem.text)
                
                related_pages = []
                related_pages_elem = page_elem.find('related_pages')
                if related_pages_elem is not None:
                    for related_elem in related_pages_elem.findall('related'):
                        if related_elem.text:
                            related_pages.append(related_elem.text)
                
                pages.append(WikiPage(
                    id=page_id,
                    title=page_title,
                    description=page_desc,
                    file_paths=file_paths,
                    importance=importance,
                    related_pages=related_pages
                ))
            
            return WikiStructure(title=title, description=description, pages=pages)
            
        except Exception as e:
            logger.error(f"Error parsing wiki structure XML: {e}")
            return None

    def _get_code_content_for_page(self, ctx: ChatContext, page: WikiPage) -> str:
        """Get code content for a page using existing tools."""
        # Use fetch_files_batch to read relevant files
        import asyncio
        
        file_contents = []
        if page.file_paths:
            # Batch read files (max 20 at a time)
            batch_size = 20
            for i in range(0, len(page.file_paths), batch_size):
                batch = page.file_paths[i:i+batch_size]
                try:
                    from app.modules.intelligence.tools.code_query_tools.get_file_content_by_path import FetchFilesBatchTool
                    tool = FetchFilesBatchTool(self.tools_provider.db, self.tools_provider.user_id)
                    result = tool._run(ctx.project_id, batch, with_line_numbers=True)
                    
                    if result.get('success'):
                        for file_data in result.get('files', []):
                            if 'content' in file_data:
                                file_contents.append(f"File: {file_data['path']}\n{file_data['content']}\n")
                except Exception as e:
                    logger.warning(f"Failed to fetch files: {e}")
        
        # Create page content prompt (from repo_wiki_gen.py)
        file_links = '\n'.join([f"- [{path}]({path})" for path in page.file_paths])
        
        prompt = f'''You are an expert technical writer.
Generate a comprehensive wiki page in Markdown format.

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

{file_links}
</details>

# {page.title}

Based on the provided source files, create comprehensive documentation covering:

1. **Introduction:** Explain the purpose and scope of "{page.title}"

2. **Detailed Sections:** Break down into logical sections with H2/H3 headings

3. **Mermaid Diagrams:** Use flowchart TD, sequenceDiagram, classDiagram to visualize:
   - Architecture and data flow
   - Component relationships
   - Process workflows
   
   CRITICAL diagram rules:
   - Always use "flowchart TD" (top-down), NEVER "graph LR"
   - For sequence diagrams: use ->> for calls, -->> for responses
   - Define all participants at the beginning

4. **Tables:** Summarize key information (parameters, configs, data models)

5. **Code Snippets:** Include relevant examples from source files

6. **Source Citations:** Cite every piece of information as: Sources: [filename.ext:line]()

7. **Technical Accuracy:** Base everything on the provided source files only

8. **Conclusion:** Brief summary of key aspects

IMPORTANT FORMATTING INSTRUCTIONS:
- DO NOT wrap the output in ```markdown fences. Write raw markdown directly.
- Start directly with the content (e.g. a heading), not a code block.

RELEVANT SOURCE FILES CONTENT:
{chr(10).join(file_contents) if file_contents else "No file content available"}

PAGE DESCRIPTION: {page.description}

Generate the complete markdown content now.'''
        
        return prompt

    async def run(self, ctx: ChatContext) -> ChatAgentResponse:
        """Generate wiki in two phases: structure then pages."""
        agent = self._build_agent()
        
        # Phase 1: Generate wiki structure
        logger.info("Phase 1: Generating wiki structure...")
        structure_prompt = await self._get_repo_structure(ctx)
        structure_ctx = ChatContext(
            project_id=ctx.project_id,
            project_name=ctx.project_name,
            curr_agent_id=ctx.curr_agent_id,
            query=structure_prompt,
            history=[],
            user_id=ctx.user_id,
        )
        
        structure_response = await agent.run(structure_ctx)
        wiki_structure = self._parse_wiki_structure(structure_response.response)
        
        if not wiki_structure:
            return ChatAgentResponse(
                response="Failed to generate wiki structure. Please try again.",
                tool_calls=[],
                citations=[]
            )
        
        logger.info(f"Generated structure with {len(wiki_structure.pages)} pages")
        
        # Phase 2: Generate each page
        all_responses = [f"# {wiki_structure.title}\n\n{wiki_structure.description}\n\n"]
        all_responses.append(f"Generating {len(wiki_structure.pages)} wiki pages...\n\n")
        
        for idx, page in enumerate(wiki_structure.pages, 1):
            logger.info(f"Phase 2: Generating page {idx}/{len(wiki_structure.pages)}: {page.title}")
            
            page_prompt = self._get_code_content_for_page(ctx, page)
            page_ctx = ChatContext(
                project_id=ctx.project_id,
                project_name=ctx.project_name,
                curr_agent_id=ctx.curr_agent_id,
                query=page_prompt,
                history=[],
                user_id=ctx.user_id,
            )
            
            page_response = await agent.run(page_ctx)
            
            # Write page using write_wiki_page tool
            try:
                from app.modules.intelligence.tools.wiki_tools.write_wiki_page_tool import _write_wiki_page
                section = self._to_filename(self._map_to_section(page.title))
                result = _write_wiki_page(
                    section=section,
                    page_title=self._to_filename(page.title),
                    content=page_response.response,
                )
                all_responses.append(f"{idx}. {result}\n")
            except Exception as e:
                logger.error(f"Failed to write page {page.title}: {e}")
                all_responses.append(f"{idx}. ❌ Failed to write {page.title}: {e}\n")

        # Write wiki_structure.xml
        try:
            xml_path = self._write_wiki_structure_xml(wiki_structure)
            all_responses.append(f"\n📋 Wiki structure saved to: {xml_path}\n")
        except Exception as e:
            logger.error(f"Failed to write wiki_structure.xml: {e}")

        return ChatAgentResponse(
            response=''.join(all_responses),
            tool_calls=[],
            citations=[]
        )

    async def run_stream(self, ctx: ChatContext) -> AsyncGenerator[ChatAgentResponse, None]:
        """Stream wiki generation progress."""
        agent = self._build_agent()
        
        # Phase 1: Generate wiki structure
        yield ChatAgentResponse(response="📊 Phase 1: Analyzing repository structure...\n", tool_calls=[], citations=[])
        
        structure_prompt = await self._get_repo_structure(ctx)
        structure_ctx = ChatContext(
            project_id=ctx.project_id,
            project_name=ctx.project_name,
            curr_agent_id=ctx.curr_agent_id,
            query=structure_prompt,
            history=[],
            user_id=ctx.user_id,
        )
        
        structure_response = await agent.run(structure_ctx)
        wiki_structure = self._parse_wiki_structure(structure_response.response)
        
        if not wiki_structure:
            yield ChatAgentResponse(response="❌ Failed to generate wiki structure\n", tool_calls=[], citations=[])
            return
        
        yield ChatAgentResponse(
            response=f"✅ Generated structure: {wiki_structure.title}\n📝 Planning {len(wiki_structure.pages)} pages\n\n",
            tool_calls=[],
            citations=[]
        )
        
        # Phase 2: Generate each page
        for idx, page in enumerate(wiki_structure.pages, 1):
            yield ChatAgentResponse(
                response=f"📄 [{idx}/{len(wiki_structure.pages)}] Generating: {page.title}...\n",
                tool_calls=[],
                citations=[]
            )
            
            page_prompt = self._get_code_content_for_page(ctx, page)
            page_ctx = ChatContext(
                project_id=ctx.project_id,
                project_name=ctx.project_name,
                curr_agent_id=ctx.curr_agent_id,
                query=page_prompt,
                history=[],
                user_id=ctx.user_id,
            )
            
            page_response = await agent.run(page_ctx)
            
            # Write page
            try:
                from app.modules.intelligence.tools.wiki_tools.write_wiki_page_tool import _write_wiki_page
                section = self._to_filename(self._map_to_section(page.title))
                result = _write_wiki_page(
                    section=section,
                    page_title=self._to_filename(page.title),
                    content=page_response.response,
                )
                yield ChatAgentResponse(response=f"   {result}\n", tool_calls=[], citations=[])
            except Exception as e:
                logger.error(f"Failed to write page {page.title}: {e}")
                yield ChatAgentResponse(response=f"   ❌ Failed: {e}\n", tool_calls=[], citations=[])

        # Write wiki_structure.xml
        try:
            xml_path = self._write_wiki_structure_xml(wiki_structure)
            yield ChatAgentResponse(
                response=f"\n📋 Wiki structure saved to: {xml_path}\n",
                tool_calls=[], citations=[]
            )
        except Exception as e:
            logger.error(f"Failed to write wiki_structure.xml: {e}")

        yield ChatAgentResponse(response=f"\n🎉 Wiki generation complete!\n", tool_calls=[], citations=[])

    @staticmethod
    def _to_filename(text: str) -> str:
        """Convert arbitrary text to a filesystem-safe filename.

        Only allow alphanumeric characters, hyphens, and underscores.
        All other characters (including path separators and dots) are replaced
        with a single underscore. If the result is empty, return 'untitled'.
        """
        # Replace any sequence of disallowed characters with a single underscore
        safe = re.sub(r'[^A-Za-z0-9_-]+', '_', text)
        # Trim leading/trailing underscores
        safe = safe.strip('_')
        # Fallback to a safe default if nothing remains
        if not safe:
            safe = "untitled"
        return safe

    def _write_wiki_structure_xml(self, wiki_structure: WikiStructure) -> str:
        """Write wiki_structure.xml to .repowiki/ matching the deepwiki-open format."""
        import os
        env_dir = os.environ.get("POTPIE_WIKI_OUTPUT_DIR")
        # POTPIE_WIKI_OUTPUT_DIR points to the content dir (en/content);
        # wiki_structure.xml lives two levels up at the wiki root.
        wiki_root = Path(env_dir).parent.parent if env_dir else Path(".repowiki")
        wiki_root.mkdir(parents=True, exist_ok=True)

        # Group page ids by their mapped section title (preserving insertion order)
        section_map: Dict[str, List[str]] = {}
        for page in wiki_structure.pages:
            section_title = self._map_to_section(page.title)
            section_map.setdefault(section_title, []).append(page.id)

        section_id_map = {
            title: f"section-{i + 1}" for i, title in enumerate(section_map)
        }

        root = Element('wiki_structure')
        title_elem = SubElement(root, 'title')
        title_elem.text = wiki_structure.title
        desc_elem = SubElement(root, 'description')
        desc_elem.text = wiki_structure.description

        sections_elem = SubElement(root, 'sections')
        for section_title, page_ids in section_map.items():
            sec_elem = SubElement(sections_elem, 'section',
                                  id=section_id_map[section_title])
            sec_title_elem = SubElement(sec_elem, 'title')
            sec_title_elem.text = section_title
            sec_pages = SubElement(sec_elem, 'pages')
            for pid in page_ids:
                page_ref = SubElement(sec_pages, 'page_ref')
                page_ref.text = pid
            SubElement(sec_elem, 'subsections')

        pages_list = SubElement(root, 'pages')
        for page in wiki_structure.pages:
            section_title = self._map_to_section(page.title)
            page_elem = SubElement(pages_list, 'page', id=page.id)
            SubElement(page_elem, 'title').text = page.title
            SubElement(page_elem, 'description').text = page.description
            SubElement(page_elem, 'importance').text = page.importance
            rf_elem = SubElement(page_elem, 'relevant_files')
            for fp in page.file_paths:
                SubElement(rf_elem, 'file_path').text = fp
            rp_elem = SubElement(page_elem, 'related_pages')
            for rp in page.related_pages:
                SubElement(rp_elem, 'related').text = rp
            SubElement(page_elem, 'parent_section').text = section_id_map[section_title]

        try:
            ET.indent(root, space='  ')  # Python 3.9+
        except AttributeError:
            pass

        xml_path = wiki_root / "wiki_structure.xml"
        XmlTree(root).write(str(xml_path), encoding='unicode', xml_declaration=False)
        logger.info(f"Wiki structure written to {xml_path}")
        return str(xml_path)

    def _map_to_section(self, page_title: str) -> str:
        """Map page title to valid wiki section."""
        title_lower = page_title.lower()
        
        if any(kw in title_lower for kw in ['overview', 'introduction', 'readme', 'getting started']):
            return "Project Overview"
        elif any(kw in title_lower for kw in ['architecture', 'design', 'system']):
            return "Core Architecture"
        elif any(kw in title_lower for kw in ['api', 'endpoint', 'interface']):
            return "API Reference"
        elif any(kw in title_lower for kw in ['auth', 'security', 'permission']):
            return "Authentication & Authorization"
        elif any(kw in title_lower for kw in ['data', 'database', 'model', 'schema']):
            return "Data Management"
        elif any(kw in title_lower for kw in ['deploy', 'infrastructure', 'docker', 'kubernetes']):
            return "Deployment & Operations"
        elif any(kw in title_lower for kw in ['integration', 'external', 'third-party']):
            return "External Integrations"
        elif any(kw in title_lower for kw in ['agent', 'intelligence', 'ai', 'ml']):
            return "Intelligence Engine"
        elif any(kw in title_lower for kw in ['parse', 'graph', 'knowledge']):
            return "Code Parsing & Knowledge Graph"
        elif any(kw in title_lower for kw in ['conversation', 'chat', 'message']):
            return "Conversations & Messaging"
        else:
            return "Project Overview"
