# test_output_and_index

Property-based tests for output path computation and index generation. Tests `compute_output_path` and `build_index` from `repowiki.output` directly, without any filesystem access.

**Source:** `tests/test_output_and_index.py`

## Functions

### test_property_5_output_path_under_output_dir

Validates three invariants of `compute_output_path` simultaneously: the result starts with `output_dir`, ends with `.md`, and preserves the source file's directory structure within the output path.

**Validates:** Requirements 4.1, 4.2, 4.3

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| source_path | `str` | A generated source file path. | |
| output_dir | `str` | A generated output directory path. | |
| style | `str` | Either `"github-wiki"` or `"docs-folder"`. | |

### test_property_6_index_contains_exactly_one_link_per_module

Validates that `build_index` produces exactly one Markdown link per module — no duplicates, no omissions.

**Validates:** Requirement 5.1

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| modules | `List[CodeModule]` | A generated non-empty list of modules. | |
| style | `str` | Either `"github-wiki"` or `"docs-folder"`. | |
| output_dir | `str` | A generated output directory path. | |
