"""
DeepWiki Docs Parser

Ports parse_official_docs.py from CodeWikiBench to the wiki-evaluator skill.

Parses a directory of markdown files (e.g. downloaded via `deepwiki-export`)
into two output artefacts that mirror the CodeWikiBench pipeline:

  - ``docs_tree.json``      — lightweight key/title tree (used for rubric generation)
  - ``structured_docs.json``— full content tree (used for evaluation context)

The heavy ``markdown_to_json`` conversion is used for structured content, with a
plain-text fallback so the module is usable even when the package is absent.

Usage::

    from deepwiki_docs_parser import parse_docs_directory

    root_page, docs_tree = parse_docs_directory(
        path="/path/to/wiki_dir",
        project_name="my-repo",
        output_dir="/path/to/output",
    )

Copyright 2025 Intel Corporation
Licensed under the Apache License, Version 2.0
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

try:
    import markdown_to_json as _m2j
    _M2J_AVAILABLE = True
except ImportError:
    _M2J_AVAILABLE = False


# ---------------------------------------------------------------------------
# JSON serialiser
# ---------------------------------------------------------------------------

def _json_default(obj: Any) -> Any:
    """Custom JSON serialiser for date/datetime objects."""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serialisable")


# ---------------------------------------------------------------------------
# DocPage dataclass (mirrors CodeWikiBench DocPage Pydantic model)
# ---------------------------------------------------------------------------

class DocPage:
    """Lightweight dataclass mirroring CodeWikiBench's DocPage Pydantic model."""

    __slots__ = ("title", "description", "content", "metadata", "subpages")

    def __init__(
        self,
        title: Optional[str] = None,
        description: Optional[str] = None,
        content: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        subpages: Optional[List["DocPage"]] = None,
    ):
        self.title = title
        self.description = description
        self.content: Dict[str, Any] = content or {}
        self.metadata: Dict[str, Any] = metadata or {}
        self.subpages: List["DocPage"] = subpages or []

    def to_dict(self, path: Optional[List] = None) -> Dict[str, Any]:
        """Recursively convert to a plain dict (structured_docs format)."""
        path = path or []
        result: Dict[str, Any] = {}
        if self.title:
            result["title"] = self.title
        if self.description:
            result["description"] = self.description
        if path:
            result["path"] = json.dumps(path, default=_json_default)
        if self.content:
            result["content"] = self.content
        if self.metadata:
            result["metadata"] = self.metadata
        if self.subpages:
            result["subpages"] = [
                sp.to_dict(path + ["subpages", i])
                for i, sp in enumerate(self.subpages)
            ]
        return result

    def to_tree(self, path: Optional[List] = None) -> Dict[str, Any]:
        """
        Recursively convert to a lightweight key-tree (docs_tree format).
        String values are replaced with ``"<detail_content>"`` placeholders,
        matching CodeWikiBench's ``generate_detailed_keys_tree`` output.
        """
        path = path or []
        result: Dict[str, Any] = {}
        if self.title:
            result["title"] = self.title
        if self.description:
            result["description"] = "<detail_content>"
        if path:
            result["path"] = json.dumps(path, default=_json_default)
        if self.content:
            result["content"] = _tree_value(self.content, path)
        if self.subpages:
            result["subpages"] = [
                sp.to_tree(path + ["subpages", i])
                for i, sp in enumerate(self.subpages)
            ]
        return result


def _tree_value(obj: Any, path: List) -> Any:
    """Recursively collapse values to ``<detail_content>`` placeholders."""
    if isinstance(obj, str):
        return "<detail_content>"
    if isinstance(obj, (int, float, bool)):
        return f"<{type(obj).__name__}>"
    if obj is None:
        return None
    if isinstance(obj, list):
        if not obj:
            return []
        if isinstance(obj[0], str):
            return "<detail_content>"
        return [_tree_value(item, path + [i]) for i, item in enumerate(obj)]
    if isinstance(obj, dict):
        result: Dict[str, Any] = {}
        for key, value in obj.items():
            if key == "On this page":
                continue
            result[key] = _tree_value(value, path)
        return result
    return f"<{type(obj).__name__}>"


# ---------------------------------------------------------------------------
# Frontmatter parser
# ---------------------------------------------------------------------------

def _parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """Split YAML frontmatter from markdown body."""
    frontmatter: Dict[str, Any] = {}
    body = content

    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            if _YAML_AVAILABLE:
                try:
                    frontmatter = yaml.safe_load(parts[1]) or {}
                    body = parts[2].strip()
                except Exception:
                    pass
            else:
                body = parts[2].strip()

    return frontmatter, body


# ---------------------------------------------------------------------------
# Single file parser
# ---------------------------------------------------------------------------

