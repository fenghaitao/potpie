"""Command-line interface for repowiki."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from .analysis import analyze_file
from .discovery import discover_sources
from .dispatch import repowiki_dispatch
from .models import GenerationRequest


def _to_dict(obj) -> object:
    """Recursively convert dataclasses to dicts for JSON serialisation."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_dict(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, list):
        return [_to_dict(i) for i in obj]
    return obj


def _cmd_extract(args: argparse.Namespace) -> None:
    """
    Discover and analyse source files, then emit structured JSON.

    This is the extraction step intended for agent consumption: the agent
    reads the JSON and uses its LLM reasoning to write rich wiki pages.
    """
    languages = args.languages or []

    try:
        sources = discover_sources(args.target)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    if languages:
        sources = [sf for sf in sources if sf.language in languages]

    if not sources:
        print(f"No supported source files found in '{args.target}'.", file=sys.stderr)
        sys.exit(1)

    modules = []
    skipped = []
    for sf in sources:
        module = analyze_file(sf, include_private=args.include_private)
        if module is None:
            skipped.append(sf.path)
        else:
            modules.append(module)

    output = {
        "target": args.target,
        "modules": [_to_dict(m) for m in modules],
        "skipped": skipped,
    }

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)
        print(f"Extracted {len(modules)} module(s) to '{args.output}'.")
        if skipped:
            print(f"Skipped {len(skipped)} file(s): {skipped}", file=sys.stderr)
    else:
        json.dump(output, sys.stdout, indent=2)
        sys.stdout.write("\n")


def _cmd_generate(args: argparse.Namespace) -> None:
    """Generate static Markdown docs (for testing/demonstration only)."""
    request = GenerationRequest(
        target=args.target,
        output_dir=args.output_dir,
        output_style=args.style,
        include_private=args.include_private,
        languages=args.languages or [],
    )

    result = repowiki_dispatch(request)

    if result.warnings:
        for w in result.warnings:
            print(w, file=sys.stderr)

    if result.docs_generated == 0:
        sys.exit(1)

    print(f"Generated {result.docs_generated} file(s) in '{args.output_dir}':")
    for path in result.output_paths:
        print(f"  {path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="repowiki",
        description=(
            "Analyse source files and produce structured extraction for wiki generation. "
            "Use 'extract' to produce JSON for agent consumption, "
            "or 'generate' for static Markdown output (demo/test only)."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- extract subcommand ---
    extract = subparsers.add_parser(
        "extract",
        help="Discover and analyse source files, emit structured JSON for agent consumption.",
    )
    extract.add_argument("target", nargs="?", default=".", help="Directory or file to analyse")
    extract.add_argument("--output", "-o", help="Write JSON to this file (default: stdout)")
    extract.add_argument(
        "--languages", "-l",
        nargs="+",
        choices=["python", "typescript", "cpp"],
        help="Restrict to specific languages",
    )
    extract.add_argument("--include-private", action="store_true")

    # --- generate subcommand (demo/test) ---
    generate = subparsers.add_parser(
        "generate",
        help="Generate static Markdown docs directly (demo/test only, no LLM).",
    )
    generate.add_argument("target", nargs="?", default=".")
    generate.add_argument("--output-dir", "-o", default="docs")
    generate.add_argument(
        "--style",
        choices=["docs-folder", "github-wiki"],
        default="docs-folder",
    )
    generate.add_argument("--languages", "-l", nargs="+", choices=["python", "typescript", "cpp"])
    generate.add_argument("--include-private", action="store_true")

    args = parser.parse_args()

    if args.command == "extract":
        _cmd_extract(args)
    elif args.command == "generate":
        _cmd_generate(args)


if __name__ == "__main__":
    main()
