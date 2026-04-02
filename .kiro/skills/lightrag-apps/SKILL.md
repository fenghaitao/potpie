---
name: lightrag-apps
description: Index any code repository into a LightRAG knowledge graph and query it with natural language. Supports hybrid, global, and local query modes.
homepage: https://github.com/fenghaitao/repowiki
metadata: {"clawdbot":{"emoji":"📚","requires":{"bins":["uv"]}}}
---

# spec-graph - LightRAG Knowledge Graph

Index any code repository into a LightRAG knowledge graph and query it with natural language.

## Quick Start

### Index and Query a Repository
```bash
# Test setup
uv run --directory {baseDir} spec-graph test

# Index repository
uv run --directory {baseDir} spec-graph index --repo /path/to/project

# Query the indexed graph
uv run --directory {baseDir} spec-graph query "Tell me about X"
```

### Index Specific Repository
```bash
uv run --directory {baseDir} spec-graph index --repo /path/to/project
```

## Features

✅ **Works with any repository** - Not limited to specific projects
✅ **Auto-detects repo name** - From git remote or directory name
✅ **Works out of the box** - Uses GitHub Copilot models by default
✅ **Maximum parallel processing** - Optimized for GitHub Copilot Business
✅ **Persistent .venv** - Fast execution with managed dependencies
✅ **Smart query modes** - global, local, hybrid

## Commands

### Test Setup
```bash
uv run --directory {baseDir} spec-graph test
```
Validates configuration, checks dependencies, and verifies repository access.

### Index Repository
```bash
# Index current directory
uv run --directory {baseDir} spec-graph index

# Index specific repository
uv run --directory {baseDir} spec-graph index --repo /path/to/project

# Custom working directory (also accepts -s)
uv run --directory {baseDir} spec-graph index --working-dir ./my-graph
```

### Query Knowledge Graph

Query an already-indexed graph directory.

```bash
# Query using the default working directory (./spec_graph_storage)
uv run --directory {baseDir} spec-graph query "Tell me about watchdog timer"

# Query a specific graph directory (--working-dir / -s)
uv run --directory {baseDir} spec-graph query -s /path/to/graph-dir "Tell me about watchdog timer"

# Workspace-relative path works when called via uv run --directory
uv run --directory {baseDir} spec-graph query -s imh-punit-merged-graph/ "Explain the reset sequence"

# Use a different query mode (default: hybrid)
uv run --directory {baseDir} spec-graph query -s ./my-graph --mode local "How does X work?"
uv run --directory {baseDir} spec-graph query -s ./my-graph -m global "What are the main components?"
```

**Options:**

| Flag | Short | Description | Default |
|------|-------|-------------|---------|
| `--working-dir` | `-s` | Path to LightRAG graph directory (must already exist) | `./spec_graph_storage` |
| `--mode` | `-m` | Query mode: `local`, `global`, `hybrid` | `hybrid` |

> **Note:** `--working-dir` must point to a directory previously built by `spec-graph index`. The command exits with a configuration error if the directory does not exist.

## Configuration

### Environment Variables (Optional)

```bash
export REPO_PATH="/path/to/project"
export WORKING_DIR="./spec_graph_storage"
export WORKSPACE=""                      # subfolder inside WORKING_DIR (default: empty)
export REPO_NAME="My Project"
export LLM_MODEL="github_copilot/gpt-4o"
export EMBEDDING_MODEL="github_copilot/text-embedding-3-small"
export API_KEY="oauth2"                  # override Copilot oauth token
```

### Default Configuration

Uses GitHub Copilot models by default (free with GitHub Copilot license):

- **LLM Model**: `github_copilot/gpt-4o` (128K context)
- **Embedding Model**: `github_copilot/text-embedding-3-small`
- **API Key**: `oauth2` (automatic with GitHub Copilot)
- **Working Directory**: `./spec_graph_storage`
- **Workspace**: *(empty)* — graph files written directly into working_dir

## Query Modes

The `query` command supports these modes:

- **hybrid** *(default)* - Balance breadth and depth; combines keyword and vector search
- **global** - Search across the entire knowledge graph
- **local** - Focus on locally connected nodes around the matched entities

## Performance

**Indexing**: First-time indexing may take longer for large repositories
**Parallelism**: Optimized for GitHub Copilot Business (48/96/48 concurrent calls)

