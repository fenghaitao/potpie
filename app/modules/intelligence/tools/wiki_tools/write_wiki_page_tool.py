"""Tool for writing generated wiki pages to .qoder/repowiki/"""

import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from app.modules.utils.logger import setup_logger

logger = setup_logger(__name__)

# Root of the wiki relative to the workspace
WIKI_ROOT = Path(".qoder/repowiki/en/content")

VALID_SECTIONS = [
    "API Reference",
    "Architecture & Design",
    "Authentication & Security",
    "Core Modules",
    "Data Models & Persistence",
    "Deployment & Infrastructure",
    "Development Guide",
    "External Integrations",
    "Project Overview",
    "System Requirements",
    "Root",
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
    """Write a wiki page to .qoder/repowiki/en/content/<section>/[subsection/]<page_title>.md"""
    try:
        if section == "Root":
            page_dir = WIKI_ROOT
        elif subsection:
            page_dir = WIKI_ROOT / section / subsection
        else:
            page_dir = WIKI_ROOT / section

        page_dir.mkdir(parents=True, exist_ok=True)
        page_path = page_dir / f"{page_title}.md"
        page_path.write_text(content, encoding="utf-8")

        relative_path = page_path.relative_to(Path("."))
        logger.info(f"Wiki page written: {relative_path}")
        return f"✅ Wiki page written to: {relative_path}"
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
