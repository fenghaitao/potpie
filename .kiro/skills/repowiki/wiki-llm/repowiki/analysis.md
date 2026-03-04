# analysis

Parses source files and extracts their structural information into `CodeModule` objects. Python files are parsed with the standard `ast` module for accuracy; TypeScript and C++ files are handled with regular expressions. Secret redaction is applied to all languages — string literals resembling API keys, tokens, or passwords are replaced with `[REDACTED]`.

**Source:** `repowiki/analysis.py`

## Dependencies

- `ast` — accurate Python AST parsing
- `re` — TypeScript and C++ regex extraction
- `pathlib.Path`

## Functions

### analyze_file

The single public entry point for code analysis. Dispatches to the appropriate language-specific analyser based on `sf.language` and returns the resulting `CodeModule`.

If the file cannot be read or parsed for any reason (syntax error, binary content, I/O failure), the function returns `None` rather than raising. The caller is responsible for recording the skipped file and continuing with the rest.

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| sf | `SourceFile` | The source file to analyse. | |
| include_private | `bool` | When `False`, underscore-prefixed Python symbols and non-exported TypeScript symbols are excluded. | `False` |

**Returns:** A populated `CodeModule` on success, or `None` if the file could not be parsed.
