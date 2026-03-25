#!/usr/bin/env python3
"""
DeepWiki Open Wiki Skill Script

Generates wiki documentation for a repository using potpie's DeepWikiOpenAgent,
following the deepwiki-open 3-phase methodology:
  1. Analyze project structure via the knowledge graph
  2. Plan wiki pages (8-12 comprehensive, or 4-6 concise)
  3. Generate and write each page to .repowiki/en/content/

Must be invoked with the potpie venv Python:
  .venv/bin/python .github/skills/deepwiki-open-wiki/scripts/generate_deepwiki.py \
    --repo_path /absolute/path/to/repo \
    [--project_id <uuid>] \
    [--concise] \
    [--readme README.md] \
    [--user_id defaultuser]

Copyright 2026 Intel Corporation
Licensed under the Apache License, Version 2.0
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: repo root on sys.path, .env loaded
# Path layout:
#   <repo>/.github/skills/deepwiki-open-wiki/scripts/generate_deepwiki.py
#   _SCRIPT_DIR               = <repo>/.github/skills/deepwiki-open-wiki/scripts
#   _SCRIPT_DIR.parents[0]    = <repo>/.github/skills/deepwiki-open-wiki
#   _SCRIPT_DIR.parents[1]    = <repo>/.github/skills
#   _SCRIPT_DIR.parents[2]    = <repo>/.github
#   _SCRIPT_DIR.parents[3]    = <repo>   ← repo root
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).parent.resolve()
_REPO_ROOT = _SCRIPT_DIR.parents[3]

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_ENV_FILE = _REPO_ROOT / ".env"
if _ENV_FILE.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_FILE, override=False)
    except ImportError:
        pass


async def run_generation_async(
    repo_path: str,
    project_id: str | None,
    concise: bool,
    readme_path: str | None,
    user_id: str,
) -> list[str]:
    """Run the DeepWikiOpenAgent to generate wiki pages.

    All rich/streaming console output is suppressed so that stdout (captured by
    run_skill_script as the tool result) stays small.  Progress lines are emitted
    to stderr where the StreamingLocalSkillScriptExecutor callback can stream
    them to the parent terminal.

    Returns a list of written wiki page paths.
    """
    from potpie import PotpieRuntime
    from potpie.agents.context import ChatContext, ToolCallEventType

    repo_path = str(Path(repo_path).expanduser().resolve())
    repo_name = Path(repo_path).name

    # Change cwd to the repo so the DeepWikiOpenAgent writes .repowiki/ there,
    # not relative to the script's own directory.
    os.chdir(repo_path)

    # Load README if requested
    readme_content: str | None = None
    if readme_path:
        full_readme = Path(repo_path) / readme_path
        try:
            with open(full_readme, "r", encoding="utf-8") as f:
                readme_content = f.read()
            print(f"[INFO] README loaded from {readme_path}", file=sys.stderr)
        except Exception as exc:
            print(f"[WARN] Failed to read README at {readme_path}: {exc}", file=sys.stderr)

    runtime = PotpieRuntime.from_env()
    await runtime.initialize()

    try:
        # ------------------------------------------------------------------
        # Auto-parse the repository when no project_id is supplied
        # ------------------------------------------------------------------
        if not project_id:
            print("[INFO] No project_id provided — auto-parsing repository...", file=sys.stderr)
            try:
                from git import Repo as GitRepo
                git_repo = GitRepo(repo_path)
                branch = git_repo.active_branch.name
                commit_id = git_repo.head.commit.hexsha
            except Exception:
                branch = "main"
                commit_id = None

            project_id = await runtime.projects.register(
                repo_name=repo_name,
                branch_name=branch,
                user_id=user_id,
                repo_path=repo_path,
                commit_id=commit_id,
            )

            result = await runtime.parsing.parse_project(
                project_id=project_id,
                user_id=user_id,
                user_email=f"{user_id}@cli.local",
                cleanup_graph=True,
                commit_id=commit_id,
            )

            if not result.success:
                raise RuntimeError(f"Parsing failed: {result.error_message}")

            print(f"[INFO] Project parsed — ID: {project_id}", file=sys.stderr)

        # ------------------------------------------------------------------
        # Resolve agent
        # ------------------------------------------------------------------
        try:
            agent = runtime.agents.deepwiki_open_agent
        except AttributeError:
            raise RuntimeError(
                "deepwiki_open_agent not found. "
                "Make sure it is registered in agents_service.py."
            )

        project_info = await runtime.projects.get(project_id)

        mode = "concise" if concise else "comprehensive"
        query = (
            f"Generate {mode} wiki documentation for the entire repository "
            "following deepwiki-open methodology"
        )

        print(
            f"[INFO] Generating {mode} wiki for '{repo_name}' (project {project_id})",
            file=sys.stderr,
        )

        ctx = ChatContext(
            project_id=project_id,
            project_name=project_info.repo_name,
            curr_agent_id="deepwiki_open_agent",
            query=(
                f"[Codebase: {project_info.repo_name}, project_id: {project_id}] "
                f"{query}"
            ),
            history=[],
            user_id=user_id,
            conversation_id=f"deepwiki_{project_id}",
        )

        if readme_content:
            ctx.additional_context = f"\n\nREADME Content:\n{readme_content}\n"

        pages_written: list[str] = []

        async for chunk in agent.stream(ctx):
            # Track tool invocations for progress, but do NOT print wiki content.
            if chunk.tool_calls:
                for tc in chunk.tool_calls:
                    if tc.event_type == ToolCallEventType.CALL:
                        print(f"[INFO] Tool: {tc.tool_name}", file=sys.stderr)
            # Scan streamed text for page-written confirmation lines only.
            if chunk.response:
                for line in chunk.response.splitlines():
                    if "✅ Wiki page written to:" in line:
                        page_path = line.split("✅ Wiki page written to:")[-1].strip()
                        pages_written.append(page_path)
                        print(
                            f"[INFO] ✅ Wiki page written to: {page_path}",
                            file=sys.stderr,
                        )

        return pages_written

    finally:
        await runtime.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate comprehensive wiki documentation using the "
            "deepwiki-open methodology via potpie's DeepWikiOpenAgent."
        )
    )
    parser.add_argument("--repo_path", required=True, help="Path to the repository")
    parser.add_argument(
        "--project_id",
        default=None,
        help="Potpie project UUID (auto-parses the repo when omitted)",
    )
    parser.add_argument(
        "--concise",
        action="store_true",
        help="Generate a concise wiki (4-6 pages instead of 8-12)",
    )
    parser.add_argument(
        "--readme",
        default=None,
        help="Path to README.md relative to the repository root",
    )
    parser.add_argument(
        "--user_id",
        default=os.environ.get("POTPIE_USER_ID", "defaultuser"),
        help="Potpie user ID (default: 'defaultuser' or $POTPIE_USER_ID)",
    )
    args = parser.parse_args()

    # Suppress sys.stdout during the async run so that loguru's
    # production_log_sink (which writes JSONL to sys.stdout) does not flood the
    # tool result captured by run_skill_script.  Progress lines go to stderr and
    # are streamed to the parent terminal via StreamingLocalSkillScriptExecutor.
    real_stdout = sys.stdout
    devnull = open(os.devnull, "w")
    sys.stdout = devnull
    error: BaseException | None = None
    pages: list[str] = []
    try:
        pages = asyncio.run(
            run_generation_async(
                repo_path=args.repo_path,
                project_id=args.project_id,
                concise=args.concise,
                readme_path=args.readme,
                user_id=args.user_id,
            )
        )
    except Exception as exc:
        error = exc
    finally:
        sys.stdout = real_stdout
        devnull.close()

    # Print concise summary to stdout — this becomes the run_skill_script tool result.
    if error is not None:
        import traceback
        print(f"[ERROR] Wiki generation failed: {error}")
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
    elif pages:
        print(f"[DONE] {len(pages)} wiki page(s) written:")
        for p in pages:
            print(f"  {p}")
    else:
        print("[DONE] Wiki generation complete. Check .repowiki/en/content/ for output.")


if __name__ == "__main__":
    main()
