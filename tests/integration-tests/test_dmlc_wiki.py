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

        # Step 4: Download reference wiki docs from deepwiki.com
        # deepwiki-export creates a subdirectory <username>/<reponame> inside
        # the base dir, so the actual output lands at dml_dir/intel/device-modeling-language/
        deepwiki_base_dir = dml_dir
        deepwiki_dir = deepwiki_base_dir / "intel" / "device-modeling-language"
        deepwiki_export_result = subprocess.run(
            [
                "deepwiki-export",
                "https://deepwiki.com/intel/device-modeling-language",
                "--output-base-dir", str(deepwiki_base_dir),
            ],
            capture_output=True,
            text=True,
            cwd=str(dml_dir),
        )
        assert deepwiki_export_result.returncode == 0, (
            f"deepwiki-export failed (exit {deepwiki_export_result.returncode}):\n"
            f"{deepwiki_export_result.stderr}"
        )
        assert deepwiki_dir.is_dir(), "deepwiki-export should create the output directory"
        ref_md_files = list(deepwiki_dir.glob("**/*.md"))
        assert ref_md_files, "deepwiki-export should produce at least one Markdown file"

        # Step 5: Evaluate the wiki against the reference docs
        eval_output = dml_dir / "wiki_eval_score.md"
        eval_result = potpie_cli_runner(
            "eval-wiki",
            "--repo", project_name,
            "--wiki-dir", str(wiki_dir),
            "--reference-docs-dir", str(deepwiki_dir),
            "--output", str(eval_output),
            "--verbose",
            cwd=str(workflow_dir),
        )
        assert eval_result.returncode == 0, (
            f"eval-wiki failed (exit {eval_result.returncode}):\n{eval_result.stderr}"
        )
        eval_json = eval_output.with_suffix(".json")
        assert eval_json.exists(), "eval-wiki should produce a JSON report"
        import json as _json
        report = _json.loads(eval_json.read_text())
        assert "overall_score" in report, "JSON report should contain 'overall_score'"

    finally:
        # Step 6: Cleanup
        if project_id:
            print(f"Cleaning up project {project_id}...")
            potpie_cli_runner("projects", "remove", project_id, "-f", check=False, cwd=workflow_dir)
