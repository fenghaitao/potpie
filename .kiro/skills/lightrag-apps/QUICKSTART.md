# spec-graph - Quick Start Guide

Index any code repository into a LightRAG knowledge graph and query it with natural language.

## Prerequisites

- `uv` package manager installed
- GitHub Copilot subscription (or OpenAI API key)

## Setup (One-Time)

```bash
# Validate setup
uv run --directory {baseDir} spec-graph test
```

## Index and Query (All-in-One)

```bash
# Index your repository
uv run --directory {baseDir} spec-graph index --repo /path/to/your/project

# Query the knowledge graph
uv run --directory {baseDir} spec-graph query "Tell me about X"
```

That's it! The knowledge graph is stored in `./spec_graph_storage/`

## Index Repository

```bash
# Index current directory
uv run --directory {baseDir} spec-graph index

# Index specific repository
uv run --directory {baseDir} spec-graph index --repo /path/to/project

# Index into a custom graph directory
uv run --directory {baseDir} spec-graph index --repo /path/to/project --working-dir ./my-graph
```

## Query the Knowledge Graph

```bash
# Query using default graph directory (./spec_graph_storage)
uv run --directory {baseDir} spec-graph query "What are the main components?"

# Query a specific graph directory
uv run --directory {baseDir} spec-graph query -s ./my-graph "How does X work?"

# Use a specific query mode (default: hybrid)
uv run --directory {baseDir} spec-graph query --mode global "What is the architecture?"
uv run --directory {baseDir} spec-graph query --mode local "What does class Foo do?"
```

## Query Modes

| Mode | Description |
|------|-------------|
| `hybrid` *(default)* | Combines keyword and vector search |
| `global` | Searches across the entire knowledge graph |
| `local` | Focuses on locally connected nodes |

## Configuration

### Default (GitHub Copilot)

Works out of the box with GitHub Copilot — no configuration needed!

### Custom Model

```bash
# Set environment variable
export LLM_MODEL="gpt-4o-mini"
uv run --directory {baseDir} spec-graph index --repo /path/to/project
```

## Examples

### Index and Query Your Project
```bash
uv run --directory ~/.kiro/skills/lightrag-apps spec-graph index --repo ~/my-project
uv run --directory ~/.kiro/skills/lightrag-apps spec-graph query "What does this project do?"
```

### Multiple Projects
```bash
uv run --directory {baseDir} spec-graph index --repo projectA --working-dir ./graph-A
uv run --directory {baseDir} spec-graph index --repo projectB --working-dir ./graph-B
uv run --directory {baseDir} spec-graph query -s ./graph-A "What does projectA do?"
uv run --directory {baseDir} spec-graph query -s ./graph-B "What does projectB do?"
```

### Re-index After Changes
```bash
uv run --directory {baseDir} spec-graph index --repo /path/to/project
uv run --directory {baseDir} spec-graph query "What changed recently?"
```

## Troubleshooting

### Check Setup
```bash
uv run --directory {baseDir} spec-graph test
```

### Repository Not Found
```bash
# Specify path explicitly
uv run --directory {baseDir} spec-graph index --repo /full/path/to/project
```

## Next Steps

- Read [SKILL.md](SKILL.md) for complete documentation
- Try different query modes (`hybrid`, `global`, `local`)
- Set up a git hook for automatic re-indexing on commit

## Output

After indexing:
```
spec_graph_storage/         # Knowledge graph storage
  ├── kv_store_*.json       # Entity / relation / chunk stores
  ├── vdb_*.json            # Vector DB files
  └── graph_chunk_entity_relation.graphml
```
