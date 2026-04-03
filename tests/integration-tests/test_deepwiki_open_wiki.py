"""
Integration test: clone intel-sandbox/deepwiki-open, parse it with potpie, and generate a wiki.
"""

import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


def _ts() -> str:
    """Return current timestamp string for log messages."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def test_parse_repo_then_generate_wiki(potpie_cli_runner):
    with tempfile.TemporaryDirectory(prefix="potpie-int-test-") as _tmp:
        _run_workflow(potpie_cli_runner, Path(_tmp))


def _run_workflow(potpie_cli_runner, workflow_dir: Path):
    co_timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    project_name = f"deepwiki-open-{co_timestamp}"
    repo_dir = workflow_dir / project_name

    # Step 1: Clone the repository (skip if already present)
    print(f"[{_ts()}] Step 1: Cloning intel-sandbox/deepwiki-open -> {repo_dir}")
    step_start = datetime.now()
    if not repo_dir.exists():
        subprocess.run(
            [
                "git",
                "clone",
                "--branch",
                "main",
                "--depth",
                "1",
                "--single-branch",
                "https://github.com/intel-sandbox/deepwiki-open",
                str(repo_dir),
            ],
            check=True,
            timeout=300,
        )
    assert repo_dir.is_dir(), "Cloned repository directory should exist"
    print(f"[{_ts()}] Step 1 done in {(datetime.now() - step_start).total_seconds():.1f}s")

    # Step 2: Parse the repository
    uuid_pattern = re.compile(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
    )

    print(f"[{_ts()}] Step 2: Parsing repository {repo_dir}")
    step_start = datetime.now()
    parse_result = potpie_cli_runner("parse", "repo", str(repo_dir), check=False)
    print(f"[{_ts()}] Step 2 done in {(datetime.now() - step_start).total_seconds():.1f}s"
          f" (exit {parse_result.returncode})")
    if parse_result.stdout:
        print(f"[{_ts()}] parse stdout:\n{parse_result.stdout}")
    if parse_result.stderr:
        print(f"[{_ts()}] parse stderr:\n{parse_result.stderr}")
    assert parse_result.returncode == 0, (
        f"parse repo failed (exit {parse_result.returncode}):\n{parse_result.stderr}"
    )

    # Capture the new project ID for teardown directly from parse output
    uuid_match = uuid_pattern.search(parse_result.stdout or "")
    assert uuid_match, "Unable to extract project ID from parse output"
    project_id = uuid_match.group(0)
    assert project_id, "Project should be registered after parsing"
    print(f"[{_ts()}] Project ID: {project_id}")

    try:
        # Step 3: Generate the wiki
        print(f"[{_ts()}] Step 3: Generating wiki for project {project_id}")
        step_start = datetime.now()
        wiki_result = potpie_cli_runner("deepwiki-open-wiki", "-r", project_name,
                                        "-p", project_id, cwd=workflow_dir)
        print(f"[{_ts()}] Step 3 done in {(datetime.now() - step_start).total_seconds():.1f}s"
              f" (exit {wiki_result.returncode})")
        if wiki_result.stdout:
            print(f"[{_ts()}] wiki stdout:\n{wiki_result.stdout}")
        if wiki_result.stderr:
            print(f"[{_ts()}] wiki stderr:\n{wiki_result.stderr}")
        assert wiki_result.returncode == 0, (
            f"wiki generation failed (exit {wiki_result.returncode}):\n{wiki_result.stderr}"
        )

        wiki_dir = repo_dir / ".repowiki"
        assert wiki_dir.is_dir(), "Wiki output directory should be created"
        md_files = list(wiki_dir.glob("**/*.md"))
        assert md_files, "At least one wiki Markdown file should be generated"
        print(f"[{_ts()}] Wiki generated: {len(md_files)} Markdown file(s) in {wiki_dir}")

        # Step 4: Download reference wiki docs from deepwiki.com
        # intel-sandbox/deepwiki-open is a fork of AsyncFuncAI/deepwiki-open which is indexed.
        # deepwiki-export creates a subdirectory <username>/<reponame> inside
        # the base dir, so the actual output lands at repo_dir/AsyncFuncAI/deepwiki-open/
        deepwiki_base_dir = repo_dir
        deepwiki_dir = deepwiki_base_dir / "AsyncFuncAI" / "deepwiki-open"
        print(f"[{_ts()}] Step 4: Running deepwiki-export for AsyncFuncAI/deepwiki-open")
        step_start = datetime.now()
        deepwiki_export_result = subprocess.run(
            [
                "deepwiki-export",
                "https://deepwiki.com/AsyncFuncAI/deepwiki-open",
                "--output-base-dir", str(deepwiki_base_dir),
            ],
            capture_output=True,
            text=True,
            cwd=str(repo_dir),
            timeout=120,
        )
        print(f"[{_ts()}] Step 4 done in {(datetime.now() - step_start).total_seconds():.1f}s"
              f" (exit {deepwiki_export_result.returncode})")
        if deepwiki_export_result.stdout:
            print(f"[{_ts()}] deepwiki-export stdout:\n{deepwiki_export_result.stdout}")
        if deepwiki_export_result.stderr:
            print(f"[{_ts()}] deepwiki-export stderr:\n{deepwiki_export_result.stderr}")
        assert deepwiki_export_result.returncode == 0, (
            f"deepwiki-export failed (exit {deepwiki_export_result.returncode}):\n"
            f"stdout:\n{deepwiki_export_result.stdout}\n\n"
            f"stderr:\n{deepwiki_export_result.stderr}"
        )
        assert deepwiki_dir.is_dir(), "deepwiki-export should create the output directory"
        ref_md_files = list(deepwiki_dir.glob("**/*.md"))
        assert ref_md_files, "deepwiki-export should produce at least one Markdown file"
        print(f"[{_ts()}] Reference docs: {len(ref_md_files)} file(s) in {deepwiki_dir}")

        # Step 5: Evaluate the wiki against the reference docs
        eval_output = repo_dir / "wiki_eval_score.md"
        print(f"[{_ts()}] Step 5: Evaluating wiki against reference docs")
        step_start = datetime.now()
        eval_result = potpie_cli_runner(
            "eval-wiki",
            "--repo", project_name,
            "--wiki-dir", str(wiki_dir),
            "--reference-docs-dir", str(deepwiki_dir),
            "--output", str(eval_output),
            "--verbose",
            cwd=str(workflow_dir),
        )
        print(f"[{_ts()}] Step 5 done in {(datetime.now() - step_start).total_seconds():.1f}s"
              f" (exit {eval_result.returncode})")
        if eval_result.stdout:
            print(f"[{_ts()}] eval-wiki stdout:\n{eval_result.stdout}")
        if eval_result.stderr:
            print(f"[{_ts()}] eval-wiki stderr:\n{eval_result.stderr}")
        assert eval_result.returncode == 0, (
            f"eval-wiki failed (exit {eval_result.returncode}):\n{eval_result.stderr}"
        )
        eval_json = eval_output.with_suffix(".json")
        assert eval_json.exists(), "eval-wiki should produce a JSON report"
        import json as _json
        report = _json.loads(eval_json.read_text())
        assert "overall_score" in report, "JSON report should contain 'overall_score'"
        print(f"[{_ts()}] Evaluation complete. overall_score={report.get('overall_score')}")

    finally:
        # Step 6: Cleanup
        if project_id:
            print(f"[{_ts()}] Step 6: Cleaning up project {project_id}")
            remove_result = potpie_cli_runner(
                "projects",
                "remove",
                project_id,
                "-f",
                check=False,
                cwd=str(workflow_dir),
            )
            print(f"[{_ts()}] Cleanup done (exit {remove_result.returncode})")
            assert remove_result.returncode == 0, (
                f"projects remove failed during cleanup (exit {remove_result.returncode}):\n"
                f"{remove_result.stderr}"
            )
