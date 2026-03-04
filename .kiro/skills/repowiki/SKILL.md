---
name: repowiki
description: 'Analyzes Python, TypeScript, and C++ source files in a repository and generates rich Markdown wiki pages. Uses a bundled extraction tool to discover and parse source structure, then applies LLM reasoning to write clear, human-readable documentation.'
---

# repowiki

This skill generates a GitHub wiki or docs folder for a repository. It works in two phases:

1. **Extraction** — a bundled Python tool discovers source files and parses their structure (classes, functions, docstrings, type annotations) into a structured JSON document.
2. **Wiki generation** — you (the agent) read that JSON and write rich, human-readable Markdown wiki pages for each module, using your understanding of the code to produce clear prose, not just a reflection of the raw structure.

## Installation

```bash
uv pip install -e {baseDir}
```

## Phase 1 — Extract source structure

Run the extraction tool to discover and parse all source files under the target directory. This produces a JSON document describing every module's classes, functions, parameters, return types, and docstrings.

```bash
# Extract to a file (recommended)
uv run --directory {baseDir} repowiki extract <target> --output extraction.json

# Extract to stdout
uv run --directory {baseDir} repowiki extract <target>

# Restrict to specific languages
uv run --directory {baseDir} repowiki extract <target> --languages python typescript

# Include private symbols
uv run --directory {baseDir} repowiki extract <target> --include-private
```

The JSON output has this shape:

```json
{
  "target": "<path>",
  "modules": [
    {
      "path": "src/auth/user.py",
      "language": "python",
      "description": "Module-level docstring or file comment.",
      "imports": ["os", "typing.List"],
      "classes": [
        {
          "name": "UserService",
          "description": "Manages user accounts.",
          "bases": ["BaseService"],
          "methods": [
            {
              "name": "create_user",
              "description": "Create a new user account.",
              "params": [
                { "name": "email", "type": "str", "description": "", "default": "" }
              ],
              "returns": "User",
              "is_async": false,
              "is_static": false
            }
          ]
        }
      ],
      "functions": [],
      "types": []
    }
  ],
  "skipped": []
}
```

## Phase 2 — Write wiki pages

After extraction, write one Markdown wiki page per module. Follow the rules below.

### Page structure

Each page must follow this structure:

```
# <module name>

<A concise paragraph describing what this module does and why it exists.
  Write this in your own words — do not just repeat the docstring verbatim.
  If there is no docstring, infer the purpose from the class and function names.>

**Source:** `<module.path>`

## <ClassName>

<Description of the class and its role. Mention base classes if relevant.>

### <methodName>

<What this method does, when to call it, and any important behaviour.>

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| <param> | <type> | <what it represents> | <default or blank> |

**Returns:** <what is returned and what it means>

## Functions

### <functionName>

<Description.>

## Dependencies

- `<import>`

## Types

**`<TypeName>`** — <what this type represents>
```

### Writing guidelines

- **Prose over structure** — every section heading must be followed by at least one sentence of explanation, never just a table or list with no context.
- **Infer intent** — if a function has no docstring, use its name, parameters, and return type to infer what it does and write a clear description.
- **Omit empty sections** — never emit a heading (`##`, `###`) when the corresponding data is absent. No heading may be immediately followed by another heading.
- **Async badge** — annotate async functions: `### myFunc \`async\``
- **Parameter tables** — include the parameter table only when a function has one or more parameters. Omit it entirely for zero-parameter functions.
- **HTML escaping** — escape `&`, `<`, `>` in any user-supplied text inserted into Markdown prose (outside code spans and fenced blocks).
- **Secret redaction** — never reproduce string literals that look like API keys, tokens, or passwords. Replace them with `[REDACTED]`.

### Output paths

Mirror the source directory structure under the output directory:

- `src/auth/user.py` → `<output_dir>/src/auth/user.md`
- `lib/utils/helpers.ts` → `<output_dir>/lib/utils/helpers.md`

### Index file

After writing all module pages, create an index file:

- **`github-wiki` style** → `<output_dir>/_Sidebar.md`
- **`docs-folder` style** → `<output_dir>/README.md`

Group entries by directory, sort alphabetically, and include exactly one link per module:

```markdown
## src/auth

- [user](src/auth/user.md)
- [session](src/auth/session.md)

## src/utils

- [helpers](src/utils/helpers.md)
```

## Demo / test mode (no LLM)

For testing the extraction and static rendering pipeline without agent involvement:

```bash
uv run --directory {baseDir} repowiki generate <target> --output-dir <dir> --style github-wiki
```

This writes Markdown files directly from the extracted structure, without any LLM enrichment. Useful for validating the extraction output and testing the pipeline end-to-end.

## Source Discovery rules

The extraction tool applies these rules automatically. They are documented here for reference.

- Supported extensions: `.py` → `python`, `.ts`/`.tsx` → `typescript`, `.cpp`/`.cc`/`.cxx`/`.hpp`/`.h` → `cpp`
- Skipped directories: `node_modules/`, `__pycache__/`, `dist/`, `build/`, `.venv/`
- Respects `.gitignore` exclusions
- Never follows symlinks outside the repository root
- Results are sorted by directory then filename (deterministic)

## Error handling

- If `skipped` in the JSON is non-empty, note the skipped files in the index or a warnings section.
- If a module has no classes, functions, or types, still create a stub page with the module description and source link.
- If the target does not exist or no supported files are found, report the error clearly and stop.
