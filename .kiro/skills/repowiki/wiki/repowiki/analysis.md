# analysis

Source code analysis for repowiki (Python, TypeScript, C++).

**Source:** `repowiki/analysis.py`

## Dependencies

- `__future__.annotations`
- `ast`
- `re`
- `pathlib.Path`
- `typing.List`
- `typing.Optional`
- `models.ClassDef`
- `models.CodeModule`
- `models.FunctionDef`
- `models.ParamDef`
- `models.SourceFile`
- `models.TypeDef`

## Types

**`_SECRET_NAME_RE`** — re.compile('(key|token|secret|password|passwd|credential|auth)', re.IGNORECASE)

**`_SECRET_VALUE_RE`** — re.compile('^(sk-|ghp_|xoxb-|AKIA|Bearer )|^[A-Za-z0-9+/]{20,64}$')

**`_TS_EXPORT_INTERFACE`** — re.compile('export\\s+interface\\s+(\\w+)')

**`_TS_EXPORT_CLASS`** — re.compile('export\\s+(?:abstract\\s+)?class\\s+(\\w+)')

**`_TS_EXPORT_FUNCTION`** — re.compile('export\\s+(?:async\\s+)?function\\s+(\\w+)\\s*\\(([^)]*)\\)')

**`_TS_EXPORT_ARROW`** — re.compile('export\\s+const\\s+(\\w+)\\s*=\\s*(?:async\\s*)?\\(([^)]*)\\)\\s*(?::\\s*\\S+)?\\s*=&gt;')

**`_TS_EXPORT_TYPE`** — re.compile('export\\s+type\\s+(\\w+)')

**`_TS_EXPORT_ENUM`** — re.compile('export\\s+enum\\s+(\\w+)')

**`_TS_FILE_COMMENT`** — re.compile('^(?:\\s*(?:/\\*[\\s\\S]*?\\*/|//[^\\n]*))+', re.MULTILINE)

**`_TS_ASYNC`** — re.compile('\\basync\\b')

**`_CPP_CLASS`** — re.compile('(?:class|struct)\\s+(\\w+)')

**`_CPP_FREE_FN`** — re.compile('^[\\w:*&amp;&lt;&gt;\\s]+\\s+(\\w+)\\s*\\(([^)]*)\\)\\s*(?:const\\s*)?[;{]', re.MULTILINE)

**`_CPP_DOXYGEN`** — re.compile('(?:/\\*\\*[\\s\\S]*?\\*/|///[^\\n]*(?:\\n///[^\\n]*)*)')

**`_CPP_FILE_COMMENT`** — re.compile('^(?:\\s*(?:/\\*[\\s\\S]*?\\*/|//[^\\n]*))+', re.MULTILINE)

**`_HEADER_EXTS`** — {'.hpp', '.h'}

## Functions

Top-level functions defined in this module.

### analyze_file

Analyze a source file and return a CodeModule, or None if it cannot be parsed.
Caller is responsible for adding to skipped_files on None return.

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| sf | SourceFile |  |  |
| include_private | bool |  | False |

**Returns:** Optional[CodeModule]
