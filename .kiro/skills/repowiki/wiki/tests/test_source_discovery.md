# test_source_discovery

Property-based tests for repowiki source discovery logic.

Tests the discover_sources logic in repowiki.discovery using the
hypothesis library.

Dependencies: hypothesis, pytest

**Source:** `tests/test_source_discovery.py`

## Dependencies

- `__future__.annotations`
- `os`
- `typing.List`
- `hypothesis.given`
- `hypothesis.settings`
- `hypothesis.strategies`
- `repowiki.discovery.EXCLUDED_DIRS`
- `repowiki.discovery.SUPPORTED_EXTENSIONS`
- `repowiki.discovery._get_language`
- `repowiki.discovery._is_excluded`
- `repowiki.models.SourceFile`
- `pathlib.Path`
- `random`

## Types

**`_path_component`** — st.text(alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd'), whitelist_characters='-_'), min_size=1, max_size=16)

**`_path_prefix`** — st.lists(_path_component, min_size=0, max_size=3).map(lambda parts: '/'.join(parts) + '/' if parts else '')

**`_supported_ext`** — st.sampled_from(list(SUPPORTED_EXTENSIONS.keys()))

**`_excluded_dir`** — st.sampled_from(sorted(EXCLUDED_DIRS))

**`_any_supported_file_path`** — _supported_ext.flatmap(_file_path_with_ext).filter(lambda p: not any((part in EXCLUDED_DIRS for part in p.replace('\\', '/').split('/'))))

**`_excluded_file_path`** — st.builds(lambda excluded, ext: _file_path_through_excluded_dir(excluded, ext), excluded=_excluded_dir, ext=_supported_ext).flatmap(lambda s: s)

## Functions

Top-level functions defined in this module.

### test_property_8_extension_to_language_mapping

**Validates: Requirements 1.5, 1.6, 1.7**

For any file path with a supported extension, discover assigns the
correct language tag:
  .py          → "python"
  .ts / .tsx   → "typescript"
  .cpp / .cc / .cxx / .hpp / .h → "cpp"

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| path | str |  |  |

**Returns:** None

### test_property_9_excluded_directories_never_in_results

**Validates: Requirements 1.2**

For any file path that passes through an excluded directory
(node_modules, __pycache__, dist, build, .venv), discovery must not
include that file in its results.

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| path | str |  |  |

**Returns:** None

### test_property_10_discovery_output_is_deterministically_sorted

**Validates: Requirements 1.4**

For any list of file paths, discovery returns results sorted by
directory then by file name, and repeated calls on the same input
(in any order) produce identical output.

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| paths | List[str] |  |  |

**Returns:** None
