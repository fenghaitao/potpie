# test_output_and_index

Property-based tests for repowiki output path computation and index generation.

Tests compute_output_path and build_index from repowiki.output using the
hypothesis library.

Dependencies: hypothesis, pytest

**Source:** `tests/test_output_and_index.py`

## Dependencies

- `__future__.annotations`
- `os`
- `re`
- `typing.List`
- `hypothesis.given`
- `hypothesis.settings`
- `hypothesis.strategies`
- `repowiki.models.CodeModule`
- `repowiki.output.build_index`
- `repowiki.output.compute_output_path`

## Types

**`_path_component`** — st.text(alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd'), whitelist_characters='-_'), min_size=1, max_size=16)

**`_path_prefix`** — st.lists(_path_component, min_size=0, max_size=3).map(lambda parts: '/'.join(parts) + '/' if parts else '')

**`_supported_ext`** — st.sampled_from(['.py', '.ts', '.tsx', '.cpp', '.cc', '.cxx', '.hpp', '.h'])

**`_source_path_strategy`** — st.builds(lambda prefix, stem, ext: f'{prefix}{stem}{ext}', prefix=_path_prefix, stem=_path_component, ext=_supported_ext)

**`_output_dir_strategy`** — st.builds(lambda parts: '/'.join(parts) if parts else 'docs', parts=st.lists(_path_component, min_size=1, max_size=3))

**`_style_strategy`** — st.sampled_from(['github-wiki', 'docs-folder'])

**`_short_text`** — st.text(alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd', 'Zs'), whitelist_characters=' _-.,'), min_size=0, max_size=50)

**`_code_module_strategy`** — st.builds(CodeModule, path=_source_path_strategy, language=st.sampled_from(['python', 'typescript', 'cpp']), description=_short_text)

**`_LINK_PATTERN`** — re.compile('\\[([^\\]]+)\\]\\(([^)]+)\\)')

## Functions

Top-level functions defined in this module.

### test_property_5_output_path_under_output_dir

**Validates: Requirements 4.1, 4.2, 4.3**

For any source path and output directory:
  1. The result starts with output_dir
  2. The result ends with .md
  3. The source directory structure is mirrored in the output path

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| source_path | str |  |  |
| output_dir | str |  |  |
| style | str |  |  |

**Returns:** None

### test_property_6_index_contains_exactly_one_link_per_module

**Validates: Requirements 5.1**

For any non-empty list of CodeModule objects, build_index produces a
Markdown document containing exactly one link per module.

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| modules | List[CodeModule] |  |  |
| style | str |  |  |
| output_dir | str |  |  |

**Returns:** None
