# dispatch

Dispatch and orchestration for repowiki.

**Source:** `repowiki/dispatch.py`

## Dependencies

- `__future__.annotations`
- `os`
- `pathlib.Path`
- `analysis.analyze_file`
- `discovery.discover_sources`
- `markdown_gen.GeneratorOptions`
- `markdown_gen.generate_markdown`
- `models.GenerationRequest`
- `models.GenerationResult`
- `output.build_index`
- `output.compute_output_path`

## Types

**`SUPPORTED_LANGUAGES`** — {'python', 'typescript', 'cpp'}

## Functions

Top-level functions defined in this module.

### repowiki_dispatch

Full dispatch flow:
  1. Validate inputs
  2. Discover sources
  3. Language filter
  4. Analyze files
  5. Generate Markdown
  6. Build index
  7. Return result

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| request | GenerationRequest |  |  |

**Returns:** GenerationResult
