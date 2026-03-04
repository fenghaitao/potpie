"""Dispatch and orchestration for repowiki."""

from __future__ import annotations

import os
from pathlib import Path

from .analysis import analyze_file
from .discovery import discover_sources
from .markdown_gen import GeneratorOptions, generate_markdown
from .models import GenerationRequest, GenerationResult
from .output import build_index, compute_output_path

SUPPORTED_LANGUAGES = {"python", "typescript", "cpp"}


def repowiki_dispatch(request: GenerationRequest) -> GenerationResult:
    """
    Full dispatch flow:
      1. Validate inputs
      2. Discover sources
      3. Language filter
      4. Analyze files
      5. Generate Markdown
      6. Build index
      7. Return result
    """
    result = GenerationResult()

    # --- Input validation ---
    if not Path(request.target).exists():
        result.warnings.append(f"Error: target '{request.target}' does not exist in the repository.")
        return result

    if request.languages:
        for lang in request.languages:
            if lang not in SUPPORTED_LANGUAGES:
                result.warnings.append(
                    f"Error: unsupported language '{lang}'. "
                    f"Supported languages are: python, typescript, cpp."
                )
                return result

    output_dir = Path(request.output_dir)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        result.warnings.append(
            f"Error: output directory '{request.output_dir}' is not writable. "
            "Check permissions and try again."
        )
        return result

    # --- Step 1: Source discovery ---
    try:
        sources = discover_sources(request.target)
    except FileNotFoundError as exc:
        result.warnings.append(str(exc))
        return result

    result.files_analyzed = len(sources)

    # --- Step 2: Language filter ---
    active_languages = set(request.languages) if request.languages else SUPPORTED_LANGUAGES
    filtered = [sf for sf in sources if sf.language in active_languages]

    # --- Step 3: Empty-target check ---
    if not filtered:
        result.warnings.append(f"No supported source files found in '{request.target}'.")
        return result

    # --- Step 4: Code analysis ---
    options = GeneratorOptions(
        include_private=request.include_private,
        output_style=request.output_style,
    )

    modules = []
    for sf in filtered:
        module = analyze_file(sf, include_private=request.include_private)
        if module is None:
            result.skipped_files.append(sf.path)
            result.warnings.append(f"Skipped {sf.path}: could not parse file")
        else:
            modules.append(module)

    # --- Step 5: Markdown generation ---
    for module in modules:
        md_content = generate_markdown(module, options)
        out_path = compute_output_path(module.path, request.output_dir)

        # Ensure intermediate directories exist
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(md_content, encoding="utf-8")
        result.output_paths.append(out_path)

    # --- Step 6: Index generation ---
    if modules:
        index_content, index_filename = build_index(modules, request.output_dir, request.output_style)
        index_path = str(output_dir / index_filename)
        Path(index_path).write_text(index_content, encoding="utf-8")
        result.output_paths.append(index_path)

    result.docs_generated = len(result.output_paths)
    return result
