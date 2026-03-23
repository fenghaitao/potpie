"""
read_scip.py — explore a .scip index produced by scip-python.

Usage:
    # from repo root
    .venv/bin/python scip/read_scip.py [path/to/index.scip]

If no path is given, defaults to index.scip in the repo root.

Supports looking up any symbol kind: method, class, variable, attribute.

The key difference vs. the current tree-sitter name-matching approach:
  - Each symbol is fully qualified (module + class + name)
  - References are compiler-accurate — no false positives from name collisions
"""
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

# scip_pb2.py must be in the same directory. It should be generated at build time
# using 'bash scip/generate_pb2.sh'. Runtime generation is no longer supported.
_SCIP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCIP_DIR))

_scip_pb2_path = _SCIP_DIR / "scip_pb2.py"
if not _scip_pb2_path.exists():
    raise FileNotFoundError(
        f"scip_pb2.py not found in {_SCIP_DIR}. "
        f"Run 'bash scip/generate_pb2.sh' to generate it, or ensure it's included in your deployment."
    )

import scip_pb2  # noqa: E402  (generated protobuf bindings)


# ── data types ───────────────────────────────────────────────────────


@dataclass
class SymbolLocation:
    """A symbol occurrence with start/end line info.

    ``line`` is the 0-based start line (from ``Occurrence.range[0]``).
    ``end_line`` is the 0-based end line of the enclosing AST node
    (from ``Occurrence.enclosing_range``).  When the enclosing range is
    absent or single-line, ``end_line`` equals ``line``.
    """
    symbol: str
    symbol_base: list[str]
    line: int
    end_line: int = -1
    is_def: bool = False
    text: str = ""


@dataclass
class DocumentRecord:
    """All occurrences found in a single source file."""
    relative_path: str
    occurrences: List[SymbolLocation] = field(default_factory=list)  # all occurrences, defs and refs


# ── helpers ──────────────────────────────────────────────────────────

ROLE_DEFINITION = scip_pb2.SymbolRole.Value("Definition")


def _end_line_from_range(r) -> int:
    """Extract the end line from a SCIP repeated-int32 range.

    SCIP ranges are either:
      - 4 elements: ``[startLine, startChar, endLine, endChar]``
      - 3 elements: ``[startLine, startChar, endChar]`` (endLine == startLine)
    Returns ``startLine`` for 3-element ranges, ``endLine`` for 4-element.
    """
    if len(r) >= 4:
        return r[2]
    if len(r) >= 3:
        return r[0]   # single-line range
    return -1


def load_index(scip_path: str) -> scip_pb2.Index:
    with open(scip_path, "rb") as f:
        idx = scip_pb2.Index()
        idx.ParseFromString(f.read())
    return idx


def build_maps(index: scip_pb2.Index):
    """Return (definitions, references) dicts keyed by symbol string."""
    definitions: dict[str, tuple[str, int]] = {}        # sym -> (path, line)
    references:  dict[str, list[tuple[str, int]]] = {}  # sym -> [(path, line)]

    for doc in index.documents:
        path = doc.relative_path
        for occ in doc.occurrences:
            sym  = occ.symbol
            line = occ.range[0]
            if occ.symbol_roles & ROLE_DEFINITION:
                definitions[sym] = (path, line)
            else:
                references.setdefault(sym, []).append((path, line))

    return definitions, references


def build_document_records(index: scip_pb2.Index) -> Dict[str, DocumentRecord]:
    """Return a dict mapping relative_path -> DocumentRecord.

    Each DocumentRecord contains the file's definitions and references
    as SymbolLocation objects with fully-qualified symbol strings.
    """
    records: Dict[str, DocumentRecord] = {}

    for doc in index.documents:
        record = DocumentRecord(relative_path=doc.relative_path)

        _extends = {}
        for sym in doc.symbols:
            for rel in sym.relationships:
                if rel.is_implementation:
                    _extends.setdefault(sym.symbol, []).append(rel.symbol)

        for occ in doc.occurrences:
            start_line = occ.range[0] if occ.range else 0
            # For definitions, prefer enclosing_range (full AST extent
            # including body); fall back to range when absent.
            if occ.symbol_roles & ROLE_DEFINITION and occ.enclosing_range:
                end_line = _end_line_from_range(occ.enclosing_range)
            else:
                end_line = _end_line_from_range(occ.range)

            loc = SymbolLocation(
                symbol=occ.symbol,
                symbol_base=_extends.get(occ.symbol, []),
                line=start_line,
                end_line=end_line,
                is_def=bool(occ.symbol_roles & ROLE_DEFINITION),
            )
            record.occurrences.append(loc)
        records[doc.relative_path] = record

    return records


def symbol_kind(sym: str) -> str:
    """Classify a SCIP symbol by its descriptor suffix.

    SCIP descriptor suffixes:
      method/function : ends with  ")."    e.g.  Class#method().
      parameter       : ends with  ")"     e.g.  Class#method().(param)
      class           : ends with  "#"     e.g.  Class#
      module          : ends with  "/"     e.g.  module/
      variable/attr   : ends with  "."     e.g.  Class#attr.  or  var.
    """
    descriptor = sym.split(" ", 4)[-1] if " " in sym else sym
    if descriptor.endswith(")."):
        return "method"
    if descriptor.endswith(")"):
        return "parameter"
    if descriptor.endswith("#"):
        return "class"
    if descriptor.endswith("/"):
        return "module"
    return "variable"   # module-level var, instance attr, or class var


