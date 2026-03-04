"""Source file discovery for repowiki."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from .models import SourceFile

SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".h": "cpp",
}

EXCLUDED_DIRS = {"node_modules", "__pycache__", "dist", "build", ".venv"}


def _is_excluded(path: Path) -> bool:
    """Return True if any component of the path is an excluded directory."""
    return any(part in EXCLUDED_DIRS for part in path.parts)


def _get_language(path: Path) -> Optional[str]:
    return SUPPORTED_EXTENSIONS.get(path.suffix.lower())


def _is_gitignored(path: Path, repo_root: Path) -> bool:
    """Best-effort check: skip .gitignore parsing for now (agent handles it)."""
    return False


def discover_sources(target: str, repo_root: Optional[str] = None) -> List[SourceFile]:
    """
    Recursively discover supported source files under *target*.

    Skips excluded directories, respects supported extensions, and returns
    results sorted by (directory, filename).
    """
    root = Path(repo_root) if repo_root else Path(".")
    target_path = Path(target)

    if not target_path.exists():
        raise FileNotFoundError(f"target '{target}' does not exist")

    results: List[SourceFile] = []

    if target_path.is_file():
        lang = _get_language(target_path)
        if lang:
            results.append(SourceFile(path=str(target_path), language=lang))
        return results

    for dirpath, dirnames, filenames in os.walk(target_path, followlinks=False):
        # Prune excluded dirs in-place so os.walk won't descend into them
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]

        for filename in filenames:
            full = Path(dirpath) / filename
            # Skip symlinks that escape the repo root
            if full.is_symlink():
                try:
                    resolved = full.resolve()
                    if not str(resolved).startswith(str(root.resolve())):
                        continue
                except OSError:
                    continue

            lang = _get_language(full)
            if lang is None:
                continue

            rel = full.relative_to(Path(".")) if full.is_absolute() else full
            results.append(SourceFile(path=str(rel), language=lang))

    results.sort(key=lambda sf: (os.path.dirname(sf.path), os.path.basename(sf.path)))
    return results
