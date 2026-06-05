"""Validation rules for GitHub Actions workflow files.

Each rule inspects a parsed workflow dict and returns zero or more Findings.
Rules are intentionally small and independent so the set is easy to extend.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

Severity = str  # "error" | "warning" | "info"

# Matches a fully pinned action ref: owner/repo@<40-char sha>
_SHA_PIN = re.compile(r"^[^@]+@[0-9a-f]{40}$")
# Matches a floating major tag like actions/checkout@v4
_TAG_REF = re.compile(r"^[^@]+@v?\d+")


@dataclass
class Finding:
    rule_id: str
    severity: Severity
    message: str
    location: str  # human-readable path into the document, e.g. "jobs.build"


Rule = Callable[[dict[str, Any]], list[Finding]]


def _iter_jobs(doc: dict[str, Any]):
    jobs = doc.get("jobs")
    if isinstance(jobs, dict):
        for name, job in jobs.items():
            if isinstance(job, dict):
                yield name, job


def rule_has_name(doc: dict[str, Any]) -> list[Finding]:
    """Workflow should declare a top-level name for readable run logs."""
    if not doc.get("name"):
        return [Finding("WF001", "warning", "Workflow has no top-level 'name'.", "<root>")]
    return []


def rule_has_trigger(doc: dict[str, Any]) -> list[Finding]:
    """Workflow must declare triggers via 'on'."""
    # PyYAML parses the bare key `on:` as boolean True, so check both.
    if "on" not in doc and True not in doc:
        return [Finding("WF002", "error", "Workflow has no 'on' trigger block.", "<root>")]
    return []


def rule_jobs_present(doc: dict[str, Any]) -> list[Finding]:
    """Workflow must define at least one job."""
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return [Finding("WF003", "error", "Workflow defines no jobs.", "jobs")]
    return []


def rule_runs_on(doc: dict[str, Any]) -> list[Finding]:
    """Every job must specify a 'runs-on' runner (unless it only 'uses' a reusable workflow)."""
    findings: list[Finding] = []
    for name, job in _iter_jobs(doc):
        if "uses" in job:
            continue
        if not job.get("runs-on"):
            findings.append(
                Finding("WF004", "error", f"Job '{name}' is missing 'runs-on'.", f"jobs.{name}")
            )
    return findings


def rule_pinned_actions(doc: dict[str, Any]) -> list[Finding]:
    """Third-party actions should be pinned to a full commit SHA for supply-chain safety."""
    findings: list[Finding] = []
    for name, job in _iter_jobs(doc):
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if not isinstance(uses, str):
                continue
            if uses.startswith("./") or uses.startswith("docker://"):
                continue
            if _SHA_PIN.match(uses):
                continue
            if _TAG_REF.match(uses):
                findings.append(
                    Finding(
                        "WF005",
                        "warning",
                        f"Action '{uses}' is pinned to a tag, not a commit SHA.",
                        f"jobs.{name}.steps[{i}]",
                    )
                )
            else:
                findings.append(
                    Finding(
                        "WF006",
                        "error",
                        f"Action '{uses}' has no version pin at all.",
                        f"jobs.{name}.steps[{i}]",
                    )
                )
    return findings


def rule_no_plaintext_secrets(doc: dict[str, Any]) -> list[Finding]:
    """Flag env values that look like inline credentials instead of ${{ secrets.* }}."""
    findings: list[Finding] = []
    suspicious = re.compile(r"(token|secret|password|api[_-]?key)", re.IGNORECASE)

    def scan_env(env: Any, location: str):
        if not isinstance(env, dict):
            return
        for key, value in env.items():
            if not isinstance(value, str):
                continue
            if suspicious.search(str(key)) and "${{" not in value and value:
                findings.append(
                    Finding(
                        "WF007",
                        "error",
                        f"Env var '{key}' looks like an inline secret. Use a secrets reference.",
                        location,
                    )
                )

    scan_env(doc.get("env"), "env")
    for name, job in _iter_jobs(doc):
        scan_env(job.get("env"), f"jobs.{name}.env")
        steps = job.get("steps")
        if isinstance(steps, list):
            for i, step in enumerate(steps):
                if isinstance(step, dict):
                    scan_env(step.get("env"), f"jobs.{name}.steps[{i}].env")
    return findings


def rule_explicit_permissions(doc: dict[str, Any]) -> list[Finding]:
    """Recommend an explicit top-level 'permissions' block to scope GITHUB_TOKEN."""
    if "permissions" not in doc:
        return [
            Finding(
                "WF008",
                "warning",
                "No top-level 'permissions' block. Default token scope is broad.",
                "<root>",
            )
        ]
    return []


def rule_timeout_minutes(doc: dict[str, Any]) -> list[Finding]:
    """Jobs without 'timeout-minutes' can hang and burn runner minutes."""
    findings: list[Finding] = []
    for name, job in _iter_jobs(doc):
        if "uses" in job:
            continue
        if "timeout-minutes" not in job:
            findings.append(
                Finding(
                    "WF009",
                    "info",
                    f"Job '{name}' has no 'timeout-minutes'.",
                    f"jobs.{name}",
                )
            )
    return findings


# Ordered registry of all active rules.
ALL_RULES: list[Rule] = [
    rule_has_name,
    rule_has_trigger,
    rule_jobs_present,
    rule_runs_on,
    rule_pinned_actions,
    rule_no_plaintext_secrets,
    rule_explicit_permissions,
    rule_timeout_minutes,
]


def run_rules(doc: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    for rule in ALL_RULES:
        findings.extend(rule(doc))
    return findings
