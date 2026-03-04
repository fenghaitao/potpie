# markdown_gen

Markdown generation for repowiki.

**Source:** `repowiki/markdown_gen.py`

## Dependencies

- `__future__.annotations`
- `os`
- `typing.List`
- `models.ClassDef`
- `models.CodeModule`
- `models.FunctionDef`
- `models.GeneratorOptions`
- `models.TypeDef`

## Functions

Top-level functions defined in this module.

### render_function

Function `render_function`.

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| fn | FunctionDef |  |  |

**Returns:** str

### generate_markdown

Function `generate_markdown`.

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| module | CodeModule |  |  |
| options | GeneratorOptions |  |  |

**Returns:** str
