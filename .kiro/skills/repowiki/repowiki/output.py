"""Output path computation and index generation for repowiki."""

from __future__ import annotations

import os
from typing import List

from .models import CodeModule


def compute_output_path(source_path: str, output_dir: str) -> str:
    """
    Replace source extension with .md and mirror directory structure under output_dir.

    e.g. src/auth/user.ts + docs -> docs/src/auth/user.md
    """
    stem, _ = os.path.splitext(source_path)
    return os.path.join(output_dir, stem + ".md")


def build_index(modules: List[CodeModule], output_dir: str, output_style: str) -> tuple[str, str]:
    """
    Build an index Markdown document.

    Returns (index_content, index_filename).
    """
    # Group by directory
    groups: dict[str, list[CodeModule]] = {}
    for module in modules:
        directory = os.path.dirname(module.path) or "."
        groups.setdefault(directory, []).append(module)

    lines: List[str] = []
    if output_style == "github-wiki":
        lines.append("# Wiki Index")
        index_filename = "_Sidebar.md"
    else:
        lines.append("# Documentation Index")
        index_filename = "README.md"

    lines.append("")

    for directory in sorted(groups.keys()):
        if directory != ".":
            lines.append(f"## {directory}")
            lines.append("")
        for module in sorted(groups[directory], key=lambda m: os.path.basename(m.path)):
            stem, _ = os.path.splitext(module.path)
            title = os.path.basename(stem)
            link_path = stem + ".md"
            lines.append(f"- [{title}]({link_path})")
        lines.append("")

    return "\n".join(lines), index_filename
