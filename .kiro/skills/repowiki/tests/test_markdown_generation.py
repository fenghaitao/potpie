"""
Property-based tests for repowiki Markdown generation logic.

Tests generate_markdown and render_function from repowiki.markdown_gen
using the hypothesis library.

Dependencies: hypothesis, pytest
"""

from __future__ import annotations

import re
from typing import List

from hypothesis import given, settings
from hypothesis import strategies as st

from repowiki.markdown_gen import generate_markdown, render_function
from repowiki.models import (
    ClassDef,
    CodeModule,
    FunctionDef,
    GeneratorOptions,
    ParamDef,
    TypeDef,
)

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_identifier = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="_"),
    min_size=1,
    max_size=20,
)

_short_text = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd", "Zs"), whitelist_characters=" _-.,"),
    min_size=0,
    max_size=50,
)

_path_component = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="-_"),
    min_size=1,
    max_size=16,
)

_supported_ext = st.sampled_from([".py", ".ts", ".tsx", ".cpp", ".hpp", ".h"])

_file_path = st.builds(
    lambda parts, stem, ext: "/".join(parts) + "/" + stem + ext if parts else stem + ext,
    parts=st.lists(_path_component, min_size=0, max_size=3),
    stem=_path_component,
    ext=_supported_ext,
)

_param_strategy = st.builds(
    ParamDef,
    name=_identifier,
    type=_short_text,
    description=_short_text,
    default=_short_text,
)

_function_strategy = st.builds(
    FunctionDef,
    name=_identifier,
    description=_short_text,
    params=st.lists(_param_strategy, min_size=0, max_size=5),
    returns=_short_text,
    is_async=st.booleans(),
    is_static=st.booleans(),
)

_type_strategy = st.builds(
    TypeDef,
    name=_identifier,
    description=_short_text,
)

_class_strategy = st.builds(
    ClassDef,
    name=_identifier,
    description=_short_text,
    methods=st.lists(_function_strategy, min_size=0, max_size=3),
)

_code_module_strategy = st.builds(
    CodeModule,
    path=_file_path,
    language=st.sampled_from(["python", "typescript", "cpp"]),
    description=_short_text,
    imports=st.lists(_short_text, min_size=0, max_size=5),
    classes=st.lists(_class_strategy, min_size=0, max_size=3),
    functions=st.lists(_function_strategy, min_size=0, max_size=3),
    types=st.lists(_type_strategy, min_size=0, max_size=3),
)

_options_strategy = st.builds(
    GeneratorOptions,
    include_private=st.booleans(),
    output_style=st.sampled_from(["github-wiki", "docs-folder"]),
)

_function_with_params_strategy = st.builds(
    FunctionDef,
    name=_identifier,
    description=_short_text,
    params=st.lists(_param_strategy, min_size=1, max_size=10),
    returns=_short_text,
    is_async=st.booleans(),
    is_static=st.booleans(),
)

_sparse_code_module_strategy = st.builds(
    CodeModule,
    path=_file_path,
    language=st.sampled_from(["python", "typescript", "cpp"]),
    description=_short_text,
    imports=st.one_of(st.just([]), st.lists(_short_text, min_size=1, max_size=3)),
    classes=st.one_of(st.just([]), st.lists(_class_strategy, min_size=1, max_size=2)),
    functions=st.one_of(st.just([]), st.lists(_function_strategy, min_size=1, max_size=2)),
    types=st.one_of(st.just([]), st.lists(_type_strategy, min_size=1, max_size=2)),
)


# ---------------------------------------------------------------------------
# Property 3: Markdown starts with H1
# Validates: Requirements 3.1
# ---------------------------------------------------------------------------

@given(_code_module_strategy, _options_strategy)
@settings(max_examples=200)
def test_property_3_markdown_starts_with_h1(module: CodeModule, options: GeneratorOptions) -> None:
    """
    **Validates: Requirements 3.1**

    For any CodeModule, generate_markdown returns a non-empty string whose
    first line begins with '# '.
    """
    result = generate_markdown(module, options)

    assert result, "generate_markdown returned an empty string"

    first_line = result.splitlines()[0]
    assert first_line.startswith("# "), (
        f"First line of generated Markdown does not start with '# '.\n"
        f"  Module path: {module.path!r}\n"
        f"  First line:  {first_line!r}"
    )


# ---------------------------------------------------------------------------
# Property 11: Parameter table row count matches param count
# Validates: Requirements 3.3
# ---------------------------------------------------------------------------

def _count_table_data_rows(markdown: str) -> int:
    lines = markdown.splitlines()
    table_lines = [l for l in lines if re.match(r"^\s*\|", l)]
    if len(table_lines) < 2:
        return 0
    return len(table_lines[2:])  # skip header + separator


@given(_function_with_params_strategy, _options_strategy)
@settings(max_examples=200)
def test_property_11_parameter_table_row_count(fn: FunctionDef, opts: GeneratorOptions) -> None:
    """
    **Validates: Requirements 3.3**

    For any FunctionDef with n > 0 parameters, render_function produces a
    Markdown table with exactly n data rows.
    """
    n = len(fn.params)
    assert n > 0

    result = render_function(fn)
    data_rows = _count_table_data_rows(result)

    assert data_rows == n, (
        f"Expected {n} data rows in parameter table, got {data_rows}.\n"
        f"  Function: {fn.name!r} with {n} params\n"
        f"  Rendered:\n{result}"
    )


# ---------------------------------------------------------------------------
# Property 12: No empty section headings
# Validates: Requirements 3.10
# ---------------------------------------------------------------------------

def _has_consecutive_headings(markdown: str) -> bool:
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("#"):
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines) and lines[j].startswith("#"):
                return True
        i += 1
    return False


@given(_sparse_code_module_strategy, _options_strategy)
@settings(max_examples=200)
def test_property_12_no_empty_section_headings(module: CodeModule, options: GeneratorOptions) -> None:
    """
    **Validates: Requirements 3.10**

    For any CodeModule, generate_markdown must not produce a section heading
    immediately followed by another heading.
    """
    result = generate_markdown(module, options)

    assert not _has_consecutive_headings(result), (
        f"generate_markdown produced consecutive headings (empty section).\n"
        f"  Module: path={module.path!r}, imports={module.imports!r}, "
        f"types={[t.name for t in module.types]!r}, "
        f"functions={[f.name for f in module.functions]!r}, "
        f"classes={[c.name for c in module.classes]!r}\n"
        f"  Output:\n{result}"
    )
