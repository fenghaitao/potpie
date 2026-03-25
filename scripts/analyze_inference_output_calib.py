#!/usr/bin/env python3
"""
Parse Potpie inference calibration logs and summarize output-token estimate accuracy.

Expects lines containing [INFERENCE][OUTPUT_CALIB] from INFERENCE_OUTPUT_CALIBRATION_LOG=1.
Works with development log format (key: value, after |) and JSONL production logs.

Usage:
  uv run python scripts/analyze_inference_output_calib.py /path/to/parse.log
  uv run python scripts/analyze_inference_output_calib.py /path/to/parse.log --current-safety 1.0
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Dict, List, Optional

CALIB_MARKER = "[INFERENCE][OUTPUT_CALIB]"

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)


def _to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        if isinstance(x, float) and (x != x):  # NaN
            return None
        return float(x)
    s = str(x).strip().lower()
    if s in ("none", "null", "nan", ""):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(x: Any) -> Optional[int]:
    if x is None:
        return None
    if isinstance(x, int):
        return x
    try:
        return int(str(x).strip())
    except ValueError:
        return None


def parse_jsonl_calib(line: str) -> Optional[Dict[str, Any]]:
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        d = json.loads(line)
    except json.JSONDecodeError:
        return None
    msg = d.get("message", "")
    if CALIB_MARKER not in msg:
        return None
    return {
        "requested": _to_int(d.get("batch_requested_nodes")),
        "returned": _to_int(d.get("batch_returned_docstrings")),
        "snippet_sum": _to_int(d.get("snippet_tokens_sum")),
        "est_sum": _to_int(d.get("estimated_output_tokens_sum")),
        "actual_json": _to_int(d.get("actual_json_output_tokens")),
        "ratio_full": _to_float(d.get("ratio_actual_json_to_est_sum")),
        "ratio_ret": _to_float(d.get("ratio_actual_to_returned_est_sum")),
        "avg_doc_per_snip": _to_float(d.get("avg_docstring_tokens_per_snippet_token")),
    }


def _grab_from_block(block: str, name: str, int_val: bool) -> Any:
    """Match `name: value,` or `name: value` at end (loguru extra fields, multiline)."""
    if int_val:
        m = re.search(rf"\b{name}:\s*(\d+)\s*(?:,|\n|$)", block)
        return int(m.group(1)) if m else None
    m = re.search(
        rf"\b{name}:\s*(None|nan|[\d.+-eE]+)\s*(?:,|\n|$)",
        block,
        re.IGNORECASE | re.MULTILINE,
    )
    return _to_float(m.group(1)) if m else None


def parse_dev_calib_multiline(text: str) -> List[Dict[str, Any]]:
    """Development logs wrap one calibration record across many lines."""
    text = strip_ansi(text)
    rows: List[Dict[str, Any]] = []
    for part in text.split(CALIB_MARKER)[1:]:
        end = re.search(
            r"avg_docstring_tokens_per_snippet_token:\s*([\d.eE+-]+)",
            part,
        )
        if not end:
            continue
        block = part[: end.end()]
        row = {
            "requested": _grab_from_block(block, "batch_requested_nodes", True),
            "returned": _grab_from_block(block, "batch_returned_docstrings", True),
            "snippet_sum": _grab_from_block(block, "snippet_tokens_sum", True),
            "est_sum": _grab_from_block(block, "estimated_output_tokens_sum", True),
            "actual_json": _grab_from_block(block, "actual_json_output_tokens", True),
            "ratio_full": _grab_from_block(block, "ratio_actual_json_to_est_sum", False),
            "ratio_ret": _grab_from_block(
                block, "ratio_actual_to_returned_est_sum", False
            ),
            "avg_doc_per_snip": _grab_from_block(
                block, "avg_docstring_tokens_per_snippet_token", False
            ),
        }
        if row["est_sum"] is None and row["actual_json"] is None:
            continue
        rows.append(row)
    return rows


def parse_line(line: str) -> Optional[Dict[str, Any]]:
    return parse_jsonl_calib(line)


def parse_log_file(path: str) -> List[Dict[str, Any]]:
    """Prefer multiline dev parser; also accept JSONL lines."""
    with open(path, "r", errors="replace") as f:
        text = f.read()
    multi = parse_dev_calib_multiline(text)
    if len(multi) >= 1:
        return multi
    rows: List[Dict[str, Any]] = []
    for line in text.splitlines():
        p = parse_line(line)
        if p is not None:
            rows.append(p)
    return rows


def percentile(sorted_vals: List[float], p: float) -> Optional[float]:
    if not sorted_vals:
        return None
    xs = sorted(sorted_vals)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    t = k - lo
    return xs[lo] + t * (xs[hi] - xs[lo])


def compute_ratios(rows: List[Dict[str, Any]]) -> List[float]:
    out: List[float] = []
    for r in rows:
        est = r.get("est_sum")
        act = r.get("actual_json")
        if est and est > 0 and act is not None:
            out.append(act / est)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log_path", help="Path to tee'd parse / inference log")
    ap.add_argument(
        "--current-safety",
        type=float,
        default=1.0,
        help="Your INFERENCE_OUTPUT_ESTIMATE_SAFETY_MULTIPLIER (for recommendation)",
    )
    args = ap.parse_args()

    try:
        rows = parse_log_file(args.log_path)
    except OSError as e:
        print(f"Error reading {args.log_path}: {e}", file=sys.stderr)
        return 1

    if not rows:
        print(
            f"No {CALIB_MARKER} lines found in {args.log_path}. "
            "Re-run with INFERENCE_OUTPUT_CALIBRATION_LOG=1.",
            file=sys.stderr,
        )
        return 2

    complete = [
        r
        for r in rows
        if r.get("requested") and r.get("returned") == r.get("requested")
        and r.get("requested", 0) > 0
    ]
    ratios_all = compute_ratios(rows)
    ratios_complete = compute_ratios(complete)

    avgs: List[float] = []
    for r in rows:
        v = r.get("avg_doc_per_snip")
        if v is not None and v == v:
            avgs.append(float(v))

    def block(title: str, vals: List[float]) -> None:
        print(f"\n{title} (n={len(vals)})")
        if not vals:
            print("  (no data)")
            return
        print(f"  min:    {min(vals):.4f}")
        print(f"  p50:    {percentile(vals, 50):.4f}")
        print(f"  p90:    {percentile(vals, 90):.4f}")
        print(f"  max:    {max(vals):.4f}")

    print("Inference output calibration summary")
    print(f"  log: {args.log_path}")
    print(f"  calibration rows: {len(rows)}")
    print(f"  complete batches (returned == requested): {len(complete)}")

    block("Ratio: actual_json_tokens / estimated_output_tokens_sum (all rows)", ratios_all)
    block(
        "Ratio: actual_json / est_sum (complete batches only — use for safety tuning)",
        ratios_complete,
    )
    if avgs:
        block("avg_docstring_tokens_per_snippet_token (returned nodes)", avgs)

    # Recommendation from complete-batch p90
    base = ratios_complete if len(ratios_complete) >= 5 else ratios_all
    p90 = percentile(base, 90) if base else None
    p50 = percentile(base, 50) if base else None

    print("\n--- Recommendation ---")
    if p90 is None:
        print("  Not enough ratio samples for a safety multiplier suggestion.")
        return 0

    cur = max(1.0, min(2.0, float(args.current_safety)))
    # Target: p90 of (actual/est) <= 1 after scaling est by safety → want safety' >= safety * p90
    suggested = cur * p90
    suggested = max(1.0, min(2.0, round(suggested, 3)))

    print(
        f"  p90(actual/est) ≈ {p90:.4f} on the {'complete-batch' if len(ratios_complete) >= 5 else 'all-rows'} set."
    )
    print(f"  Current INFERENCE_OUTPUT_ESTIMATE_SAFETY_MULTIPLIER: {cur}")
    if p50 is not None:
        print(f"  p50(actual/est) ≈ {p50:.4f}")

    if p90 <= 1.01:
        tighter = max(1.0, round(cur * p90, 3))
        print(
            "  Estimates are conservative (actual JSON is below est at most percentiles): "
            f"p90(actual/est)={p90:.4f}."
        )
        print(
            f"  Try INFERENCE_OUTPUT_ESTIMATE_SAFETY_MULTIPLIER={tighter} "
            f"(≈ current × p90, floored at 1.0) for tighter batches, or leave {cur} for extra slack."
        )
    else:
        print(
            f"  Suggested INFERENCE_OUTPUT_ESTIMATE_SAFETY_MULTIPLIER: {suggested} "
            f"(= {cur} × p90, clamped to [1, 2])."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
