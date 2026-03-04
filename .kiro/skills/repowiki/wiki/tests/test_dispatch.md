# test_dispatch

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

**Source:** `tests/test_dispatch.py`

## Dependencies

- `__future__.annotations`
- `os`
- `dataclasses.dataclass`
- `dataclasses.field`
- `typing.List`
- `hypothesis.given`
- `hypothesis.settings`
- `hypothesis.strategies`
- `repowiki.models.GenerationResult`
- `repowiki.models.SourceFile`

## Types

**`SUPPORTED_LANGUAGES`** — {'python', 'typescript', 'cpp'}

**`_path_component`** — st.text(alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd'), whitelist_characters='-_'), min_size=1, max_size=16)

**`_path_prefix`** — st.lists(_path_component, min_size=0, max_size=3).map(lambda parts: '/'.join(parts) + '/' if parts else '')

**`_supported_ext_map`** — {'.py': 'python', '.ts': 'typescript', '.tsx': 'typescript', '.cpp': 'cpp', '.hpp': 'cpp', '.h': 'cpp'}

**`_supported_ext`** — st.sampled_from(list(_supported_ext_map.keys()))

**`_source_file_strategy`** — st.builds(lambda prefix, stem, ext: SourceFile(path=f'{prefix}{stem}{ext}', language=_supported_ext_map[ext]), prefix=_path_prefix, stem=_path_component, ext=_supported_ext)

**`_output_dir_strategy`** — st.builds(lambda parts: '/'.join(parts) if parts else 'docs', parts=st.lists(_path_component, min_size=1, max_size=3))

**`_output_style_strategy`** — st.sampled_from(['github-wiki', 'docs-folder'])

**`_language_filter_strategy`** — st.one_of(st.just([]), st.lists(st.sampled_from(sorted(SUPPORTED_LANGUAGES)), min_size=1, max_size=3, unique=True))

**`_request_with_files_strategy`** — st.builds(_TestRequest, target=_path_component, output_dir=_output_dir_strategy, output_style=_output_style_strategy, include_private=st.booleans(), languages=_language_filter_strategy, source_files=st.lists(_source_file_strategy, min_size=1, max_size=20))

**`_request_empty_sources_strategy`** — st.builds(_TestRequest, target=_path_component, output_dir=_output_dir_strategy, output_style=_output_style_strategy, include_private=st.booleans(), languages=st.just([]), source_files=st.just([]))

## Functions

Top-level functions defined in this module.

### test_property_1_dispatch_totality

**Validates: Requirements 6.1**

For any valid request, dispatch always returns a GenerationResult
without raising an unhandled exception.

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| request | _TestRequest |  |  |

**Returns:** None

### test_property_7_empty_sources_yields_zero_docs_and_warning

**Validates: Requirements 6.5**

When no source files are present, dispatch must return
docs_generated == 0 and at least one warning.

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| request | _TestRequest |  |  |

**Returns:** None

### test_property_13_language_filter_is_respected

**Validates: Requirements 6.6**

With a non-empty language filter, dispatch must not produce output for
any source file whose language is not in the filter list.

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| request | _TestRequest |  |  |

**Returns:** None
