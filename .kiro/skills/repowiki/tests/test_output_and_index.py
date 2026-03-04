"""
Property-based tests for repowiki output path computation and index generation.

Tests compute_output_path and build_index from repowiki.output using the
hypothesis library.

Dependencies: hypothesis, pytest
"""

from __future__ import annotations

import os
import re
from typing import List

from hypothesis import given, settings
from hypothesis import strategies as st

from repowiki.models import CodeModule
from repowiki.output import build_index, compute_output_path

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_path_component = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="-_"),
    min_size=1,
    max_size=16,
)

_path_prefix = st.lists(_path_component, min_size=0, max_size=3).map(
    lambda parts: "/".join(parts) + "/" if parts else ""
)

_supported_ext = st.sampled_from([".py", ".ts", ".tsx", ".cpp", ".cc", ".cxx", ".hpp", ".h"])

_source_path_strategy = st.builds(
    lambda prefix, stem, ext: f"{prefix}{stem}{ext}",
    prefix=_path_prefix,
    stem=_path_component,
    ext=_supported_ext,
)

_output_dir_strategy = st.builds(
    lambda parts: "/".join(parts) if parts else "docs",
    parts=st.lists(_path_component, min_size=1, max_size=3),
)

_style_strategy = st.sampled_from(["github-wiki", "docs-folder"])

_short_text = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd", "Zs"), whitelist_characters=" _-.,"),
    min_size=0,
    max_size=50,
)

_code_module_strategy = st.builds(
    CodeModule,
    path=_source_path_strategy,
    language=st.sampled_from(["python", "typescript", "cpp"]),
    description=_short_text,
)


# ---------------------------------------------------------------------------
# Property 5: Output path is under output directory with .md extension
# Validates: Requirements 4.1, 4.2, 4.3
# ---------------------------------------------------------------------------

@given(_source_path_strategy, _output_dir_strategy, _style_strategy)
@settings(max_examples=200)
def test_property_5_output_path_under_output_dir(
    source_path: str, output_dir: str, style: str
) -> None:
    """
    **Validates: Requirements 4.1, 4.2, 4.3**

    For any source path and output directory:
      1. The result starts with output_dir
      2. The result ends with .md
      3. The source directory structure is mirrored in the output path
    """
    result = compute_output_path(source_path, output_dir)

    norm_result = result.replace("\\", "/")
    norm_output_dir = output_dir.replace("\\", "/")
    assert norm_result.startswith(norm_output_dir), (
        f"Output path {result!r} does not start with output_dir {output_dir!r}.\n"
        f"  source_path={source_path!r}"
    )

    assert result.endswith(".md"), (
        f"Output path {result!r} does not end with '.md'.\n"
        f"  source_path={source_path!r}, output_dir={output_dir!r}"
    )

    source_dir = os.path.dirname(source_path)
    if source_dir:
        norm_source_dir = source_dir.replace("\\", "/")
        assert norm_source_dir in norm_result, (
            f"Source directory {source_dir!r} is not mirrored in output path {result!r}.\n"
            f"  source_path={source_path!r}, output_dir={output_dir!r}"
        )


# ---------------------------------------------------------------------------
# Property 6: Index contains exactly one link per module
# Validates: Requirements 5.1
# ---------------------------------------------------------------------------

_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _count_links(markdown: str) -> int:
    return len(_LINK_PATTERN.findall(markdown))


@given(
    st.lists(_code_module_strategy, min_size=1, max_size=20),
    _style_strategy,
    _output_dir_strategy,
)
@settings(max_examples=200)
def test_property_6_index_contains_exactly_one_link_per_module(
    modules: List[CodeModule], style: str, output_dir: str
) -> None:
    """
    **Validates: Requirements 5.1**

    For any non-empty list of CodeModule objects, build_index produces a
    Markdown document containing exactly one link per module.
    """
    index_content, _ = build_index(modules, output_dir, style)

    link_count = _count_links(index_content)
    module_count = len(modules)

    assert link_count == module_count, (
        f"Expected exactly {module_count} link(s) in index, found {link_count}.\n"
        f"  style={style!r}\n"
        f"  modules={[m.path for m in modules]!r}\n"
        f"  index output:\n{index_content}"
    )
