"""Source code analysis for repowiki (Python, TypeScript, C++)."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import List, Optional

from .models import ClassDef, CodeModule, FunctionDef, ParamDef, SourceFile, TypeDef

# Patterns that look like secrets — suppress their values
_SECRET_NAME_RE = re.compile(
    r"(key|token|secret|password|passwd|credential|auth)", re.IGNORECASE
)
_SECRET_VALUE_RE = re.compile(
    r"^(sk-|ghp_|xoxb-|AKIA|Bearer )|^[A-Za-z0-9+/]{20,64}$"
)


def _redact(name: str, value: str) -> str:
    if _SECRET_NAME_RE.search(name) or _SECRET_VALUE_RE.match(value):
        return "[REDACTED]"
    return value


# ---------------------------------------------------------------------------
# Python analysis
# ---------------------------------------------------------------------------

def _py_param(arg: ast.arg, defaults_map: dict) -> ParamDef:
    name = arg.arg
    type_str = ast.unparse(arg.annotation) if arg.annotation else ""
    default_str = ast.unparse(defaults_map.get(name, "")) if name in defaults_map else ""
    return ParamDef(name=name, type=type_str, default=default_str)


def _py_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> FunctionDef:
    doc = ast.get_docstring(node) or ""
    args = node.args
    # Build defaults map: last N args get the last N defaults
    all_args = args.posonlyargs + args.args + (([args.vararg] if args.vararg else []) +
               args.kwonlyargs + ([args.kwarg] if args.kwarg else []))
    positional = args.posonlyargs + args.args
    defaults_map: dict = {}
    for arg, default in zip(reversed(positional), reversed(args.defaults)):
        defaults_map[arg.arg] = default

    params = [_py_param(a, defaults_map) for a in positional if a.arg != "self"]
    returns = ast.unparse(node.returns) if node.returns else ""
    is_async = isinstance(node, ast.AsyncFunctionDef)
    is_static = any(
        (isinstance(d, ast.Name) and d.id == "staticmethod") or
        (isinstance(d, ast.Attribute) and d.attr == "staticmethod")
        for d in node.decorator_list
    )
    return FunctionDef(
        name=node.name,
        description=doc,
        params=params,
        returns=returns,
        is_async=is_async,
        is_static=is_static,
    )


def _analyze_python(sf: SourceFile, include_private: bool) -> CodeModule:
    source = Path(sf.path).read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source)

    module = CodeModule(path=sf.path, language="python")
    module.description = ast.get_docstring(tree) or ""

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module.imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                module.imports.append(f"{mod}.{alias.name}" if mod else alias.name)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not include_private and node.name.startswith("_"):
                continue
            module.functions.append(_py_function(node))

        elif isinstance(node, ast.ClassDef):
            if not include_private and node.name.startswith("_"):
                continue
            bases = [ast.unparse(b) for b in node.bases]
            cls = ClassDef(
                name=node.name,
                description=ast.get_docstring(node) or "",
                bases=bases,
            )
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not include_private and item.name.startswith("_"):
                        continue
                    cls.methods.append(_py_function(item))
            module.classes.append(cls)

        elif isinstance(node, ast.Assign):
            # Top-level type aliases
            for target in node.targets:
                if isinstance(target, ast.Name):
                    val = ast.unparse(node.value)
                    module.types.append(TypeDef(name=target.id, description=val))

        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            module.types.append(TypeDef(name=node.target.id, description=ast.unparse(node.annotation)))

    return module


# ---------------------------------------------------------------------------
# TypeScript analysis (regex-based, no full parser)
# ---------------------------------------------------------------------------

_TS_EXPORT_INTERFACE = re.compile(r"export\s+interface\s+(\w+)")
_TS_EXPORT_CLASS = re.compile(r"export\s+(?:abstract\s+)?class\s+(\w+)")
_TS_EXPORT_FUNCTION = re.compile(r"export\s+(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)")
_TS_EXPORT_ARROW = re.compile(r"export\s+const\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*(?::\s*\S+)?\s*=>")
_TS_EXPORT_TYPE = re.compile(r"export\s+type\s+(\w+)")
_TS_EXPORT_ENUM = re.compile(r"export\s+enum\s+(\w+)")
_TS_FILE_COMMENT = re.compile(r"^(?:\s*(?:/\*[\s\S]*?\*/|//[^\n]*))+", re.MULTILINE)
_TS_ASYNC = re.compile(r"\basync\b")


def _analyze_typescript(sf: SourceFile, include_private: bool) -> CodeModule:
    source = Path(sf.path).read_text(encoding="utf-8", errors="replace")
    module = CodeModule(path=sf.path, language="typescript")

    # File-level comment
    m = _TS_FILE_COMMENT.match(source)
    if m:
        module.description = m.group(0).strip()

    if not include_private:
        # Only exported symbols
        for m in _TS_EXPORT_INTERFACE.finditer(source):
            module.classes.append(ClassDef(name=m.group(1)))
        for m in _TS_EXPORT_CLASS.finditer(source):
            module.classes.append(ClassDef(name=m.group(1)))
        for m in _TS_EXPORT_FUNCTION.finditer(source):
            is_async = bool(_TS_ASYNC.search(source[max(0, m.start()-10):m.start()+20]))
            params = [ParamDef(name=p.strip().split(":")[0].strip())
                      for p in m.group(2).split(",") if p.strip()]
            module.functions.append(FunctionDef(name=m.group(1), params=params, is_async=is_async))
        for m in _TS_EXPORT_ARROW.finditer(source):
            is_async = "async" in source[max(0, m.start()-5):m.start()+30]
            params = [ParamDef(name=p.strip().split(":")[0].strip())
                      for p in m.group(2).split(",") if p.strip()]
            module.functions.append(FunctionDef(name=m.group(1), params=params, is_async=is_async))
        for m in _TS_EXPORT_TYPE.finditer(source):
            module.types.append(TypeDef(name=m.group(1)))
        for m in _TS_EXPORT_ENUM.finditer(source):
            module.types.append(TypeDef(name=m.group(1)))

    return module


# ---------------------------------------------------------------------------
# C++ analysis (regex-based)
# ---------------------------------------------------------------------------

_CPP_CLASS = re.compile(r"(?:class|struct)\s+(\w+)")
_CPP_FREE_FN = re.compile(r"^[\w:*&<>\s]+\s+(\w+)\s*\(([^)]*)\)\s*(?:const\s*)?[;{]", re.MULTILINE)
_CPP_DOXYGEN = re.compile(r"(?:/\*\*[\s\S]*?\*/|///[^\n]*(?:\n///[^\n]*)*)")
_CPP_FILE_COMMENT = re.compile(r"^(?:\s*(?:/\*[\s\S]*?\*/|//[^\n]*))+", re.MULTILINE)
_HEADER_EXTS = {".hpp", ".h"}


def _analyze_cpp(sf: SourceFile, include_private: bool) -> CodeModule:
    source = Path(sf.path).read_text(encoding="utf-8", errors="replace")
    module = CodeModule(path=sf.path, language="cpp")

    m = _CPP_FILE_COMMENT.match(source)
    if m:
        module.description = m.group(0).strip()

    for m in _CPP_CLASS.finditer(source):
        module.classes.append(ClassDef(name=m.group(1)))

    # Free functions in headers
    if Path(sf.path).suffix in _HEADER_EXTS:
        for m in _CPP_FREE_FN.finditer(source):
            name = m.group(1)
            if name in {"if", "while", "for", "switch", "return"}:
                continue
            params = [ParamDef(name=p.strip()) for p in m.group(2).split(",") if p.strip()]
            module.functions.append(FunctionDef(name=name, params=params))

    return module


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyze_file(sf: SourceFile, include_private: bool = False) -> Optional[CodeModule]:
    """
    Analyze a source file and return a CodeModule, or None if it cannot be parsed.
    Caller is responsible for adding to skipped_files on None return.
    """
    try:
        if sf.language == "python":
            return _analyze_python(sf, include_private)
        elif sf.language == "typescript":
            return _analyze_typescript(sf, include_private)
        elif sf.language == "cpp":
            return _analyze_cpp(sf, include_private)
    except Exception:
        return None
    return CodeModule(path=sf.path, language=sf.language)
