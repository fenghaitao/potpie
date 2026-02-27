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
from pathlib import Path

# scip_pb2.py must be in the same directory; generate it first with:
#   bash scip/generate_pb2.sh
sys.path.insert(0, str(Path(__file__).parent))
import scip_pb2  # noqa: E402  (generated protobuf bindings)


# ── helpers ──────────────────────────────────────────────────────────

ROLE_DEFINITION = scip_pb2.SymbolRole.Value("Definition")


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
    """Extract a readable name from a SCIP symbol descriptor."""
    descriptor = sym.split(" ", 4)[-1] if " " in sym else sym
    if "`" in descriptor:
        descriptor = descriptor.split("`")[-1].lstrip("`/")
    if "#" in descriptor:
        descriptor = descriptor.split("#")[-1]
    return descriptor.rstrip("#/(). ")


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
