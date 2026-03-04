"""Markdown generation for repowiki."""

from __future__ import annotations

import os
from typing import List

from .models import ClassDef, CodeModule, FunctionDef, GeneratorOptions, TypeDef


def _escape(text: str) -> str:
    """Escape HTML special characters in user-supplied strings."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _module_title(path: str) -> str:
    stem, _ = os.path.splitext(os.path.basename(path))
    return stem or path


def render_function(fn: FunctionDef) -> str:
    lines: List[str] = []

    async_badge = " `async`" if fn.is_async else ""
    lines.append(f"### {_escape(fn.name)}{async_badge}")
    lines.append("")

    desc = _escape(fn.description) if fn.description else f"Function `{_escape(fn.name)}`."
    lines.append(desc)
    lines.append("")

    if fn.params:
        lines.append("| Name | Type | Description | Default |")
        lines.append("| ---- | ---- | ----------- | ------- |")
        for p in fn.params:
            lines.append(
                f"| {_escape(p.name)} | {_escape(p.type)} | {_escape(p.description)} | {_escape(p.default)} |"
            )
        lines.append("")

    if fn.returns:
        lines.append(f"**Returns:** {_escape(fn.returns)}")
        lines.append("")

    return "\n".join(lines)


def generate_markdown(module: CodeModule, options: GeneratorOptions) -> str:
    parts: List[str] = []

    title = _module_title(module.path)
    parts.append(f"# {_escape(title)}")
    parts.append("")

    if module.description:
        parts.append(_escape(module.description))
        parts.append("")

    parts.append(f"**Source:** `{module.path}`")
    parts.append("")

    if module.imports:
        parts.append("## Dependencies")
        parts.append("")
        for imp in module.imports:
            parts.append(f"- `{_escape(imp)}`")
        parts.append("")

    if module.types:
        parts.append("## Types")
        parts.append("")
        for t in module.types:
            desc = f" — {_escape(t.description)}" if t.description else ""
            parts.append(f"**`{_escape(t.name)}`**{desc}")
            parts.append("")

    for cls in module.classes:
        parts.append(f"## {_escape(cls.name)}")
        parts.append("")
        cls_desc = _escape(cls.description) if cls.description else f"Class `{_escape(cls.name)}`."
        parts.append(cls_desc)
        parts.append("")
        for method in cls.methods:
            parts.append(render_function(method))

    if module.functions:
        parts.append("## Functions")
        parts.append("")
        parts.append("Top-level functions defined in this module.")
        parts.append("")
        for fn in module.functions:
            parts.append(render_function(fn))

    return "\n".join(parts)
