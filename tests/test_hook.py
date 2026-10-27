"""Tests for the Claude Code PreToolUse hook.

The hook is exercised as a subprocess exactly as Claude Code runs it: a JSON
payload on stdin, a decision (or silence) on stdout. This verifies the real
contract, not just internal functions.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "hooks" / "validate_workflow_hook.py"
SRC = REPO / "src"

CLEAN = (REPO / "examples" / "sample-workflow.yml").read_text()

BAD = "jobs:\n  build:\n    steps:\n      - uses: some/action\n"


def _run_hook(payload: dict, cwd: Path) -> subprocess.CompletedProcess:
    env = {"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"}
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
    )


def _decision(proc: subprocess.CompletedProcess):
    out = proc.stdout.strip()
    if not out:
        return None
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"]


def test_write_bad_workflow_is_denied(tmp_path):
    proc = _run_hook(
        {"tool_name": "Write", "tool_input": {
            "file_path": ".github/workflows/ci.yml", "content": BAD}},
        cwd=tmp_path,
    )
    assert proc.returncode == 0
    assert _decision(proc) == "deny"
    reason = json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "WF004" in reason  # missing runs-on surfaced to the agent


def test_write_clean_workflow_is_allowed(tmp_path):
    proc = _run_hook(
        {"tool_name": "Write", "tool_input": {
            "file_path": ".github/workflows/ci.yml", "content": CLEAN}},
        cwd=tmp_path,
    )
    assert proc.returncode == 0
    assert _decision(proc) is None  # silence = no decision = allowed


def test_non_workflow_path_passes_through(tmp_path):
    proc = _run_hook(
        {"tool_name": "Write", "tool_input": {
            "file_path": "src/app.py", "content": "jobs: nonsense"}},
        cwd=tmp_path,
    )
    assert proc.returncode == 0
    assert _decision(proc) is None


def test_edit_introducing_error_is_denied(tmp_path):
    wf = tmp_path / ".github" / "workflows" / "ci.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text(CLEAN)
    proc = _run_hook(
        {"tool_name": "Edit", "tool_input": {
            "file_path": ".github/workflows/ci.yml",
            "old_string": "    runs-on: ubuntu-latest\n",
            "new_string": ""}},
        cwd=tmp_path,
    )
    assert _decision(proc) == "deny"
    assert "WF004" in proc.stdout


def test_edit_keeping_valid_is_allowed(tmp_path):
    wf = tmp_path / ".github" / "workflows" / "ci.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text(CLEAN)
    proc = _run_hook(
        {"tool_name": "Edit", "tool_input": {
            "file_path": ".github/workflows/ci.yml",
            "old_string": 'echo "hello"',
            "new_string": 'echo "hi"'}},
        cwd=tmp_path,
    )
    assert _decision(proc) is None


def test_malformed_stdin_fails_open(tmp_path):
    proc = _run_hook_raw("not json at all", cwd=tmp_path)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def _run_hook_raw(raw: str, cwd: Path) -> subprocess.CompletedProcess:
    env = {"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"}
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=raw,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
    )
