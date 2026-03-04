# test_markdown_generation

Property-based tests for repowiki Markdown generation logic.

Tests generate_markdown and render_function from repowiki.markdown_gen
using the hypothesis library.

Dependencies: hypothesis, pytest

**Source:** `tests/test_markdown_generation.py`

## Dependencies

- `__future__.annotations`
- `re`
- `typing.List`
- `hypothesis.given`
- `hypothesis.settings`
- `hypothesis.strategies`
- `repowiki.markdown_gen.generate_markdown`
- `repowiki.markdown_gen.render_function`
- `repowiki.models.ClassDef`
- `repowiki.models.CodeModule`
- `repowiki.models.FunctionDef`
- `repowiki.models.GeneratorOptions`
- `repowiki.models.ParamDef`
- `repowiki.models.TypeDef`

## Types

**`_identifier`** — st.text(alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd'), whitelist_characters='_'), min_size=1, max_size=20)

**`_short_text`** — st.text(alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd', 'Zs'), whitelist_characters=' _-.,'), min_size=0, max_size=50)

**`_path_component`** — st.text(alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd'), whitelist_characters='-_'), min_size=1, max_size=16)

**`_supported_ext`** — st.sampled_from(['.py', '.ts', '.tsx', '.cpp', '.hpp', '.h'])

**`_file_path`** — st.builds(lambda parts, stem, ext: '/'.join(parts) + '/' + stem + ext if parts else stem + ext, parts=st.lists(_path_component, min_size=0, max_size=3), stem=_path_component, ext=_supported_ext)

**`_param_strategy`** — st.builds(ParamDef, name=_identifier, type=_short_text, description=_short_text, default=_short_text)

**`_function_strategy`** — st.builds(FunctionDef, name=_identifier, description=_short_text, params=st.lists(_param_strategy, min_size=0, max_size=5), returns=_short_text, is_async=st.booleans(), is_static=st.booleans())

**`_type_strategy`** — st.builds(TypeDef, name=_identifier, description=_short_text)

**`_class_strategy`** — st.builds(ClassDef, name=_identifier, description=_short_text, methods=st.lists(_function_strategy, min_size=0, max_size=3))

**`_code_module_strategy`** — st.builds(CodeModule, path=_file_path, language=st.sampled_from(['python', 'typescript', 'cpp']), description=_short_text, imports=st.lists(_short_text, min_size=0, max_size=5), classes=st.lists(_class_strategy, min_size=0, max_size=3), functions=st.lists(_function_strategy, min_size=0, max_size=3), types=st.lists(_type_strategy, min_size=0, max_size=3))

**`_options_strategy`** — st.builds(GeneratorOptions, include_private=st.booleans(), output_style=st.sampled_from(['github-wiki', 'docs-folder']))

**`_function_with_params_strategy`** — st.builds(FunctionDef, name=_identifier, description=_short_text, params=st.lists(_param_strategy, min_size=1, max_size=10), returns=_short_text, is_async=st.booleans(), is_static=st.booleans())

**`_sparse_code_module_strategy`** — st.builds(CodeModule, path=_file_path, language=st.sampled_from(['python', 'typescript', 'cpp']), description=_short_text, imports=st.one_of(st.just([]), st.lists(_short_text, min_size=1, max_size=3)), classes=st.one_of(st.just([]), st.lists(_class_strategy, min_size=1, max_size=2)), functions=st.one_of(st.just([]), st.lists(_function_strategy, min_size=1, max_size=2)), types=st.one_of(st.just([]), st.lists(_type_strategy, min_size=1, max_size=2)))

## Functions

Top-level functions defined in this module.

### test_property_3_markdown_starts_with_h1

**Validates: Requirements 3.1**

For any CodeModule, generate_markdown returns a non-empty string whose
first line begins with '# '.

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| module | CodeModule |  |  |
| options | GeneratorOptions |  |  |

**Returns:** None

### test_property_11_parameter_table_row_count

**Validates: Requirements 3.3**

For any FunctionDef with n &gt; 0 parameters, render_function produces a
Markdown table with exactly n data rows.

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| fn | FunctionDef |  |  |
| opts | GeneratorOptions |  |  |

**Returns:** None

### test_property_12_no_empty_section_headings

**Validates: Requirements 3.10**

For any CodeModule, generate_markdown must not produce a section heading
immediately followed by another heading.

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| module | CodeModule |  |  |
| options | GeneratorOptions |  |  |

**Returns:** None
