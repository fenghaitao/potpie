# CI / GitHub Actions

## Overview

The repository uses a single GitHub Actions workflow to run the unit-test suite
on pushes to `main` and on pull requests from branches within this repository
(pull requests from forks are skipped). No external services (Postgres, Redis,
Neo4j, Copilot CLI) are required — the unit tests are fully mocked.

---

## Workflow file

```
.github/workflows/unit-tests.yml
```

---

## Trigger rules

| Event | Branches | Result |
|---|---|---|
| `push` | `main` | Run unit tests |
| `pull_request` | targeting `main` | Run unit tests (only for PRs from branches in this repo; PRs from forks are skipped) |

**Note:** Because the workflow runs on a self-hosted runner and uses repository secrets,
pull requests opened from forks do **not** run this CI workflow. Contributors working
from forks should run the unit tests locally using the commands below.

---

## What the workflow does

1. **Checkout** – checks out the repository (latest commit via a shallow clone using `actions/checkout@v4`).
2. **Set up Python** – installs 3.13 in a matrix.
3. **Cache dependencies** – caches the `uv`-managed virtual environment keyed on `pyproject.toml` + `uv.lock`.
   A cache hit reuses the existing virtualenv contents, significantly reducing CI runtimes and dependency installation time.
4. **Install dependencies** – uses `uv sync --group dev` to create/update the virtualenv
    with the locked application dependencies and dev tools (pytest, pytest-asyncio, etc.).
5. **Run unit tests** – executes `uv run pytest unit-tests/ -m "not integration"`.
   Tests tagged `@pytest.mark.integration` are **skipped** in CI because they
   require live credentials (Copilot CLI, database, etc.).
6. **Test reports** – the test suite can emit a JUnit XML report, but CI
   does not currently upload this report as a build artifact.

---

## Test folder layout

```
unit-tests/
  conftest.py              # Minimal conftest — no DB/Redis/Neo4j imports
  pytest.ini               # asyncio_mode = auto, testpaths = .
  test_copilot_model.py    # Fully mocked CopilotModel tests
  test_eval_ask_pipeline.py# Mocked ask→YAML→eval pipeline tests
```

---

## Running locally

```bash
 # Identical to what CI does (uses uv + dependency groups)
uv python install 3.13
uv venv --python 3.13 .venv
# Sync base deps + dev tools from [dependency-groups]
uv sync --group dev
# Sanity check
uv run python -V
uv run pytest --version
uv run pytest unit-tests/ -m "not integration" -v

# If you prefer plain venv + pip (alternative, not used in CI):
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e . --no-deps
# Install test dependencies used by the unit test suite
.venv/bin/pip install pytest pytest-asyncio pydantic_evals
.venv/bin/pytest unit-tests/ -m "not integration" -v
```

---

## Required status checks (branch protection)

To enforce CI on `main`, configure branch protection in GitHub:

1. Go to **Settings → Branches → Add branch protection rule** for `main`.
2. Enable **Require status checks to pass before merging**.
3. Search for and add:
   - `Unit Tests / Run unit tests (Python 3.13)`
4. Enable **Require branches to be up to date before merging**.
5. Optionally enable **Do not allow bypassing the above settings**.

PRs that fail the CI job will be blocked from merging automatically.

Note: The unit-test workflow only runs on branches within this repository
(pull requests from forks are skipped). As a result, fork PRs cannot directly
satisfy the required `Unit Tests / Run unit tests (Python 3.13)` check and
cannot be merged as-is. To merge contributions from a fork, a maintainer must
push the contributor's branch to this repository (for example, `git fetch`
the fork and `git push` it as a branch here) and open a new pull request
from that internal branch so that CI can run and the required check can pass.

---

## Adding new tests

- Place test files in `unit-tests/` prefixed with `test_`.
- Mark tests that need live services with `@pytest.mark.integration` — they
  will be skipped in CI but can be run locally when infrastructure is available.
- Do **not** import `app.main` or any module that triggers database/Redis
  connections at import time; the `unit-tests/conftest.py` deliberately avoids
  this to keep the suite fast and infra-free.
