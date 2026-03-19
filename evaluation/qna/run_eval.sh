#!/usr/bin/env bash
# Run the potpie QnA evaluator against the device-modeling-language project.
#
# Usage:
#   ./evaluation/qna/run_eval.sh [--repo <name>] [--cases <file>] [--output <file>]
#
# The project ID is resolved automatically from the project list by repo name.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

REPO_NAME="${REPO_NAME:-device-modeling-language}"
CASES="${CASES:-$SCRIPT_DIR/qna_eval_dml_cases.yaml}"
OUTPUT="${OUTPUT:-$SCRIPT_DIR/qna_eval_dml_score.md}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)   REPO_NAME="$2"; shift 2 ;;
        --cases)  CASES="$2";     shift 2 ;;
        --output) OUTPUT="$2";    shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

cd "$REPO_ROOT"
source .env

echo "[INFO] Looking up project ID for repo: $REPO_NAME"

PROJECT_ID="$(.venv/bin/python "$REPO_ROOT/evaluation/get_project_id.py" --repo "$REPO_NAME")"

if [[ -z "$PROJECT_ID" ]]; then
    echo "[ERROR] Could not resolve project ID for repo '$REPO_NAME'" >&2
    exit 1
fi

echo "[INFO] Resolved project ID: $PROJECT_ID"

exec .venv/bin/python .kiro/skills/potpie-evaluator/scripts/evaluate_qna.py \
    --cases      "$CASES" \
    --project-id "$PROJECT_ID" \
    --output     "$OUTPUT"
