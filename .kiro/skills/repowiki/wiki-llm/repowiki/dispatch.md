# dispatch

The orchestration layer that ties all components together. Accepts a `GenerationRequest`, validates inputs, runs the full pipeline from source discovery through to index generation, and returns a `GenerationResult`.

**Source:** `repowiki/dispatch.py`

## Dependencies

- `repowiki.analysis` — `analyze_file`
- `repowiki.discovery` — `discover_sources`
- `repowiki.markdown_gen` — `generate_markdown`
- `repowiki.output` — `compute_output_path`, `build_index`

## Functions

### repowiki_dispatch

Executes the full seven-step generation pipeline:

1. **Validate inputs** — checks the target exists, language filter values are recognised, and the output directory is writable (creating it if needed). Returns an error immediately on any failure.
2. **Discover sources** — calls `discover_sources` to find all supported files under the target.
3. **Language filter** — discards files whose language is not in the requested filter. Filtered files are silently excluded and never appear in `skipped_files`.
4. **Empty-target check** — if no files remain after filtering, returns `docs_generated = 0` with a warning and stops.
5. **Analyse files** — calls `analyze_file` on each remaining file. Unparseable files are added to `skipped_files` with a warning; processing continues for all others.
6. **Generate and write Markdown** — renders each module's page and writes it to the computed output path, creating intermediate directories as needed.
7. **Build index** — writes `_Sidebar.md` or `README.md` when at least one module was successfully documented.

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| request | `GenerationRequest` | The fully-specified generation request. | |

**Returns:** A `GenerationResult` with counts, output paths, skipped files, and accumulated warnings.
