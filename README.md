# GitHub Actions Validator — MCP Server

An [MCP](https://modelcontextprotocol.io) server that validates GitHub Actions
workflow files for correctness and supply-chain safety. Point an MCP client
(Claude Desktop, the MCP Inspector, or your own agent) at it and ask it to
check a workflow. It returns a structured report of findings instead of a wall
of prose.

The validation engine is plain Python and fully testable on its own. The MCP
layer is a thin wrapper that exposes it as tools, a resource, and a prompt.

## What it checks

Each rule has a stable ID so findings are easy to suppress, track, or assert
against in tests.

| ID | Severity | Check |
|------|----------|-------|
| WF000 | error | YAML fails to parse or top level is not a mapping |
| WF001 | warning | No top-level `name` |
| WF002 | error | No `on` trigger block |
| WF003 | error | No jobs defined |
| WF004 | error | Job missing `runs-on` |
| WF005 | warning | Action pinned to a tag, not a commit SHA |
| WF006 | error | Action has no version pin at all |
| WF007 | error | Env var looks like an inline secret |
| WF008 | warning | No top-level `permissions` block |
| WF009 | info | Job has no `timeout-minutes` |

## MCP surface

**Tools**
- `validate_workflow_text(text)` — validate inline YAML
- `validate_workflow_file(path)` — validate a file on disk
- `list_rules()` — describe every active rule

**Resource**
- `gha-validator://rules` — machine-readable rule catalog

**Prompt**
- `review_workflow(text)` — a ready-made review prompt that drives the tools

## How to run

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Run the server over stdio (the default MCP transport):

```bash
python -m gha_validator_mcp
# or, via the installed entry point:
gha-validator-mcp
```

The server speaks MCP over stdin/stdout, so it expects an MCP client on the
other end rather than a human. The two easy ways to drive it:

**MCP Inspector** (interactive, browser-based):

```bash
npx @modelcontextprotocol/inspector python -m gha_validator_mcp
```

**Claude Desktop** — add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "gha-validator": {
      "command": "python",
      "args": ["-m", "gha_validator_mcp"]
    }
  }
}
```

Then ask: *"Validate the workflow at .github/workflows/ci.yml."*

## How to test

The engine has no MCP dependency, so the test suite runs fast and offline:

```bash
pip install -e ".[dev]"
pytest
```

You can also sanity-check the engine directly without a client:

```bash
python -c "from gha_validator_mcp.validator import validate_workflow_text as v; \
import json; print(json.dumps(v(open('examples/sample-workflow.yml').read()), indent=2))"
```

## Layout

```
src/gha_validator_mcp/
  rules.py       # one small function per check, plus a registry
  validator.py   # parse YAML + run rules -> JSON report
  server.py      # FastMCP wrapper (tools / resource / prompt)
  __main__.py    # python -m gha_validator_mcp
tests/
  test_validator.py
examples/
  sample-workflow.yml
```

## Author's notes

I build CI/CD platforms for a living, so the rules here reflect the review
comments I leave most often: pin your actions to a SHA, scope `GITHUB_TOKEN`
with an explicit `permissions` block, and keep secrets out of inline `env`.

The design choice worth calling out is the split between the engine and the
MCP layer. `validator.py` and `rules.py` know nothing about MCP. That keeps the
checks unit-testable in isolation and means the same engine could back a CLI, a
pre-commit hook, or a GitHub Action with no changes. The MCP server is
deliberately thin: it parses arguments, calls the engine, and serializes the
result.

Rules are intentionally small, independent functions registered in a list.
Adding a check is a function plus one line, and the rule's docstring is what
`list_rules` and the `gha-validator://rules` resource report, so documentation
stays next to the code.

One real-world gotcha is baked in: PyYAML parses the bare key `on:` as the
boolean `True`, not the string `"on"`. The trigger rule checks for both so it
does not false-positive on valid workflows.

## Known limitations

- Checks are structural and pattern-based. There is no JSON Schema validation
  of the full workflow syntax, so a malformed-but-parseable workflow can slip
  through.
- The secret detector is a heuristic on key names. It catches obvious inline
  credentials but will miss obfuscated ones and can flag false positives.
- Expression syntax inside `${{ }}` is not parsed or validated.
- Reusable workflow inputs and `matrix` strategies are not deeply inspected.
- SHA pinning is verified by shape (40 hex chars), not by resolving the ref
  against the real commit history.

## Next steps

- Add JSON Schema validation against the published GitHub Actions schema as a
  first pass, with these semantic rules layered on top.
- A `validate_workflow_dir(path)` tool to scan an entire `.github/workflows/`.
- Optional autofix suggestions returned alongside findings (e.g. the resolved
  SHA for a tagged action).
- Severity threshold config so teams can promote or demote individual rules.
- Package and publish so `pip install gha-validator-mcp` works directly.

## License

MIT
