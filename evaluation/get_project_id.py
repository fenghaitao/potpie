#!/usr/bin/env python3
"""
Resolve a potpie project ID from repo name and branch.

Usage:
    source .env && .venv/bin/python evaluation/get_project_id.py \
        --repo device-modeling-language \
        --branch main
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_ENV_FILE = _REPO_ROOT / ".env"
if _ENV_FILE.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_FILE, override=False)
    except ImportError:
        pass


async def resolve(repo_name: str, branch: str | None) -> str:
    from potpie.runtime import PotpieRuntime

    runtime = PotpieRuntime.from_env()
    await runtime.initialize()
    try:
        user_id = os.environ.get("POTPIE_USER_ID", "defaultuser")
        projects = await runtime.projects.list(user_id=user_id)
        matches = [
            p for p in projects
            if p.repo_name == repo_name
            and (branch is None or p.branch_name == branch)
        ]
        if not matches:
            criteria = f"repo='{repo_name}'" + (f", branch='{branch}'" if branch else "")
            print(f"[ERROR] No project found with {criteria}", file=sys.stderr)
            if branch:
                all_branches = [p.branch_name for p in projects if p.repo_name == repo_name]
                if all_branches:
                    print(f"[INFO]  Available branches for '{repo_name}': {all_branches}", file=sys.stderr)
            sys.exit(1)
        return matches[0].id
    finally:
        await runtime.close()


def main():
    parser = argparse.ArgumentParser(description="Resolve potpie project ID by repo name and branch")
    parser.add_argument("--repo", required=True, help="Repository name")
    parser.add_argument("--branch", default=None, help="Branch name (omit to match any branch)")
    args = parser.parse_args()

    project_id = asyncio.run(resolve(args.repo, args.branch))
    print(project_id)


if __name__ == "__main__":
    main()
