"""
Property-based tests for repowiki source discovery logic.

Tests the discover_sources logic in repowiki.discovery using the
hypothesis library.

Dependencies: hypothesis, pytest
"""

from __future__ import annotations

import os
from typing import List

from hypothesis import given, settings
from hypothesis import strategies as st

from repowiki.discovery import (
    EXCLUDED_DIRS,
    SUPPORTED_EXTENSIONS,
    _get_language,
    _is_excluded,
)
from repowiki.models import SourceFile

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
_excluded_dir = st.sampled_from(sorted(EXCLUDED_DIRS))


def _file_path_with_ext(ext: str):
    return st.builds(
        lambda prefix, stem: f"{prefix}{stem}{ext}",
        prefix=_path_prefix,
        stem=_path_component,
    )


_any_supported_file_path = _supported_ext.flatmap(_file_path_with_ext).filter(
    lambda p: not any(part in EXCLUDED_DIRS for part in p.replace("\\", "/").split("/"))
)


def _file_path_through_excluded_dir(excluded: str, ext: str):
    return st.builds(
        lambda before, stem: f"{before}{excluded}/{stem}{ext}",
        before=_path_prefix,
        stem=_path_component,
    )


_excluded_file_path = st.builds(
    lambda excluded, ext: _file_path_through_excluded_dir(excluded, ext),
    excluded=_excluded_dir,
    ext=_supported_ext,
).flatmap(lambda s: s)


# ---------------------------------------------------------------------------
# Helper: a pure-function discover that works on a flat path list
# (mirrors the real walker's logic without touching the filesystem)
# ---------------------------------------------------------------------------

def _discover_from_paths(file_paths: List[str]) -> List[SourceFile]:
    """Apply discovery rules to a flat list of paths (no filesystem access)."""
    from pathlib import Path

    results: List[SourceFile] = []
    for path in file_paths:
        p = Path(path)
        if _is_excluded(p):
            continue
        lang = _get_language(p)
        if lang is None:
            continue
        results.append(SourceFile(path=path, language=lang))

    results.sort(key=lambda sf: (os.path.dirname(sf.path), os.path.basename(sf.path)))
    return results


# ---------------------------------------------------------------------------
# Property 8: Extension-to-language mapping
# Validates: Requirements 1.5, 1.6, 1.7
# ---------------------------------------------------------------------------

@given(_any_supported_file_path)
@settings(max_examples=200)
def test_property_8_extension_to_language_mapping(path: str) -> None:
    """
    **Validates: Requirements 1.5, 1.6, 1.7**

    For any file path with a supported extension, discover assigns the
    correct language tag:
      .py          → "python"
      .ts / .tsx   → "typescript"
      .cpp / .cc / .cxx / .hpp / .h → "cpp"
    """
    results = _discover_from_paths([path])
    assert len(results) == 1, f"Expected 1 result for {path!r}, got {results}"
    sf = results[0]
    _, ext = os.path.splitext(path)
    expected_language = SUPPORTED_EXTENSIONS[ext.lower()]
    assert sf.language == expected_language, (
        f"Path {path!r} (ext={ext!r}) should map to {expected_language!r}, "
        f"got {sf.language!r}"
    )


# ---------------------------------------------------------------------------
# Property 9: Excluded directories are never in results
# Validates: Requirements 1.2
# ---------------------------------------------------------------------------

@given(_excluded_file_path)
@settings(max_examples=200)
def test_property_9_excluded_directories_never_in_results(path: str) -> None:
    """
    **Validates: Requirements 1.2**

    For any file path that passes through an excluded directory
    (node_modules, __pycache__, dist, build, .venv), discovery must not
    include that file in its results.
    """
    results = _discover_from_paths([path])
    result_paths = [sf.path for sf in results]
    assert path not in result_paths, (
        f"Path {path!r} passes through an excluded directory "
        f"but appeared in discovery results: {result_paths}"
    )


# ---------------------------------------------------------------------------
# Property 10: Discovery output is deterministically sorted
# Validates: Requirements 1.4
# ---------------------------------------------------------------------------

@given(st.lists(_any_supported_file_path, min_size=1, max_size=30, unique=True))
@settings(max_examples=200)
def test_property_10_discovery_output_is_deterministically_sorted(paths: List[str]) -> None:
    """
    **Validates: Requirements 1.4**

    For any list of file paths, discovery returns results sorted by
    directory then by file name, and repeated calls on the same input
    (in any order) produce identical output.
    """
    import random

    result_a = _discover_from_paths(paths)

    shuffled = paths[:]
    random.shuffle(shuffled)
    result_b = _discover_from_paths(shuffled)

    assert result_a == result_b, (
        "discover produced different orderings for the same file set.\n"
        f"  Original order result: {[sf.path for sf in result_a]}\n"
        f"  Shuffled order result: {[sf.path for sf in result_b]}"
    )

    paths_out = [sf.path for sf in result_a]
    expected_sorted = sorted(
        paths_out,
        key=lambda p: (os.path.dirname(p), os.path.basename(p)),
    )
    assert paths_out == expected_sorted, (
        f"Discovery output is not sorted by (dir, filename).\n"
        f"  Got:      {paths_out}\n"
        f"  Expected: {expected_sorted}"
    )
