# discovery

Finds all relevant source files under a target directory. Walks the file tree, prunes excluded directories, maps extensions to language tags, and returns a deterministically sorted list of `SourceFile` objects ready for analysis.

**Source:** `repowiki/discovery.py`

## Dependencies

- `os`
- `pathlib.Path`

## Types

**`SUPPORTED_EXTENSIONS`** — Maps file extensions to language tags: `.py` → `python`, `.ts`/`.tsx` → `typescript`, `.cpp`/`.cc`/`.cxx`/`.hpp`/`.h` → `cpp`.

**`EXCLUDED_DIRS`** — Directory names that are never descended into: `node_modules`, `__pycache__`, `dist`, `build`, `.venv`.

## Functions

### discover_sources

Recursively walks `target` and collects every file whose extension appears in `SUPPORTED_EXTENSIONS`. Directories in `EXCLUDED_DIRS` are pruned before recursion so their contents are never visited. Symlinks that resolve outside the repository root are silently skipped.

Results are sorted by directory path then by filename, making the output identical across repeated calls regardless of filesystem ordering.

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| target | `str` | Directory or file path to search. Must exist. | |
| repo_root | `Optional[str]` | Repository root for symlink boundary checks. Defaults to the current working directory. | `None` |

**Returns:** A sorted list of `SourceFile` objects, one per discovered file.
