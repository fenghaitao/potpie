# test_code_analysis

Property-based tests for repowiki code analysis logic.

Tests analyze_file from repowiki.analysis using the hypothesis library.

Dependencies: hypothesis, pytest

**Source:** `tests/test_code_analysis.py`

## Dependencies

- `__future__.annotations`
- `os`
- `dataclasses.dataclass`
- `typing.List`
- `hypothesis.given`
- `hypothesis.settings`
- `hypothesis.strategies`
- `repowiki.analysis.analyze_file`
- `repowiki.discovery.SUPPORTED_EXTENSIONS`
- `repowiki.models.CodeModule`
- `repowiki.models.SourceFile`

## Types

**`_path_component`** — st.text(alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd'), whitelist_characters='-_'), min_size=1, max_size=16)

**`_path_prefix`** — st.lists(_path_component, min_size=0, max_size=3).map(lambda parts: '/'.join(parts) + '/' if parts else '')

**`_supported_ext`** — st.sampled_from(list(SUPPORTED_EXTENSIONS.keys()))

**`_any_supported_file_path`** — _supported_ext.flatmap(_file_path_with_ext)

**`_source_file_strategy`** — st.builds(lambda path: SourceFile(path=path, language=SUPPORTED_EXTENSIONS[os.path.splitext(path)[1].lower()]), path=_any_supported_file_path)

**`_public_python_name`** — _path_component.filter(lambda n: not n.startswith('_'))

**`_private_python_name`** — _path_component.map(lambda n: '_' + n)

**`_public_ts_symbol`** — st.builds(Symbol, name=_path_component, exported=st.just(True))

**`_private_ts_symbol`** — st.builds(Symbol, name=_path_component, exported=st.just(False))

**`_public_cpp_symbol`** — st.one_of(st.builds(Symbol, name=_path_component, in_public_section=st.just(True), is_free_header_fn=st.just(False)), st.builds(Symbol, name=_path_component, in_public_section=st.just(False), is_free_header_fn=st.just(True)))

**`_private_cpp_symbol`** — st.builds(Symbol, name=_path_component, in_public_section=st.just(False), is_free_header_fn=st.just(False))

## Symbol

Class `Symbol`.

## Functions

Top-level functions defined in this module.

### test_property_2_analyze_file_path_identity

**Validates: Requirements 2.1, 2.2**

For any SourceFile sf pointing to a non-existent path, analyze_file
returns None (unparseable) or a CodeModule where:
  - module.path == sf.path
  - module.language == sf.language

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| sf | SourceFile |  |  |

**Returns:** None

### test_property_4_python_no_private_symbols

**Validates: Requirements 2.6**

For Python, the public-symbol filter must exclude any symbol whose
name starts with '_'.

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| symbols | List[Symbol] |  |  |

**Returns:** None

### test_property_4_typescript_no_unexported_symbols

**Validates: Requirements 2.7**

For TypeScript, the public-symbol filter must exclude any symbol that
does not have the export keyword (exported=False).

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| symbols | List[Symbol] |  |  |

**Returns:** None

### test_property_4_cpp_no_private_symbols

**Validates: Requirements 2.8**

For C++, the public-symbol filter must exclude any symbol that is not
in a public: section and is not a free header function.

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| symbols | List[Symbol] |  |  |

**Returns:** None
