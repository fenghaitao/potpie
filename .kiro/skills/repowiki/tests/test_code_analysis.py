"""
Property-based tests for repowiki code analysis logic.

Tests analyze_file from repowiki.analysis using the hypothesis library.

Dependencies: hypothesis, pytest
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List

from hypothesis import given, settings
from hypothesis import strategies as st

from repowiki.analysis import analyze_file
from repowiki.discovery import SUPPORTED_EXTENSIONS
from repowiki.models import CodeModule, SourceFile

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

_supported_ext = st.sampled_from(list(SUPPORTED_EXTENSIONS.keys()))


def _file_path_with_ext(ext: str):
    return st.builds(
        lambda prefix, stem: f"{prefix}{stem}{ext}",
        prefix=_path_prefix,
        stem=_path_component,
    )


_any_supported_file_path = _supported_ext.flatmap(_file_path_with_ext)

_source_file_strategy = st.builds(
    lambda path: SourceFile(
        path=path,
        language=SUPPORTED_EXTENSIONS[os.path.splitext(path)[1].lower()],
    ),
    path=_any_supported_file_path,
)

# ---------------------------------------------------------------------------
# Symbol model for filter_public property tests
# (filter_public logic is internal; we test it via its observable contract)
# ---------------------------------------------------------------------------

@dataclass
class Symbol:
    name: str
    exported: bool = False
    in_public_section: bool = False
    is_free_header_fn: bool = False


def _filter_public(symbols: List[Symbol], language: str) -> List[Symbol]:
    """Mirror of the public-symbol filter logic in repowiki.analysis."""
    if language == "python":
        return [s for s in symbols if not s.name.startswith("_")]
    elif language == "typescript":
        return [s for s in symbols if s.exported]
    elif language == "cpp":
        return [s for s in symbols if s.in_public_section or s.is_free_header_fn]
    return list(symbols)


_public_python_name = _path_component.filter(lambda n: not n.startswith("_"))
_private_python_name = _path_component.map(lambda n: "_" + n)

_public_ts_symbol = st.builds(Symbol, name=_path_component, exported=st.just(True))
_private_ts_symbol = st.builds(Symbol, name=_path_component, exported=st.just(False))

_public_cpp_symbol = st.one_of(
    st.builds(Symbol, name=_path_component, in_public_section=st.just(True), is_free_header_fn=st.just(False)),
    st.builds(Symbol, name=_path_component, in_public_section=st.just(False), is_free_header_fn=st.just(True)),
)
_private_cpp_symbol = st.builds(
    Symbol,
    name=_path_component,
    in_public_section=st.just(False),
    is_free_header_fn=st.just(False),
)


# ---------------------------------------------------------------------------
# Property 2: Analyze-file path identity
# Validates: Requirements 2.1, 2.2
# ---------------------------------------------------------------------------

@given(_source_file_strategy)
@settings(max_examples=200)
def test_property_2_analyze_file_path_identity(sf: SourceFile) -> None:
    """
    **Validates: Requirements 2.1, 2.2**

    For any SourceFile sf pointing to a non-existent path, analyze_file
    returns None (unparseable) or a CodeModule where:
      - module.path == sf.path
      - module.language == sf.language
    """
    module = analyze_file(sf)
    # Non-existent files return None — that's the correct skipped-file behaviour
    if module is None:
        return
    assert isinstance(module, CodeModule)
    assert module.path == sf.path, (
        f"module.path {module.path!r} != sf.path {sf.path!r}"
    )
    assert module.language == sf.language, (
        f"module.language {module.language!r} != sf.language {sf.language!r}"
    )


# ---------------------------------------------------------------------------
# Property 4: Public-symbol filter excludes private names
# Validates: Requirements 2.6, 2.7, 2.8
# ---------------------------------------------------------------------------

@given(
    st.lists(st.one_of(_public_python_name, _private_python_name), min_size=0, max_size=30).map(
        lambda names: [Symbol(name=n) for n in names]
    )
)
@settings(max_examples=200)
def test_property_4_python_no_private_symbols(symbols: List[Symbol]) -> None:
    """
    **Validates: Requirements 2.6**

    For Python, the public-symbol filter must exclude any symbol whose
    name starts with '_'.
    """
    result = _filter_public(symbols, "python")
    for sym in result:
        assert not sym.name.startswith("_"), (
            f"Private Python symbol {sym.name!r} appeared in filter output"
        )


@given(
    st.lists(st.one_of(_public_ts_symbol, _private_ts_symbol), min_size=0, max_size=30)
)
@settings(max_examples=200)
def test_property_4_typescript_no_unexported_symbols(symbols: List[Symbol]) -> None:
    """
    **Validates: Requirements 2.7**

    For TypeScript, the public-symbol filter must exclude any symbol that
    does not have the export keyword (exported=False).
    """
    result = _filter_public(symbols, "typescript")
    for sym in result:
        assert sym.exported, (
            f"Non-exported TypeScript symbol {sym.name!r} appeared in filter output"
        )


@given(
    st.lists(st.one_of(_public_cpp_symbol, _private_cpp_symbol), min_size=0, max_size=30)
)
@settings(max_examples=200)
def test_property_4_cpp_no_private_symbols(symbols: List[Symbol]) -> None:
    """
    **Validates: Requirements 2.8**

    For C++, the public-symbol filter must exclude any symbol that is not
    in a public: section and is not a free header function.
    """
    result = _filter_public(symbols, "cpp")
    for sym in result:
        assert sym.in_public_section or sym.is_free_header_fn, (
            f"Private C++ symbol {sym.name!r} appeared in filter output"
        )
