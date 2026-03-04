# test_markdown_generation

Property-based tests for the Markdown generation layer. Tests `generate_markdown` and `render_function` from `repowiki.markdown_gen` directly, using Hypothesis to generate arbitrary inputs and assert structural invariants about the output.

**Source:** `tests/test_markdown_generation.py`

## Functions

### test_property_3_markdown_starts_with_h1

Validates that `generate_markdown` always produces a non-empty string whose first line is an H1 heading. Holds for any `CodeModule`, including those with all sections empty.

**Validates:** Requirement 3.1

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| module | `CodeModule` | A generated module with arbitrary content. | |
| options | `GeneratorOptions` | Generated rendering options. | |

### test_property_11_parameter_table_row_count

Validates that `render_function` produces a parameter table with exactly as many data rows as the function has parameters. Only runs for functions with at least one parameter.

**Validates:** Requirement 3.3

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| fn | `FunctionDef` | A generated function with one or more parameters. | |
| opts | `GeneratorOptions` | Generated rendering options. | |

### test_property_12_no_empty_section_headings

Validates that `generate_markdown` never emits a heading immediately followed by another heading. Tested with sparse modules where some sections are empty and some are not.

**Validates:** Requirement 3.10

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| module | `CodeModule` | A generated module with sparse, mixed-empty sections. | |
| options | `GeneratorOptions` | Generated rendering options. | |
