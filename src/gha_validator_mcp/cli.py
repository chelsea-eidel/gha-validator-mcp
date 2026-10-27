"""Command-line entry point for the validator engine.

This is the same engine the MCP server and the Claude Code hook use. Having a
plain CLI means the checks can also run from a Makefile, a pre-commit hook, CI,
or a shell pipeline with no MCP client involved.

Usage:
    gha-validate path/to/workflow.yml       # validate one file
    gha-validate a.yml b.yml dir/           # several files and/or directories
    cat workflow.yml | gha-validate -       # validate stdin
    gha-validate --github                   # scan .github/workflows/ in the repo

Exit codes:
    0  no error-severity findings anywhere (warnings/info may still be present)
    1  one or more error-severity findings
    2  bad invocation (no such file, nothing to scan, etc.)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .validator import validate_workflow_text

_SUFFIXES = (".yml", ".yaml")
_DEFAULT_GITHUB_DIR = Path(".github/workflows")


def _collect(paths: list[str], use_github: bool) -> tuple[list[Path], list[str]]:
    """Expand the given paths (and/or the --github dir) into workflow files.

    Returns (files, errors). Directories are scanned for *.yml/*.yaml. Explicit
    file arguments are kept as-is so a non-workflow path still reports clearly.
    """
    files: list[Path] = []
    errors: list[str] = []

    targets = list(paths)
    if use_github:
        targets.append(str(_DEFAULT_GITHUB_DIR))

    for raw in targets:
        p = Path(raw)
        if p.is_dir():
            found = sorted(
                f for f in p.rglob("*") if f.suffix in _SUFFIXES and f.is_file()
            )
            if not found:
                errors.append(f"no workflow files under {raw}")
            files.extend(found)
        elif p.is_file():
            files.append(p)
        else:
            errors.append(f"cannot read {raw}: no such file or directory")

    return files, errors


def _validate_file(path: Path) -> dict:
    report = validate_workflow_text(path.read_text(encoding="utf-8"))
    report["file"] = str(path)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gha-validate",
        description="Validate GitHub Actions workflows for correctness and supply-chain safety.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Workflow files and/or directories to validate, or '-' for stdin.",
    )
    parser.add_argument(
        "--github",
        action="store_true",
        help="Also scan .github/workflows/ relative to the current directory.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the JSON report; use the exit code and summary only.",
    )
    args = parser.parse_args(argv)

    # Stdin mode: single document, keeps the original simple contract.
    if args.paths == ["-"]:
        report = validate_workflow_text(sys.stdin.read())
        if not args.quiet:
            print(json.dumps(report, indent=2))
        return 0 if report["passed"] else 1

    if not args.paths and not args.github:
        parser.error("give one or more paths, '-' for stdin, or --github")

    files, errors = _collect(args.paths, args.github)
    for err in errors:
        print(f"gha-validate: {err}", file=sys.stderr)

    if not files:
        return 2

    reports = [_validate_file(f) for f in files]
    failed = [r for r in reports if not r["passed"]]

    if not args.quiet:
        print(json.dumps(reports, indent=2))

    # A compact human summary on stderr so it shows even with --quiet and
    # alongside the JSON on stdout (handy in CI logs).
    for r in reports:
        mark = "FAIL" if not r["passed"] else "ok"
        c = r["counts"]
        print(
            f"[{mark}] {r['file']}  "
            f"errors={c['error']} warnings={c['warning']} info={c['info']}",
            file=sys.stderr,
        )
    print(
        f"gha-validate: {len(files)} file(s), {len(failed)} failed.",
        file=sys.stderr,
    )

    if errors:
        # Unreadable targets are an invocation problem even if scanned files passed.
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
