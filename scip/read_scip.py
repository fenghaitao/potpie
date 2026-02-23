"""
read_scip.py — explore a .scip index produced by scip-python.

Usage:
    # from repo root
    .venv/bin/python scip/read_scip.py [path/to/index.scip]

If no path is given, defaults to index.scip in the repo root.

What this script shows:
  1. Index summary (tool, version, document count, symbol counts)
  2. Precise call sites for a specific function (register_project)
  3. All cross-file callers of every function defined in parsing_service.py

The key difference vs. the current tree-sitter name-matching approach:
  - Each symbol is fully qualified (module + class + method)
  - References are compiler-accurate — no false positives from name collisions
"""
import sys
from pathlib import Path

# scip_pb2.py must be in the same directory; generate it first with:
#   bash scip/generate_pb2.sh
sys.path.insert(0, str(Path(__file__).parent))
import scip_pb2  # noqa: E402  (generated protobuf bindings)


# ── helpers ─────────────────────────────────────────────────────────

ROLE_DEFINITION = scip_pb2.SymbolRole.Value("Definition")


def load_index(scip_path: str) -> scip_pb2.Index:
    with open(scip_path, "rb") as f:
        idx = scip_pb2.Index()
        idx.ParseFromString(f.read())
    return idx


def build_maps(index: scip_pb2.Index):
    """Return (definitions, references) dicts keyed by symbol string."""
    definitions: dict[str, tuple[str, int]] = {}   # sym -> (path, line)
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


def short_name(sym: str) -> str:
    """Extract a readable name from a SCIP symbol descriptor."""
    # SCIP format: "scip-python python <pkg> <ver> `module`/Class#method()."
    if "`" in sym:
        return sym.split("`")[-1].rstrip("`().")
    return sym.split("/")[-1]


# ── main ─────────────────────────────────────────────────────────────

def main():
    scip_path = sys.argv[1] if len(sys.argv) > 1 else "index.scip"

    print(f"Loading {scip_path} ...")
    index = load_index(scip_path)

    print(f"Tool    : {index.metadata.tool_info.name} {index.metadata.tool_info.version}")
    print(f"Docs    : {len(index.documents)}")

    definitions, references = build_maps(index)
    print(f"Symbols defined    : {len(definitions)}")
    print(f"Symbols referenced : {len(references)}")
    print()

    # ── 1. Precise call sites for a specific method ──────────────────
    TARGET = "register_project"
    matches = [(s, d) for s, d in definitions.items() if TARGET in s
               # method symbols end with ")." — parameters end with ").(name)"
               and s.endswith(").")]

    print(f"=== Call sites for '{TARGET}' ===")
    for sym, (def_path, def_line) in matches[:5]:
        refs = references.get(sym, [])
        print(f"\nSymbol : {sym}")
        print(f"Defined: {def_path}:{def_line + 1}")
        print(f"Called from ({len(refs)} sites):")
        for ref_path, ref_line in refs:
            print(f"  {ref_path}:{ref_line + 1}")

    # ── 2. Cross-file callers of parsing_service.py ──────────────────
    print()
    print("=" * 60)
    print("Cross-file callers of functions in parsing_service.py")
    print("=" * 60)

    for sym, (def_path, def_line) in sorted(definitions.items(), key=lambda x: x[1][1]):
        if "parsing_service" not in def_path:
            continue
        # only method definitions — method symbols end with ").", params end with ").(name)"
        if not sym.endswith(")."):
            continue
        refs = references.get(sym, [])
        cross = [(p, l) for p, l in refs if "parsing_service" not in p]
        if not cross:
            continue
        name = short_name(sym)
        print(f"\n  {name}  ({def_path}:{def_line + 1})")
        for p, l in cross:
            print(f"    <- {p}:{l + 1}")


if __name__ == "__main__":
    main()
