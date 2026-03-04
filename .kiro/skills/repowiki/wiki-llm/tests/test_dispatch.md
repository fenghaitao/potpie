# test_dispatch

Property-based tests for the dispatch and orchestration logic. Because the real `repowiki_dispatch` touches the filesystem, these tests use a lightweight in-memory shim (`_dispatch_shim`) that accepts an explicit `source_files` list and applies the same language-filtering and output-path logic without any I/O.

**Source:** `tests/test_dispatch.py`

## Functions

### test_property_1_dispatch_totality

Validates that the dispatch function always returns a `GenerationResult` without raising, for any valid combination of inputs.

**Validates:** Requirement 6.1

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| request | `_TestRequest` | A generated request with a non-empty source file list. | |

### test_property_7_empty_sources_yields_zero_docs_and_warning

Validates that when no source files are present, the dispatcher returns `docs_generated = 0` and at least one warning message.

**Validates:** Requirement 6.5

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| request | `_TestRequest` | A generated request with an empty source file list. | |

### test_property_13_language_filter_is_respected

Validates that with a non-empty language filter, no output is produced for source files whose language is not in the filter. For every non-index output path, at least one corresponding source file must have a language in the active filter set.

**Validates:** Requirement 6.6

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| request | `_TestRequest` | A generated request with a non-empty language filter and mixed-language source files. | |
