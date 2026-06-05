"""MCP server exposing GitHub Actions workflow validation.

Run over stdio (the default MCP transport):

    python -m gha_validator_mcp

Tools:
    validate_workflow_text(text)  -> validate inline YAML
    validate_workflow_file(path)  -> validate a file on disk
    list_rules()                  -> describe every active rule

Resource:
    gha-validator://rules         -> machine-readable rule catalog

Prompt:
    review_workflow(text)         -> a ready-made review prompt
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .rules import ALL_RULES
from .validator import validate_workflow_text as _validate

mcp = FastMCP("gha-validator")


def _rule_catalog() -> list[dict[str, str]]:
    catalog = []
    for rule in ALL_RULES:
        doc = (rule.__doc__ or "").strip().split("\n")[0]
        catalog.append({"function": rule.__name__, "description": doc})
    return catalog


@mcp.tool()
def validate_workflow_text(text: str) -> str:
    """Validate a GitHub Actions workflow given as raw YAML text.

    Returns a JSON report with pass/fail status, severity counts, and findings.
    """
    return json.dumps(_validate(text), indent=2)


@mcp.tool()
def validate_workflow_file(path: str) -> str:
    """Validate a GitHub Actions workflow file on disk by its path.

    Returns a JSON report identical in shape to validate_workflow_text.
    """
    p = Path(path)
    if not p.is_file():
        return json.dumps({"error": f"File not found: {path}"}, indent=2)
    return json.dumps(_validate(p.read_text(encoding="utf-8")), indent=2)


@mcp.tool()
def list_rules() -> str:
    """List every active validation rule and a one-line description of each."""
    return json.dumps(_rule_catalog(), indent=2)


@mcp.resource("gha-validator://rules")
def rules_resource() -> str:
    """Machine-readable catalog of all validation rules."""
    return json.dumps(_rule_catalog(), indent=2)


@mcp.prompt()
def review_workflow(text: str) -> str:
    """Generate a prompt asking an LLM to review a workflow using these rules."""
    return (
        "You are reviewing a GitHub Actions workflow for correctness and "
        "supply-chain safety. Run the validate_workflow_text tool on the YAML "
        "below, then summarize the findings by severity and suggest concrete "
        f"fixes.\n\n```yaml\n{text}\n```"
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
