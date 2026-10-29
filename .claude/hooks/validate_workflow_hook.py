#!/usr/bin/env python3
"""Claude Code PreToolUse hook: validate GitHub Actions workflows before write.

Wired on the Write and Edit tools. When the agent is about to write or edit a
file under .github/workflows/, this hook reconstructs the *resulting* file
content and runs the gha-validator engine against it. If there are any
error-severity findings, the write is denied and the findings are handed back
to the agent as the reason, so it can fix them and try again.

Contract notes (Claude Code hooks):
- Input: a JSON object on stdin.
    .tool_name            -> "Write" | "Edit"
    .tool_input.file_path -> target path
    Write:  .tool_input.content                       (the whole new file)
    Edit:   .tool_input.old_string / .new_string      (a diff, NOT the file)
  The Write/Edit field names here are observed from the payload dump (set
  GHA_VALIDATOR_DEBUG=1), not from the hooks docs page, which defers Edit's
  tool_input shape to the tools reference. Because Edit sends a diff, we read
  the current file from disk and apply the replacement to get the post-edit
  content.
- Output to DENY: exit 0 and print JSON with hookSpecificOutput.permissionDecision
  = "deny". We use the JSON form (not exit 2) so the reason is delivered cleanly.
- Non-workflow paths: exit 0 with no output -> no decision, normal flow continues.
- This hook is fail-open by design: if it cannot reach or run the validator, it
  exits 0 with no decision and the write proceeds, so a broken hook never wedges
  the agent. Per the docs, exit 1 is a *non-blocking* error (the call proceeds
  anyway) and only exit 2 blocks; we rely on neither for enforcement -- denial
  always goes through the JSON decision above.
Set GHA_VALIDATOR_DEBUG=1 to dump the raw stdin payload to the scratchpad dir,
which is how you confirm the exact field names on your Claude Code version.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

WORKFLOW_MARKERS = (".github/workflows/",)
WORKFLOW_SUFFIXES = (".yml", ".yaml")


def _deny(reason: str) -> None:
    """Emit a PreToolUse deny decision and exit."""
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(out))
    sys.exit(0)


def _allow_silently() -> None:
    """No decision: let the normal permission flow proceed."""
    sys.exit(0)


def _is_workflow_path(path: str) -> bool:
    norm = path.replace("\\", "/")
    if not any(norm.endswith(s) for s in WORKFLOW_SUFFIXES):
        return False
    return any(marker in norm for marker in WORKFLOW_MARKERS)


def _post_edit_content(tool_input: dict, file_path: str) -> str | None:
    """Reconstruct file content after an Edit by applying the replacement on disk."""
    old = tool_input.get("old_string")
    new = tool_input.get("new_string")
    if old is None or new is None:
        return None
    try:
        current = Path(file_path).read_text(encoding="utf-8")
    except OSError:
        # New file via Edit, or unreadable: nothing on disk to validate against.
        return None
    if tool_input.get("replace_all"):
        return current.replace(old, new)
    return current.replace(old, new, 1)


def _candidate_content(tool_name: str, tool_input: dict, file_path: str) -> str | None:
    if tool_name == "Write":
        return tool_input.get("content")
    if tool_name == "Edit":
        return _post_edit_content(tool_input, file_path)
    # MultiEdit or anything else we don't model: don't guess, don't block.
    return None


def _debug_dump(raw: str) -> None:
    if os.environ.get("GHA_VALIDATOR_DEBUG") != "1":
        return
    scratch = os.environ.get("CLAUDE_SCRATCHPAD_DIR") or os.environ.get("TMPDIR") or "/tmp"
    try:
        dest = Path(scratch) / "gha_validator_hook_stdin.json"
        dest.write_text(raw, encoding="utf-8")
    except OSError:
        pass


def main() -> None:
    raw = sys.stdin.read()
    _debug_dump(raw)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        # Can't parse the hook input: fail open so we never wedge the agent.
        _allow_silently()

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""

    if not file_path or not _is_workflow_path(file_path):
        _allow_silently()

    content = _candidate_content(tool_name, tool_input, file_path)
    if content is None:
        # We couldn't determine the resulting content (e.g. unmodeled tool, or
        # a diff we couldn't apply). Don't block on uncertainty.
        _allow_silently()

    # Run the shared engine via its CLI, reading the candidate content on stdin.
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "gha_validator_mcp.cli", "-"],
            input=content,
            capture_output=True,
            text=True,
            timeout=20,
        )
        except (OSError, subprocess.TimeoutExpired) as exc:
        # Fail open: we could not run the validator (not installed, timed out).
        # stderr is surfaced under `claude --debug`, but we exit 0 with no
        # decision so the write is never silently wedged by a broken hook.
        # (Exit 1 would NOT block the call anyway -- only exit 2 does -- so a
        # non-zero exit here would be a misleading no-op.)
        print(f"gha-validator hook could not run, allowing write: {exc}", file=sys.stderr)
        _allow_silently()

    if proc.returncode == 0:
        _allow_silently()

    # Non-zero exit: the engine reported findings (exit 1). Parse the report and
    # deny only on findings we can actually read. If the output is not the report
    # shape we expect, fail open rather than block on something we can't explain.
    try:
        report = json.loads(proc.stdout)
        errors = [f for f in report.get("findings", []) if f.get("severity") == "error"]
    except json.JSONDecodeError:
        print(
            f"gha-validator hook got unparseable output, allowing write:\n{proc.stdout}",
            file=sys.stderr,
        )
        _allow_silently()

    if not errors:
        # Non-zero exit but no error-severity findings we recognize: don't block.
        _allow_silently()

    lines = [
        f"  [{f.get('rule_id', '?')}] {f.get('location', '?')}: {f.get('message', '')}"
        for f in errors
    ]
    reason = (
        f"Blocked write to {file_path}. The workflow has "
        f"{len(errors)} error-severity issue(s):\n" + "\n".join(lines) +
        "\n\nFix these and try the write again."
    )
    _deny(reason)

if __name__ == "__main__":
    main()
