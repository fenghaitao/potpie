# discovery

Source file discovery for repowiki.

**Source:** `repowiki/discovery.py`

## Dependencies

- `__future__.annotations`
- `os`
- `pathlib.Path`
- `typing.List`
- `typing.Optional`
- `models.SourceFile`

## Types

**`SUPPORTED_EXTENSIONS`** — dict[str, str]

**`EXCLUDED_DIRS`** — {'node_modules', '__pycache__', 'dist', 'build', '.venv'}

## Functions

Top-level functions defined in this module.

### discover_sources

Recursively discover supported source files under *target*.

Skips excluded directories, respects supported extensions, and returns
results sorted by (directory, filename).

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| target | str |  |  |
| repo_root | Optional[str] |  | None |

**Returns:** List[SourceFile]
