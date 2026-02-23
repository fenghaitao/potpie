# SCIP — Precise Code Navigation

This folder contains tooling to generate and query a [SCIP](https://github.com/sourcegraph/scip)
index for the potpie Python codebase using [scip-python](https://github.com/sourcegraph/scip-python).

SCIP gives compiler-accurate symbol resolution (definitions + references) backed by Pyright,
replacing the current tree-sitter name-matching approach which produces false-positive edges
when multiple classes share a method name.

## Prerequisites

**Node.js** (for scip-python):
```bash
# scip-python is a Node.js CLI tool
npm install -g @sourcegraph/scip-python
scip-python --version   # should print e.g. 0.6.6
```

**Python protobuf + grpcio-tools** (to read the .scip output):
```bash
uv pip install grpcio-tools   # adds grpcio-tools + protobuf to the venv
```

## Step 1 — Generate the SCIP index

Run from the repo root with the venv active:

```bash
# Index the entire Python backend (~2.5 min for 326 files)
scip-python index app --project-name potpie --output index.scip

# Or index only a subdirectory
scip-python index app/modules/projects --project-name potpie --output index.scip
```

The output `index.scip` is a protobuf binary (~11 MB for the full repo).

> **Note:** scip-python has no incremental mode. Every run is a full re-index.
> Tie it to the existing commit-ID change detection so it only runs when a reparse is triggered.

## Step 2 — Generate Python protobuf bindings

Only needed once (or after updating scip.proto):

```bash
bash scip/generate_pb2.sh
# → produces scip/scip_pb2.py
```

`scip_pb2.py` is gitignored (generated file). `scip.proto` is committed as the schema source.

## Step 3 — Explore the index

```bash
.venv/bin/python scip/read_scip.py index.scip
```

This prints:
- Index summary (tool, version, document/symbol counts)
- Precise call sites for `register_project` (no false positives)
- All cross-file callers of every function in `parsing_service.py`

## SCIP symbol format

Each symbol is fully qualified:
```
scip-python python potpie 0.1.0 `app.modules.projects.projects_service`/ProjectService#register_project().
                                 ^module path                            ^class           ^method
```

This means `ProjectService#register_project` and `SomeOtherClass#register_project` are
distinct symbols — no name-collision false positives.

## Integration path (future)

Replace the name-matching loop in `parsing_repomap.py` with SCIP-derived edges:

1. Run `scip-python index` during `parse repo` (after tree-sitter graph construction)
2. Parse `index.scip` with `scip_pb2`
3. For every `(definition, reference)` pair where both paths are in the repo,
   emit a `REFERENCES` edge in Neo4j using the fully-qualified symbol as the key

This gives accurate `FUNCTION → FUNCTION` edges that respect class scope,
replacing the current ~15k name-matched edges with precise call graph edges.

## Files

| File | Purpose |
|------|---------|
| `scip.proto` | SCIP protobuf schema (from sourcegraph/scip) |
| `generate_pb2.sh` | Generates `scip_pb2.py` from the proto schema |
| `scip_pb2.py` | Generated Python bindings (gitignored) |
| `read_scip.py` | Example script to explore a .scip index |
