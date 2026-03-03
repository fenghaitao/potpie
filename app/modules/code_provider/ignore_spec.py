"""
Shared utility for loading .gitignore and .potpieignore patterns into a
single PathSpec that can be used for file filtering across the codebase.
"""

import logging
import os
from typing import Optional

import pathspec

logger = logging.getLogger(__name__)

# Extra patterns always excluded regardless of ignore files
_ALWAYS_EXCLUDE = [
    ".git",
    "__pycache__",
    "*.pyc",
    "node_modules",
    ".DS_Store",
]


def load_ignore_spec(repo_path: str) -> Optional[pathspec.PathSpec]:
    """
    Load .gitignore and .potpieignore from repo_path and merge into one PathSpec.

    Always appends a set of common exclusions (.git, __pycache__, etc.).

    Args:
        repo_path: Absolute path to the repository root.

    Returns:
        A PathSpec combining all patterns, or None if no ignore files exist
        and no always-exclude patterns apply (in practice always returns a
        PathSpec because _ALWAYS_EXCLUDE is non-empty).
    """
    patterns: list[str] = list(_ALWAYS_EXCLUDE)

    for filename in (".gitignore", ".potpieignore"):
        ignore_path = os.path.join(repo_path, filename)
        if not os.path.exists(ignore_path):
            continue
        try:
            with open(ignore_path, "r", encoding="utf-8") as f:
                patterns.extend(f.read().splitlines())
        except Exception as e:
            logger.warning(f"Error reading {filename}: {e}")

    return pathspec.PathSpec.from_lines("gitwildmatch", patterns)
