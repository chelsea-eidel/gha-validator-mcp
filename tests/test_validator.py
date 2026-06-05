"""Tests for the validation engine (no MCP transport needed)."""

from gha_validator_mcp.validator import validate_workflow_text

CLEAN = """
name: CI
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@8f4b7f84864484a7bf31766abe9204da3cbe65b3
      - run: echo hello
"""

BAD = """
jobs:
  build:
    steps:
      - uses: actions/checkout@v4
      - uses: some/action
    env:
      API_KEY: "hardcoded-value-123"
"""


def _ids(report):
    return {f["rule_id"] for f in report["findings"]}


def test_clean_workflow_passes():
    report = validate_workflow_text(CLEAN)
    assert report["parsed"] is True
    assert report["passed"] is True
    assert report["counts"]["error"] == 0


def test_missing_trigger_and_runs_on_are_errors():
    report = validate_workflow_text(BAD)
    ids = _ids(report)
    assert "WF002" in ids
    assert "WF004" in ids
    assert report["passed"] is False


def test_unpinned_action_flagged():
    ids = _ids(validate_workflow_text(BAD))
    assert "WF005" in ids
    assert "WF006" in ids


def test_inline_secret_flagged():
    assert "WF007" in _ids(validate_workflow_text(BAD))


def test_missing_permissions_warning():
    assert "WF008" in _ids(validate_workflow_text(BAD))


def test_invalid_yaml_returns_error_not_exception():
    report = validate_workflow_text("name: [unclosed")
    assert report["parsed"] is False
    assert report["passed"] is False
    assert report["findings"][0]["rule_id"] == "WF000"


def test_non_mapping_yaml():
    report = validate_workflow_text("- just\n- a\n- list")
    assert report["parsed"] is False
    assert "WF000" in _ids(report)
