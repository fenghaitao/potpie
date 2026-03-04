# test_source_discovery

Property-based tests for the source discovery logic in `repowiki.discovery`. Tests exercise the core filtering and sorting rules using a pure helper (`_discover_from_paths`) that applies the same exclusion and language-mapping logic to an in-memory list of paths, without touching the filesystem.

**Source:** `tests/test_source_discovery.py`

## Functions

### test_property_8_extension_to_language_mapping

Validates that every supported extension maps to the correct language tag. Hypothesis generates arbitrary file paths with supported extensions (filtered to exclude paths through excluded directories) and asserts the right language is assigned.

**Validates:** Requirements 1.5, 1.6, 1.7

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| path | `str` | A generated file path with a supported extension. | |

### test_property_9_excluded_directories_never_in_results

Validates that files inside excluded directories (`node_modules`, `__pycache__`, `dist`, `build`, `.venv`) are never returned by discovery, regardless of where in the path the excluded directory appears.

**Validates:** Requirement 1.2

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| path | `str` | A generated file path passing through an excluded directory. | |

### test_property_10_discovery_output_is_deterministically_sorted

Validates that discovery always returns results sorted by directory then filename, regardless of input order. Runs discovery twice on the same paths (once original, once shuffled) and asserts identical output.

**Validates:** Requirement 1.4

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| paths | `List[str]` | A generated list of unique supported file paths. | |
