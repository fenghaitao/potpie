"""Tool for listing existing wiki pages in .qoder/repowiki/"""

import os
from pathlib import Path
from typing import List, Dict, Any
from pydantic import BaseModel
from langchain_core.tools import StructuredTool
from app.modules.utils.logger import setup_logger

logger = setup_logger(__name__)

# Root of the wiki relative to the workspace
WIKI_ROOT = Path(".qoder/repowiki/en/content")

class ListWikiPagesInput(BaseModel):
    pass

def _list_wiki_pages() -> Dict[str, Any]:
    """List all wiki pages currently present in .qoder/repowiki/en/content/"""
    try:
        if not WIKI_ROOT.exists():
            return {
                "success": True,
                "message": "Wiki directory does not exist yet.",
                "pages": []
            }

        pages = []
        for path in WIKI_ROOT.rglob("*.md"):
            if path.is_file():
                # Get path relative to WIKI_ROOT
                rel_path = path.relative_to(WIKI_ROOT)
                pages.append(str(rel_path))

        return {
            "success": True,
            "count": len(pages),
            "pages": sorted(pages)
        }
    except Exception as e:
        logger.error(f"Failed to list wiki pages: {e}")
        return {"success": False, "error": str(e)}

def get_list_wiki_pages_tool() -> StructuredTool:
    return StructuredTool.from_function(
        func=_list_wiki_pages,
        name="list_wiki_pages",
        description=(
            "List all existing wiki pages in the .qoder/repowiki directory. "
            "Use this to see what documentation has already been generated, "
            "helping to avoid duplication and enabling cross-linking between pages."
        ),
        args_schema=ListWikiPagesInput,
    )
