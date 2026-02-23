"""
Example: read potpie.scip and explore precise symbol references.
Shows definitions and cross-file references for Python functions.

Usage:
    .venv/bin/python scripts/read_scip.py
"""
import sys
sys.path.insert(0, '/tmp')  # where scip_pb2.py was generated

import scip_pb2

# ── Load the index ──────────────────────────────────────────────────
SCIP_PATH = '/tmp/potpie.scip'

with open(SCIP_PATH, 'rb') as f:
    index = scip_pb2.Index()
    index.ParseFromString(f.read())

print(f"Metadata: tool={index.metadata.tool_info.name}  version={index.metadata.tool_info.version}")
print(f"Documents: {len(index.documents)}")
print()

# ── Build symbol -> definition and symbol -> references maps ─────────
# occurrence.symbol_roles is a bitmask; bit 0 = Definition
ROLE_DEFINITION = scip_pb2.SymbolRole.Value('Definition')

definitions = {}   # symbol_str -> (relative_path, line)
references  = {}   # symbol_str -> [(relative_path, line)]

for doc in index.documents:
    path = doc.relative_path
    for occ in doc.occurrences:
        sym  = occ.symbol
        line = occ.range[0]
        is_def = bool(occ.symbol_roles & ROLE_DEFINITION)
        if is_def:
            definitions[sym] = (path, line)
        else:
            references.setdefault(sym, []).append((path, line))

print(f"Unique symbols defined:    {len(definitions)}")
print(f"Unique symbols referenced: {len(references)}")
print()

# ── Example 1: precise references to register_project ───────────────
target = 'register_project'
matches = [(s, d) for s, d in definitions.items() if target in s]

for sym, (def_path, def_line) in matches[:3]:
    refs = references.get(sym, [])
    print(f"Symbol : {sym}")
    print(f"Defined: {def_path}:{def_line + 1}")
    print(f"Referenced from ({len(refs)} sites):")
    for ref_path, ref_line in refs[:8]:
        print(f"  {ref_path}:{ref_line + 1}")
    print()

# ── Example 2: cross-file callers of parsing_service functions ───────
print("─" * 60)
print("Cross-file references INTO parsing_service.py:")
print("─" * 60)
for sym, (def_path, def_line) in definitions.items():
    if 'parsing_service' not in def_path:
        continue
    refs = references.get(sym, [])
    cross = [(p, l) for p, l in refs if 'parsing_service' not in p]
    if not cross:
        continue
    # pull readable name from SCIP symbol descriptor
    name = sym.split('`')[-1].rstrip('`().') if '`' in sym else sym.split('/')[-1]
    print(f"  {name}  (defined {def_path}:{def_line + 1})")
    for p, l in cross[:5]:
        print(f"    <- {p}:{l + 1}")
