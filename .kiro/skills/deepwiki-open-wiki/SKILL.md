---
name: deepwiki-open-wiki
description: Generates comprehensive wiki documentation for a repository using potpie's DeepWikiOpenAgent, following the deepwiki-open 3-phase methodology (analyze structure, plan pages, generate content). Writes Markdown pages to .repowiki/en/content/.
---

# deepwiki-open-wiki

Generates a comprehensive wiki for a repository using potpie's `DeepWikiOpenAgent`, following the deepwiki-open methodology:

1. **Analyze** — queries the knowledge graph to understand repository structure
2. **Plan** — creates a wiki page structure (8-12 comprehensive or 4-6 concise pages)
3. **Generate** — writes Markdown content for each wiki page to `.repowiki/en/content/`

## Quick Start

```bash
.venv/bin/python .github/skills/deepwiki-open-wiki/scripts/generate_deepwiki.py \
  --repo_path /abs/path/to/repo \
  --project_id <uuid>
```

When invoked via `run_skill_script`, use:

```python
run_skill_script(
    skill="deepwiki-open-wiki",
    script="scripts/generate_deepwiki.py",
    args={
        "repo_path": "/abs/path/to/repo",
        "project_id": "<uuid>",
        # optional:
        # "concise": True,       # 4-6 pages instead of 8-12
        # "readme": "README.md", # path relative to repo root
    }
)
```

## Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--repo_path` | yes | — | Absolute path to the repository root |
| `--project_id` | no | — | Potpie project UUID (auto-parses repo when omitted) |
| `--concise` | no | false | Generate concise wiki (4-6 pages instead of 8-12) |
| `--readme` | no | — | Path to README.md relative to the repo root |
| `--user_id` | no | `defaultuser` | Potpie user ID (or `$POTPIE_USER_ID` env var) |

## Output

All wiki pages are written to `<repo_path>/.repowiki/en/content/` organised into topic sub-directories. A `wiki_structure.xml` file is also written to `<repo_path>/.repowiki/`.

## Prerequisites

- potpie `.venv` with all dependencies installed (`uv sync`)
- `.env` file with `CHAT_MODEL` and database settings
- The repository must be registered and parsed in potpie (or pass no `--project_id` to auto-parse)
- Backend services (Postgres, Redis, Neo4j) must be running — see **Backend Services** below

## Backend Services

Follow these steps (all commands run from the potpie repository root) before invoking `run_skill_script`.

### 1. Ensure `.env` exists

```bash
# Copy the template if .env is missing
[ -f .env ] || cp .env.template .env
```

Then open `.env` and fill in the required values — at minimum `CHAT_MODEL`, `OPENAI_API_KEY` (or equivalent), `POSTGRES_SERVER`, `NEO4J_URI`, `NEO4J_PASSWORD`, `REDISHOST`, and `REDISPORT`. See [README.md](../../../../../README.md) for the full list.

### 2. Set up the Python virtual environment

Create and activate the `.venv` if it does not already exist, then install all dependencies:

```bash
# Create the virtual environment only if it is missing
[ -d .venv ] || uv venv

# Activate the virtual environment (required before any subsequent commands)
source .venv/bin/activate

# Sync / install all dependencies
uv sync
```

> **Note:** Always `source .venv/bin/activate` before running any `alembic`, `gunicorn`, `celery`, or skill script commands in the same shell session.

### 3. Pre-flight: clear any stale Neo4j store lock

Neo4j holds a `store_lock` file for as long as it is running. If Neo4j was killed ungracefully the file can persist, causing the **next** startup to fail immediately with:

```
Lock file has been locked by another process: /data/databases/store_lock.
```

Because `singularity/start.sh` starts Neo4j internally, the lock must be checked and cleared **before** calling `start.sh`. Do this every time you are about to start (or restart) the stack:

```bash
NEO4J_DATA="singularity/potpie-data/neo4j/data/databases"

# Determine whether the Neo4j PROCESS is actually running (not just the container).
# The Singularity instance (neo4j1) can be listed while Neo4j itself is stopped.
NEO4J_RUNNING=false
if singularity instance list 2>&1 | grep -q neo4j1; then
    # Container exists — check the process inside it
    if singularity exec instance://neo4j1 neo4j status 2>&1 | grep -q "Neo4j is running"; then
        NEO4J_RUNNING=true
    fi
fi

if [ "${NEO4J_RUNNING}" = "false" ] && [ -f "${NEO4J_DATA}/store_lock" ]; then
    echo "Stale store_lock found with Neo4j stopped — removing..."
    rm "${NEO4J_DATA}/store_lock"
    echo "Lock removed."
elif [ "${NEO4J_RUNNING}" = "true" ] && [ -f "${NEO4J_DATA}/store_lock" ]; then
    echo "store_lock present and Neo4j is running — this is normal, do NOT remove."
else
    echo "No stale lock found."
fi
```

> **Warning:** Only remove the lock when the Neo4j **process** is confirmed stopped (not just when the container is absent). Removing the lock while Neo4j is active will corrupt the database.

### 4. (Re)start backend services

Stop any stale instances first, then start fresh:

```bash
bash singularity/stop.sh   # safe no-op if nothing is running
bash singularity/start.sh
```

`singularity/start.sh` will:
1. Start Singularity containers (Postgres, Redis, Neo4j)
2. Apply database migrations (`alembic upgrade heads`)
3. Start the FastAPI application (`gunicorn`) and Celery worker

Wait for the script to finish — it polls until Neo4j bolt is reachable before returning.

### 5. Verify the API is healthy

```bash
curl -X GET 'http://localhost:8001/health'
```

Only proceed to `run_skill_script` once this returns `200 OK`.

## How It Works

The script suppresses all verbose/streaming output during the async run and prints only a concise `[DONE] N page(s) written:` summary to stdout. This keeps the `run_skill_script` tool result small so the outer LLM agent does not exceed its context limit. Progress lines are written to stderr and are visible when using `--verbose` with the CLI.
