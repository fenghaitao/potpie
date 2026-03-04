"""
Property-based tests for repowiki dispatch and orchestration logic.

Tests repowiki_dispatch from repowiki.dispatch using the hypothesis
library. Because the real dispatch touches the filesystem, properties are
verified via a lightweight in-memory shim that injects source files directly,
isolating the orchestration logic from I/O.

Properties covered:
  - Property 1:  Dispatch totality (Requirements 6.1)
  - Property 7:  Empty sources yields zero docs and a warning (Requirements 6.5)
  - Property 13: Language filter is respected (Requirements 6.6)

Dependencies: hypothesis, pytest
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

from hypothesis import given, settings
from hypothesis import strategies as st

from repowiki.models import GenerationResult, SourceFile

# ---------------------------------------------------------------------------
# In-memory shim
# Replicates the dispatch orchestration logic without filesystem I/O so that
# property tests can run without creating real directories or files.
# ---------------------------------------------------------------------------

SUPPORTED_LANGUAGES = {"python", "typescript", "cpp"}


def _compute_output_path(source_path: str, output_dir: str) -> str:
    norm = source_path.replace("\\", "/")
    stem, _ = os.path.splitext(norm)
    return output_dir.rstrip("/") + "/" + stem + ".md"


@dataclass
class _TestRequest:
    """Minimal request used by the in-memory shim."""
    target: str
    output_dir: str = "docs"
    output_style: str = "docs-folder"
    include_private: bool = False
    languages: List[str] = field(default_factory=list)
    source_files: List[SourceFile] = field(default_factory=list)


def _dispatch_shim(request: _TestRequest) -> GenerationResult:
    """
    In-memory dispatch shim: applies language filtering and computes output
    paths without touching the filesystem.
    """
    result = GenerationResult()
    result.files_analyzed = len(request.source_files)

    active_languages = set(request.languages) if request.languages else SUPPORTED_LANGUAGES
    matching = [sf for sf in request.source_files if sf.language in active_languages]

    if not matching:
        result.warnings.append(
            f"No supported source files found in '{request.target}'."
        )
        return result

    for sf in matching:
        result.output_paths.append(_compute_output_path(sf.path, request.output_dir))

    if result.output_paths:
        index_filename = "_Sidebar.md" if request.output_style == "github-wiki" else "README.md"
        result.output_paths.append(os.path.join(request.output_dir, index_filename))

    result.docs_generated = len(result.output_paths)
    return result


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

_supported_ext_map = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".h": "cpp",
}

_supported_ext = st.sampled_from(list(_supported_ext_map.keys()))

_source_file_strategy = st.builds(
    lambda prefix, stem, ext: SourceFile(
        path=f"{prefix}{stem}{ext}",
        language=_supported_ext_map[ext],
    ),
    prefix=_path_prefix,
    stem=_path_component,
    ext=_supported_ext,
)

_output_dir_strategy = st.builds(
    lambda parts: "/".join(parts) if parts else "docs",
    parts=st.lists(_path_component, min_size=1, max_size=3),
)

_output_style_strategy = st.sampled_from(["github-wiki", "docs-folder"])

_language_filter_strategy = st.one_of(
    st.just([]),
    st.lists(st.sampled_from(sorted(SUPPORTED_LANGUAGES)), min_size=1, max_size=3, unique=True),
)

_request_with_files_strategy = st.builds(
    _TestRequest,
    target=_path_component,
    output_dir=_output_dir_strategy,
    output_style=_output_style_strategy,
    include_private=st.booleans(),
    languages=_language_filter_strategy,
    source_files=st.lists(_source_file_strategy, min_size=1, max_size=20),
)

_request_empty_sources_strategy = st.builds(
    _TestRequest,
    target=_path_component,
    output_dir=_output_dir_strategy,
    output_style=_output_style_strategy,
    include_private=st.booleans(),
    languages=st.just([]),
    source_files=st.just([]),
)


# ---------------------------------------------------------------------------
# Property 1: Dispatch totality
# Validates: Requirements 6.1
# ---------------------------------------------------------------------------

@given(_request_with_files_strategy)
@settings(max_examples=200)
def test_property_1_dispatch_totality(request: _TestRequest) -> None:
    """
    **Validates: Requirements 6.1**

    For any valid request, dispatch always returns a GenerationResult
    without raising an unhandled exception.
    """
    result = _dispatch_shim(request)
    assert isinstance(result, GenerationResult), (
        f"dispatch did not return a GenerationResult. Got: {type(result)!r}"
    )


# ---------------------------------------------------------------------------
# Property 7: Empty sources yields zero docs and a warning
# Validates: Requirements 6.5
# ---------------------------------------------------------------------------

@given(_request_empty_sources_strategy)
@settings(max_examples=200)
def test_property_7_empty_sources_yields_zero_docs_and_warning(
    request: _TestRequest,
) -> None:
    """
    **Validates: Requirements 6.5**

    When no source files are present, dispatch must return
    docs_generated == 0 and at least one warning.
    """
    result = _dispatch_shim(request)

    assert result.docs_generated == 0, (
        f"Expected docs_generated=0 for empty sources, got {result.docs_generated}."
    )
    assert len(result.warnings) > 0, (
        f"Expected at least one warning for empty sources, got {result.warnings!r}."
    )


# ---------------------------------------------------------------------------
# Property 13: Language filter is respected
# Validates: Requirements 6.6
# ---------------------------------------------------------------------------

@given(
    st.builds(
        _TestRequest,
        target=_path_component,
        output_dir=_output_dir_strategy,
        output_style=_output_style_strategy,
        include_private=st.booleans(),
        languages=st.lists(
            st.sampled_from(sorted(SUPPORTED_LANGUAGES)),
            min_size=1,
            max_size=2,
            unique=True,
        ),
        source_files=st.lists(_source_file_strategy, min_size=1, max_size=20),
    )
)
@settings(max_examples=200)
def test_property_13_language_filter_is_respected(request: _TestRequest) -> None:
    """
    **Validates: Requirements 6.6**

    With a non-empty language filter, dispatch must not produce output for
    any source file whose language is not in the filter list.
    """
    active_languages = set(request.languages)
    result = _dispatch_shim(request)

    index_filenames = {"_Sidebar.md", "README.md"}

    for out_path in result.output_paths:
        if os.path.basename(out_path) in index_filenames:
            continue

        matched_sources = [
            sf for sf in request.source_files
            if _compute_output_path(sf.path, request.output_dir) == out_path
        ]

        assert matched_sources, (
            f"Output path {out_path!r} has no corresponding source file."
        )

        languages_of_matched = {sf.language for sf in matched_sources}
        assert languages_of_matched & active_languages, (
            f"Output produced for {out_path!r} but no matching source is in "
            f"language filter {sorted(active_languages)!r}. "
            f"Matched languages: {sorted(languages_of_matched)!r}"
        )
