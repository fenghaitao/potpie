# test_code_analysis

Property-based tests for the code analysis layer. Tests `analyze_file` from `repowiki.analysis` and verifies the public-symbol filtering contract for all three supported languages.

Because `analyze_file` requires real files on disk, the path-identity property accepts `None` as a valid return for non-existent paths — that is the correct skipped-file behaviour. The filter properties use an in-module mirror of the internal filtering rules.

**Source:** `tests/test_code_analysis.py`

## Symbol

A test-only dataclass used to represent a symbol with visibility attributes for the filter property tests. Not part of the production API.

## Functions

### test_property_2_analyze_file_path_identity

Validates that when `analyze_file` successfully parses a file, the returned `CodeModule` has `path` and `language` matching the input `SourceFile` exactly. `None` is accepted for non-existent paths.

**Validates:** Requirements 2.1, 2.2

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| sf | `SourceFile` | A generated `SourceFile` with a supported extension. | |

### test_property_4_python_no_private_symbols

Validates that the Python public-symbol filter excludes any symbol whose name starts with `_`.

**Validates:** Requirement 2.6

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| symbols | `List[Symbol]` | A generated list of Python symbols with mixed visibility. | |

### test_property_4_typescript_no_unexported_symbols

Validates that the TypeScript public-symbol filter excludes any symbol without the `export` keyword.

**Validates:** Requirement 2.7

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| symbols | `List[Symbol]` | A generated list of TypeScript symbols with mixed export status. | |

### test_property_4_cpp_no_private_symbols

Validates that the C++ public-symbol filter excludes any symbol that is neither in a `public:` section nor a free function in a header file.

**Validates:** Requirement 2.8

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| symbols | `List[Symbol]` | A generated list of C++ symbols with mixed visibility. | |
