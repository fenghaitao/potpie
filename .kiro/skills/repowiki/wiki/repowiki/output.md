# output

Output path computation and index generation for repowiki.

**Source:** `repowiki/output.py`

## Dependencies

- `__future__.annotations`
- `os`
- `typing.List`
- `models.CodeModule`

## Functions

Top-level functions defined in this module.

### compute_output_path

Replace source extension with .md and mirror directory structure under output_dir.

e.g. src/auth/user.ts + docs -&gt; docs/src/auth/user.md

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| source_path | str |  |  |
| output_dir | str |  |  |

**Returns:** str

### build_index

Build an index Markdown document.

Returns (index_content, index_filename).

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| modules | List[CodeModule] |  |  |
| output_dir | str |  |  |
| output_style | str |  |  |

**Returns:** tuple[str, str]