def parse_markdown_file(file_path: str) -> DocPage:
    """
    Parse a single markdown file into a DocPage.

    Mirrors ``parse_markdown_file`` from parse_official_docs.py.
    Uses ``markdown_to_json`` when available; falls back to storing raw text.
    """
    with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
        raw = fh.read()

    frontmatter, body = _parse_frontmatter(raw)

    # Remove <details>…</details> blocks (deepwiki "Relevant source files" boxes)
    body = re.sub(r"<details>.*?</details>", "", body, flags=re.DOTALL).strip()

    # Convert markdown to structured JSON if possible
    if _M2J_AVAILABLE:
        try:
            content_json: Dict[str, Any] = json.loads(_m2j.jsonify(body))
        except Exception:
            content_json = {"content": body}
    else:
        content_json = {"content": body}

    # Strip "On this page" navigation sections
    if isinstance(content_json, dict) and "On this page" in content_json:
        del content_json["On this page"]

    # Extract title: frontmatter → top-level key → filename
    title: Optional[str] = frontmatter.get("title")
    if not title and isinstance(content_json, dict):
        for key in content_json:
            if isinstance(content_json[key], dict):
                title = key
                content_json = content_json[key]
                break
    if not title:
        title = (
            Path(file_path).stem
            .replace("-", " ")
            .replace("_", " ")
            .title()
        )

    return DocPage(
        title=title,
        description=frontmatter.get("description"),
        content=content_json,
        metadata=frontmatter,
    )


# ---------------------------------------------------------------------------
# Directory parser
# ---------------------------------------------------------------------------

def parse_docs_directory(
    path: str,
    project_name: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> Tuple[DocPage, Dict[str, Any]]:
    """
    Parse a directory of markdown files into docs_tree + structured_docs.

    Mirrors ``parse_docs_directory`` from parse_official_docs.py.

    Args:
        path:         Directory containing ``.md`` / ``.mdx`` files.
        project_name: Display name for the root page (defaults to dir name).
        output_dir:   Where to write ``docs_tree.json`` and
                      ``structured_docs.json``.  Defaults to ``path``.

    Returns:
        ``(root_page, docs_tree_dict)``
    """
    path = str(Path(path).resolve())
    if output_dir is None:
        output_dir = path
    if project_name is None:
        project_name = Path(path).name

    root = DocPage(
        title=project_name,
        description=f"Documentation for {project_name}",
        metadata={"type": "root", "path": path},
    )

    _process_directory(path, root)

    docs_tree = root.to_tree()
    structured_docs = root.to_dict()

    # Write output files
    os.makedirs(output_dir, exist_ok=True)
    _write_json(os.path.join(output_dir, "docs_tree.json"), docs_tree)
    _write_json(os.path.join(output_dir, "structured_docs.json"), structured_docs)

    print(f"[docs-parser] Parsed {len(root.subpages)} top-level pages from {path}")
    print(f"[docs-parser] Wrote docs_tree.json + structured_docs.json → {output_dir}")

    return root, docs_tree


def _process_directory(dir_path: str, parent: DocPage) -> None:
    """Recursively parse all markdown files and subdirectories."""
    try:
        entries = os.listdir(dir_path)
    except (PermissionError, FileNotFoundError):
        return

    md_files = sorted(
        (e, os.path.join(dir_path, e))
        for e in entries
        if os.path.isfile(os.path.join(dir_path, e))
        and (e.endswith(".md") or e.endswith(".mdx"))
    )
    subdirs = sorted(
        (e, os.path.join(dir_path, e))
        for e in entries
        if os.path.isdir(os.path.join(dir_path, e))
        and not e.startswith(".")
    )

    for filename, file_path in md_files:
        try:
            page = parse_markdown_file(file_path)
            parent.subpages.append(page)
        except Exception as exc:
            print(f"[docs-parser] WARN: Could not parse {file_path}: {exc}")

    for dirname, subdir_path in subdirs:
        dir_page = DocPage(
            title=dirname.replace("-", " ").replace("_", " ").title(),
            description=f"Documentation section: {dirname}",
            metadata={"type": "directory", "path": subdir_path},
        )
        _process_directory(subdir_path, dir_page)
        if dir_page.subpages:
            parent.subpages.append(dir_page)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, default=_json_default)


def get_docs_tree_summary(docs_tree: Dict[str, Any], max_chars: int = 12_000) -> str:
    """
    Return a compact text summary of the docs_tree suitable for LLM prompts.

    Walks the tree and collects titles, truncating to ``max_chars``.
    """
    lines: List[str] = []

    def _walk(node: Any, depth: int = 0) -> None:
        if isinstance(node, dict):
            title = node.get("title", "")
            if title:
                lines.append("  " * depth + f"- {title}")
            for sub in node.get("subpages", []):
                _walk(sub, depth + 1)
        elif isinstance(node, list):
            for item in node:
                _walk(item, depth)

    _walk(docs_tree)
    summary = "\n".join(lines)
    if len(summary) > max_chars:
        summary = summary[:max_chars] + "\n...(truncated)"
    return summary
