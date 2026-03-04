# cli

The command-line entry point for repowiki. Provides two subcommands: `extract` for producing structured JSON for agent consumption, and `generate` for static Markdown output used in testing and demonstration.

**Source:** `repowiki/cli.py`

## Dependencies

- `argparse`, `json`, `dataclasses` — CLI parsing and JSON serialisation

## Functions

### main

Parses command-line arguments and dispatches to `extract` or `generate`. Registered as the `repowiki` entry point in `pyproject.toml`.

**`repowiki extract <target>`** — Runs discovery and analysis, then serialises all `CodeModule` objects to JSON. This is the intended input for the agent's wiki-generation phase. Output goes to stdout by default, or to a file with `--output`.

**`repowiki generate <target>`** — Runs the full static pipeline (discovery → analysis → Markdown rendering → index) and writes `.md` files directly. No LLM involved. Intended for testing the pipeline end-to-end.
