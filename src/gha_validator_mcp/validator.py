"""Parse a workflow YAML string and run all rules against it."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import yaml

from .rules import Finding, run_rules

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def validate_workflow_text(text: str) -> dict[str, Any]:
    """Validate raw workflow YAML text.

    Returns a JSON-serializable report. Never raises on bad YAML; a parse
    failure comes back as a single error finding so callers get a uniform shape.
    """
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return _report([Finding("WF000", "error", f"YAML parse error: {exc}", "<file>")], parsed=False)

    if not isinstance(doc, dict):
        return _report(
            [Finding("WF000", "error", "Top-level YAML is not a mapping.", "<file>")],
            parsed=False,
        )

    return _report(run_rules(doc), parsed=True)


def _report(findings: list[Finding], parsed: bool) -> dict[str, Any]:
    findings = sorted(findings, key=lambda f: (_SEVERITY_ORDER.get(f.severity, 9), f.rule_id))
    counts = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    return {
        "parsed": parsed,
        "passed": counts["error"] == 0,
        "counts": counts,
        "findings": [asdict(f) for f in findings],
    }
