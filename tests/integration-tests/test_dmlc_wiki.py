"""
Integration test: clone device-modeling-language, parse it with potpie, and generate a wiki.
"""

import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


def test_parse_repo_then_generate_wiki(potpie_cli_runner):
    with tempfile.TemporaryDirectory(prefix="potpie-int-test-") as _tmp:
        _run_workflow(potpie_cli_runner, Path(_tmp))


def _run_workflow(potpie_cli_runner, workflow_dir: Path):
    co_timestamp = datetime.now().strftime("%m%d%H%M")
    project_name = f"dml-{co_timestamp}"
    dml_dir = workflow_dir / project_name

    # Step 1: Clone the repository (skip if already present)
    if not dml_dir.exists():
        subprocess.run(
            ["git", "clone", "--branch", "main",
             "https://github.com/fenghaitao/device-modeling-language",
             str(dml_dir)],
            check=True,
        )
    assert dml_dir.is_dir(), "Cloned repository directory should exist"

    # Step 2: Parse the repository
    uuid_pattern = re.compile(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
    )

    parse_result = potpie_cli_runner("parse", "repo", str(dml_dir))
    assert parse_result.returncode == 0, (
        f"parse repo failed (exit {parse_result.returncode}):\n{parse_result.stderr}"
    )

    # Capture the new project ID for teardown
    list_result = potpie_cli_runner("projects", "list", "--json", check=False)
    import json

    project_id = None
    try:
        projects = json.loads(list_result.stdout)
        for project in projects:
            if project['repo_name'] == project_name:
                project_id = project['id']
                break
    except json.JSONDecodeError:
        pass
    except KeyError:
        pass

    assert project_id, "Project should be registered after parsing"

    try:
        # Step 3: Generate the wiki
        wiki_result = potpie_cli_runner("deepwiki-open-wiki", "-r", project_name,
                                        "-p", project_id, cwd=workflow_dir)
        assert wiki_result.returncode == 0, (
            f"wiki generation failed (exit {wiki_result.returncode}):\n{wiki_result.stderr}"
        )

        wiki_dir = dml_dir / ".repowiki"
        assert wiki_dir.is_dir(), "Wiki output directory should be created"
        md_files = list(wiki_dir.glob("**/*.md"))
        assert md_files, "At least one wiki Markdown file should be generated"

    finally:
        # Step 4: Cleanup
        if project_id:
            print(f"Cleaning up project {project_id}...")
            potpie_cli_runner("projects", "remove", project_id, "-f", check=False, cwd=workflow_dir)
