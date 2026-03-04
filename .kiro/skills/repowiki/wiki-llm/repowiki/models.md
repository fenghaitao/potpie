# models

Shared data models used throughout repowiki. All types are plain Python dataclasses with no behaviour — they carry structured data between the discovery, analysis, generation, and dispatch layers.

**Source:** `repowiki/models.py`

## SourceFile

Represents a single source file found during discovery. Holds the file's relative path and its detected language tag (`"python"`, `"typescript"`, or `"cpp"`).

## ParamDef

Describes one parameter of a function or method: its name, type annotation, an optional description extracted from the docstring, and its default value if present.

## FunctionDef

Describes a function or method. Includes its name, docstring, list of `ParamDef` parameters, return type annotation, and flags for whether it is async or static.

## ClassDef

Describes a class definition. Holds the class name, its docstring, the list of base class names, and a list of `FunctionDef` objects for its methods.

## TypeDef

Describes a top-level type alias, `TypedDict`, `NamedTuple`, or exported TypeScript type/enum. Holds the name and a short description derived from the right-hand side of the assignment.

## CodeModule

The central output of the analysis phase. Aggregates everything extracted from one source file: path, language, module-level description, imports, classes, top-level functions, and type definitions.

## GeneratorOptions

Controls Markdown rendering. `include_private` determines whether private symbols are included. `output_style` selects between `"docs-folder"` and `"github-wiki"` index formats.

## GenerationRequest

The input to the full dispatch pipeline. Specifies the target path, output directory, output style, language filter, and whether private symbols should be included.

## GenerationResult

The output of the full dispatch pipeline. Reports files analysed, docs generated, all output paths written, files skipped due to parse errors, and any warning messages.