## Examples

### Index and Query Your Own Project
```bash
uv run --directory /path/to/lightrag-apps spec-graph index --repo /path/to/your/project
uv run --directory /path/to/lightrag-apps spec-graph query "What does this project do?"
```

### Re-index After Code Changes
```bash
uv run --directory {baseDir} spec-graph index --repo /path/to/project
uv run --directory {baseDir} spec-graph query "What changed recently?"
```

## File Support

By default, indexes:
- **Python files**: `.py`
- **Markdown files**: `.md`
- **Text files**: `.txt`

Skips files smaller than 50 bytes (configurable via `MIN_FILE_SIZE` environment variable).

## Troubleshooting

### Check Setup
```bash
uv run --directory {baseDir} spec-graph test
```

### Common Issues

**Repository not found**
```bash
# Specify path explicitly
uv run --directory {baseDir} spec-graph index --repo /full/path/to/project
```

**Import errors**
**GitHub Copilot not working**
- Ensure you have an active GitHub Copilot license
- Check that you're signed in to GitHub in your IDE
- Try using a different model by setting the `LLM_MODEL` environment variable, for example: `LLM_MODEL=gpt-4o-mini`

## Output Files

After indexing, you'll find:

```
spec_graph_storage/         # Knowledge graph storage
  ├── kv_store_*.json     # Entity / relation / chunk key-value stores
  ├── vdb_*.json          # Vector DB files (entities, relationships, chunks)
  ├── graph_chunk_entity_relation.graphml
  └── ...                 # (Stored directly here when WORKSPACE is empty)
```

> If `WORKSPACE` is set, graph files are written to `spec_graph_storage/<workspace>/` instead.

## Advanced Usage

### Custom Parallel Processing

```bash
export MAX_PARALLEL_INSERT=48
export LLM_MODEL_MAX_ASYNC=96
export EMBEDDING_FUNC_MAX_ASYNC=48
uv run --directory {baseDir} spec-graph index --repo /path/to/project
```

### Custom File Extensions

Edit the script's `code_extensions` configuration to include additional file types.

### Multiple Workspaces

The `WORKSPACE` env var (or `--working-dir` pointing to different directories) lets you
maintain separate graphs for different projects or branches:

```bash
# Index into a named subdirectory
export WORKSPACE="experimental"
export WORKING_DIR="./spec_graph_storage"
uv run --directory {baseDir} spec-graph index --repo /path/to/project
# Files land in ./spec_graph_storage/experimental/

# Or simply use different --working-dir paths
uv run --directory {baseDir} spec-graph index --repo projectA --working-dir ./graph-A
uv run --directory {baseDir} spec-graph index --repo projectB --working-dir ./graph-B
uv run --directory {baseDir} spec-graph query -s ./graph-A "What does projectA do?"
uv run --directory {baseDir} spec-graph query -s ./graph-B "What does projectB do?"
```

## Integration

### Git Hooks

Add to `.git/hooks/post-commit`:
```bash
#!/bin/bash
uv run --directory /path/to/lightrag-apps spec-graph index
```

## Technical Details

**Built with:**
- [LightRAG](https://github.com/HKUDS/LightRAG) - Knowledge graph framework
- GitHub Copilot models - LLM and embeddings
- NetworkX - Graph operations
- Nano-VectorDB - Vector storage

**Architecture:**
1. **Indexer** - Scans repository, builds knowledge graph
2. **Knowledge Graph** - Stores entities, relationships, and context

**Dependencies:**
- Managed via `pyproject.toml`
- 11 direct dependencies including LightRAG, OpenAI, LiteLLM
- ~114 total packages (including transitive dependencies)
- Persistent `.venv` for fast execution

**Package Structure:**
```
lightrag-apps/
├── pyproject.toml           # Project configuration
├── lightrag_apps/           # Package directory
│   ├── __init__.py
│   └── spec_graph.py          # Main script
└── .venv/                   # Created automatically by uv run
```

## References

See `references/` directory for additional documentation:
- Query modes and strategies
- Performance optimization
- Prompt customization
- Knowledge graph structure

## Related Skills

- **nl-cypher** - Query a Neo4j knowledge graph with natural language
- **repowiki** skill - Generate Markdown wiki pages from source structure
