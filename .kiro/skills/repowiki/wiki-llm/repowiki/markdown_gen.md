# markdown_gen

Converts a `CodeModule` into a Markdown document. Enforces the heading hierarchy from SKILL.md (H1 for module title, H2 for classes and top-level sections, H3 for methods and functions), renders parameter tables, adds async badges, and ensures no heading is ever emitted without content following it. All user-supplied strings are HTML-escaped before insertion.

**Source:** `repowiki/markdown_gen.py`

## Functions

### render_function

Renders a single `FunctionDef` as a Markdown fragment starting with an H3 heading. Async functions get an `` `async` `` badge appended to the heading. A description always follows the heading — if the `FunctionDef` has no docstring, a minimal placeholder is generated so the heading is never left empty.

A parameter table is included only when the function has one or more parameters; zero-parameter functions produce no table. A `**Returns:**` line is appended when a return type is present.

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| fn | `FunctionDef` | The function to render. | |

**Returns:** A Markdown string fragment for embedding in a larger document.

### generate_markdown

Renders a complete `CodeModule` as a standalone Markdown page. Opens with an H1 title (filename without extension), the module description, and a `**Source:**` link.

Sections are conditional: `## Dependencies` only when imports are present, `## Types` only when type definitions exist, `## Functions` only when there are module-level functions. Each class gets its own `## ClassName` section. The empty-heading rule is strictly enforced — sections with no content are omitted entirely.

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| module | `CodeModule` | The analysed module to document. | |
| options | `GeneratorOptions` | Controls rendering behaviour. | |

**Returns:** A complete Markdown string for the module's wiki page.