def short_name(sym: str) -> str:
    """Extract a readable name from a SCIP symbol descriptor.

    For class symbols like ``models/Greeting#`` the name sits *before*
    the ``#``; for members like ``Greeting#greet().`` it is after ``#``.
    """
    descriptor = sym.split(" ", 4)[-1] if " " in sym else sym
    if "`" in descriptor:
        descriptor = descriptor.split("`")[-1].lstrip("`/")
    if "#" in descriptor:
        parts = descriptor.split("#")
        after_hash = parts[-1].rstrip("#/(). ")
        if after_hash:
            return after_hash
        # Class symbol — name is the segment just before '#'
        before_hash = parts[-2] if len(parts) > 1 else ""
        return before_hash.rstrip("/").rsplit("/", 1)[-1]
    return descriptor.rstrip("#/(). ")


def qualified_name(sym: str) -> str:
    """Extract a human-readable qualified name from a SCIP symbol.

    Returns 'ClassName.member' for class members, or just 'name' for
    top-level symbols.  Useful for display while the raw SCIP symbol
    string is used as a precise matching key (``tag.ident``).

    Examples:
        '... AgentRunner#run().'  → 'AgentRunner.run'
        '... AgentRunner#'        → 'AgentRunner'
        '... DEFAULT_MODEL.'      → 'DEFAULT_MODEL'
    """
    descriptor = sym.split(" ", 4)[-1] if " " in sym else sym
    if "`" in descriptor:
        descriptor = descriptor.split("`")[-1].lstrip("`/")
    if "#" in descriptor:
        parts = descriptor.split("#")
        class_part = (
            parts[-2].rstrip("/").rsplit("/", 1)[-1] if len(parts) > 1 else ""
        )
        member_part = parts[-1].rstrip("#/(). ")
        if class_part and member_part:
            return f"{class_part}.{member_part}"
        return class_part or member_part
    # No class context — top-level symbol
    return descriptor.rsplit("/", 1)[-1].rstrip("#/(). ")


# ── main ─────────────────────────────────────────────────────────────

def find_and_print(
    fragment: str,
    definitions: dict,
    references: dict,
    skip_kinds: tuple = ("parameter",),
    limit: int = 4,
):
    """Find symbols matching fragment and print their reference sites."""
    matches = [
        (s, d) for s, d in definitions.items()
        if fragment in s and symbol_kind(s) not in skip_kinds
    ]
    if not matches:
        print(f"  (no symbols found matching '{fragment}')\n")
        return
    for sym, (def_path, def_line) in matches[:limit]:
        refs = references.get(sym, [])
        kind = symbol_kind(sym)
        print(f"[{kind}] {short_name(sym)}")
        print(f"  Symbol : {sym}")
        print(f"  Defined: {def_path}:{def_line + 1}")
        print(f"  References ({len(refs)} sites):")
        for ref_path, ref_line in refs[:6]:
            print(f"    {ref_path}:{ref_line + 1}")
        print()


def main():
    scip_path = sys.argv[1] if len(sys.argv) > 1 else "index.scip"

    print(f"Loading {scip_path} ...")
    index = load_index(scip_path)
    print(f"Tool : {index.metadata.tool_info.name} {index.metadata.tool_info.version}")
    print(f"Docs : {len(index.documents)}")
    for doc in index.documents:
        print(f"  {doc.relative_path}  ({len(doc.occurrences)} occurrences)")

    definitions, references = build_maps(index)

    kinds = Counter(symbol_kind(s) for s in definitions)
    print(f"Symbols: {len(definitions)} defined  |  {len(references)} referenced")
    for kind, count in sorted(kinds.items()):
        print(f"  {kind:<12} {count}")
    print()

    # ── 1. Method lookup ─────────────────────────────────────────────
    print("=== Method: register_project ===")
    find_and_print("register_project", definitions, references)

    # ── 2. Variable / attribute lookup ───────────────────────────────
    print("=== Variable: default_user_id (CLIContext instance attr) ===")
    find_and_print("default_user_id", definitions, references)

    # ── 3. Class lookup ──────────────────────────────────────────────
    print("=== Class: ProjectService ===")
    find_and_print(
        "ProjectService#",
        definitions, references,
        skip_kinds=("parameter", "method", "variable"),
    )

    # ── 4. Cross-file callers of parsing_service.py (methods only) ───
    print("=" * 60)
    print("Cross-file callers of methods in parsing_service.py")
    print("=" * 60)

    for sym, (def_path, def_line) in sorted(definitions.items(), key=lambda x: x[1][1]):
        if "parsing_service" not in def_path:
            continue
        if symbol_kind(sym) != "method":
            continue
        refs = references.get(sym, [])
        cross = [(p, l) for p, l in refs if "parsing_service" not in p]
        if not cross:
            continue
        print(f"\n  {short_name(sym)}  ({def_path}:{def_line + 1})")
        for p, l in cross:
            print(f"    <- {p}:{l + 1}")


if __name__ == "__main__":
    main()
