# spec-graph - LightRAG Knowledge Graph

Index any code repository into a LightRAG knowledge graph and query it with natural language.

## What is spec-graph?

`spec-graph` uses LightRAG to build a knowledge graph from your code repository. Once indexed, you can ask natural language questions against the graph using hybrid, global, or local query modes.

## Quick Links

- [SKILL.md](SKILL.md) - Complete documentation
- [LightRAG](https://github.com/HKUDS/LightRAG) - Knowledge graph framework

## Basic Usage

```bash
# Index your repository
uv run --directory .kiro/skills/lightrag-apps spec-graph index --repo /path/to/project

# Query the indexed graph
uv run --directory .kiro/skills/lightrag-apps spec-graph query "Tell me about X"
```

## Features

✅ Works with any repository
✅ Auto-detects repository name
✅ Uses GitHub Copilot by default (FREE)
✅ Smart query modes (global, local, hybrid)
✅ Persistent .venv for fast execution
✅ Optimized for GitHub Copilot Business (48/96/48 concurrent)

## Commands

| Command | Description |
|---------|-------------|
| `spec-graph test` | Validate setup and dependencies |
| `spec-graph index` | Index a repository into the knowledge graph |
| `spec-graph query` | Query the indexed knowledge graph |

## Query Modes

- **hybrid** *(default)* — combines keyword and vector search
- **global** — search across the entire knowledge graph
- **local** — focus on locally connected nodes

## Configuration

### Default (GitHub Copilot)
Works out of the box — no API key needed!

### Environment Variables
```bash
export REPO_PATH="/path/to/project"
export WORKING_DIR="./spec_graph_storage"
export LLM_MODEL="github_copilot/gpt-4o"
```

## Performance

- **Indexing**: First-time indexing may take longer for large repos
- **Parallelism**: Optimized for GitHub Copilot Business (48/96/48 concurrent)

## Examples

### Index and Query Your Project
```bash
uv run --directory ~/.kiro/skills/lightrag-apps spec-graph index --repo ~/my-project
uv run --directory ~/.kiro/skills/lightrag-apps spec-graph query "What does this project do?"
```

### Multiple Projects
```bash
uv run --directory ~/.kiro/skills/lightrag-apps spec-graph index --repo projectA --working-dir ./graph-A
uv run --directory ~/.kiro/skills/lightrag-apps spec-graph index --repo projectB --working-dir ./graph-B
uv run --directory ~/.kiro/skills/lightrag-apps spec-graph query -s ./graph-A "What does projectA do?"
```

### Git Hook (auto re-index on commit)
```bash
# .git/hooks/post-commit
uv run --directory /path/to/lightrag-apps spec-graph index
```

## Support

For issues or questions:
1. Check [SKILL.md](SKILL.md) troubleshooting section
2. Run `spec-graph test` to diagnose setup problems
3. Review [LightRAG documentation](https://github.com/HKUDS/LightRAG)

## Technical Details

Built with:
- LightRAG - Knowledge graph framework
- GitHub Copilot models - LLM and embeddings
- NetworkX - Graph operations
- Nano-VectorDB - Vector storage

Architecture:
1. **Indexer** (`spec-graph index`) — scans repository, builds knowledge graph
2. **Knowledge Graph** — stores entities, relationships, and context
3. **Query** (`spec-graph query`) — retrieves answers using hybrid/global/local modes

Package entry point: `lightrag_apps.spec_graph:main`
