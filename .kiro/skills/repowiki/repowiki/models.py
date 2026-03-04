"""Data models for repowiki."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SourceFile:
    path: str
    language: str  # "python" | "typescript" | "cpp"


@dataclass
class ParamDef:
    name: str
    type: str = ""
    description: str = ""
    default: str = ""


@dataclass
class FunctionDef:
    name: str
    description: str = ""
    params: List[ParamDef] = field(default_factory=list)
    returns: str = ""
    is_async: bool = False
    is_static: bool = False


@dataclass
class ClassDef:
    name: str
    description: str = ""
    bases: List[str] = field(default_factory=list)
    methods: List[FunctionDef] = field(default_factory=list)


@dataclass
class TypeDef:
    name: str
    description: str = ""


@dataclass
class CodeModule:
    path: str
    language: str
    description: str = ""
    imports: List[str] = field(default_factory=list)
    classes: List[ClassDef] = field(default_factory=list)
    functions: List[FunctionDef] = field(default_factory=list)
    types: List[TypeDef] = field(default_factory=list)


@dataclass
class GeneratorOptions:
    include_private: bool = False
    output_style: str = "docs-folder"  # "github-wiki" | "docs-folder"


@dataclass
class GenerationRequest:
    target: str
    output_dir: str = "docs"
    output_style: str = "docs-folder"
    include_private: bool = False
    languages: List[str] = field(default_factory=list)  # empty = all supported


@dataclass
class GenerationResult:
    files_analyzed: int = 0
    docs_generated: int = 0
    output_paths: List[str] = field(default_factory=list)
    skipped_files: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
