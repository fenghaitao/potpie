"""Graph-based extraction for repowiki — queries the potpie Neo4j knowledge graph."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Bootstrap: add the potpie repo root to sys.path so we can import PotpieRuntime
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).parent.resolve()
_REPO_ROOT = _SCRIPT_DIR.parents[3]  # potpie/.kiro/skills/repowiki/scripts/ → potpie/

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_ENV_FILE = _REPO_ROOT / ".env"
if _ENV_FILE.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_FILE, override=False)
    except ImportError:
        pass

from models import CodeModule, ClassDef, FunctionDef  # noqa: E402


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------
_EXT_TO_LANG: Dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".h": "cpp",
}


def _lang_from_path(file_path: str) -> str:
    return _EXT_TO_LANG.get(Path(file_path).suffix.lower(), "unknown")


def _rel_path(file_path: str, repo_root: str) -> str:
    try:
        return str(Path(file_path).relative_to(repo_root))
    except ValueError:
        return file_path


# ---------------------------------------------------------------------------
# Neo4j queries
# ---------------------------------------------------------------------------
_QUERY_FILES = """
MATCH (n:NODE {repoId: $project_id})
WHERE n.type = 'FILE'
RETURN n.file_path AS file_path,
       n.name      AS name,
       n.docstring AS docstring
ORDER BY n.file_path
"""

_QUERY_NODES = """
MATCH (n:NODE {repoId: $project_id})
WHERE n.type IN ['CLASS', 'FUNCTION', 'INTERFACE']
RETURN n.file_path  AS file_path,
       n.name       AS name,
       n.type       AS type,
       n.start_line AS start_line,
       n.end_line   AS end_line,
       n.text       AS text,
       n.docstring  AS docstring
ORDER BY n.file_path, n.start_line
"""


async def _run_queries(project_id: str) -> tuple[List[Dict], List[Dict]]:
    """Run both graph queries via PotpieRuntime and return (file_records, node_records)."""
    from potpie.runtime import PotpieRuntime

    runtime = PotpieRuntime.from_env()
    await runtime.initialize()
    try:
        file_records = await runtime.neo4j.execute_query(_QUERY_FILES, {"project_id": project_id})
        node_records = await runtime.neo4j.execute_query(_QUERY_NODES, {"project_id": project_id})
    finally:
        await runtime.close()

    return file_records, node_records


# ---------------------------------------------------------------------------
# Build extraction dict from graph records
# ---------------------------------------------------------------------------
def _build_extraction(
    file_records: List[Dict],
    node_records: List[Dict],
    repo_root: str,
) -> Dict[str, Any]:
    """Convert raw Neo4j records into the extraction dict shape used by generate_wiki."""
    nodes_by_file: Dict[str, List[Dict]] = {}
    for rec in node_records:
        fp = rec.get("file_path") or ""
        nodes_by_file.setdefault(fp, []).append(rec)

    modules: List[CodeModule] = []
    skipped: List[str] = []

    for frec in file_records:
        fp = frec.get("file_path") or ""
        if not fp:
            continue

        rel = _rel_path(fp, repo_root)
        lang = _lang_from_path(fp)
        if lang == "unknown":
            skipped.append(rel)
            continue

        classes: List[ClassDef] = []
        functions: List[FunctionDef] = []

        for node in nodes_by_file.get(fp, []):
            ntype = (node.get("type") or "").upper()
            name = node.get("name") or ""
            doc = node.get("docstring") or ""
            text = node.get("text") or ""

            if ntype in ("CLASS", "INTERFACE"):
                classes.append(ClassDef(name=name, description=doc))
            elif ntype == "FUNCTION":
                functions.append(FunctionDef(
                    name=name,
                    description=doc,
                    is_async="async def" in text or "async function" in text,
                    is_static="@staticmethod" in text or "static " in text,
                ))

        modules.append(CodeModule(
            path=rel,
            language=lang,
            description=frec.get("docstring") or frec.get("name") or "",
            classes=classes,
            functions=functions,
        ))

    # Serialise to plain dicts so callers don't need to import models
    return {
        "target": repo_root,
        "modules": [_module_to_dict(m) for m in modules],
        "skipped": skipped,
    }


def _module_to_dict(m: CodeModule) -> Dict[str, Any]:
    return {
        "path": m.path,
        "language": m.language,
        "description": m.description,
        "imports": m.imports,
        "classes": [
            {"name": c.name, "description": c.description, "bases": c.bases, "methods": []}
            for c in m.classes
        ],
        "functions": [
            {
                "name": f.name, "description": f.description,
                "params": [], "returns": f.returns,
                "is_async": f.is_async, "is_static": f.is_static,
            }
            for f in m.functions
        ],
        "types": [],
    }


# ---------------------------------------------------------------------------
# Public async interface (used by generate_wiki.py)
# ---------------------------------------------------------------------------
async def graph_extract_async(project_id: str, repo_root: str) -> Dict[str, Any]:
    """
    Query the potpie knowledge graph and return the extraction dict.

    Args:
        project_id: Potpie project UUID.
        repo_root:  Absolute path to the repository root.

    Returns:
        Dict with keys: target, modules (list of dicts), skipped (list of paths).
    """
    file_records, node_records = await _run_queries(project_id)

    if not file_records:
        print(
            f"[FAIL] No FILE nodes found in graph for project '{project_id}'. "
            "Ensure the project has been parsed with `potpie-cli parse repo`.",
            file=sys.stderr,
        )
        sys.exit(1)

    return _build_extraction(file_records, node_records, repo_root)
