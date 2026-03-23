"""Tool for writing generated wiki pages to .qoder/repowiki/"""

import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from app.modules.utils.logger import setup_logger

logger = setup_logger(__name__)

# Root of the wiki — overridden by POTPIE_WIKI_OUTPUT_DIR env var when set
# (used by the VS Code extension to write to a controlled workspace location)
def _get_wiki_root() -> Path:
    env_dir = os.environ.get("POTPIE_WIKI_OUTPUT_DIR")
    return Path(env_dir) if env_dir else Path(".repowiki/en/content")

VALID_SECTIONS = [
    "API Reference",
    "Authentication & Authorization",
    "Code Parsing & Knowledge Graph",
    "Conversations & Messaging",
    "Core Architecture",
    "Data Management",
    "Deployment & Operations",
    "External Integrations",
    "Intelligence Engine",
    "Project Overview",
]


class WriteWikiPageInput(BaseModel):
    section: str = Field(
        ...,
        description=(
            "Top-level section folder. Must be one of: "
            + ", ".join(f'"{s}"' for s in VALID_SECTIONS)
        ),
    )
    subsection: Optional[str] = Field(
        default=None,
        description=(
            "Optional sub-folder inside the section, e.g. 'System Agents' inside "
            "'Intelligence Engine'. Leave empty to write directly into the section folder."
        ),
    )
    page_title: str = Field(
        ...,
        description="Page filename without the .md extension, e.g. 'Wiki Agent'",
    )
    content: str = Field(
        ...,
        description="Full markdown content of the wiki page",
    )


def _write_wiki_page(
    section: str,
    page_title: str,
    content: str,
    subsection: Optional[str] = None,
) -> str:
    """Write a wiki page to <WIKI_ROOT>/<section>/[subsection/]<page_title>.md"""
    try:
        wiki_root = _get_wiki_root()
        if subsection:
            page_dir = wiki_root / section / subsection
        else:
            page_dir = wiki_root / section

        page_dir.mkdir(parents=True, exist_ok=True)
        page_path = page_dir / f"{page_title}.md"
        page_path.write_text(content, encoding="utf-8")

        try:
            # Compute a display-friendly relative path; this works even if wiki_root
            # is outside the current working directory. Fall back to the full path
            # if a relative path cannot be determined (e.g., cross-drive on Windows).
            relative_path_str = os.path.relpath(page_path)
        except Exception:
            relative_path_str = str(page_path)

        logger.info(f"Wiki page written: {relative_path_str}")
        return f"✅ Wiki page written to: {relative_path_str}"
    except Exception as e:
        logger.error(f"Failed to write wiki page '{page_title}': {e}")
        return f"❌ Failed to write wiki page: {e}"


def get_write_wiki_page_tool() -> StructuredTool:
    return StructuredTool.from_function(
        func=_write_wiki_page,
        name="write_wiki_page",
        description=(
            "Write a generated wiki page as a Markdown file into the .qoder/repowiki directory. "
            "Use this after generating wiki content to persist it to disk. "
            f"Valid sections: {', '.join(VALID_SECTIONS)}"
        ),
        args_schema=WriteWikiPageInput,
    )
