# CLAUDE.md

Guidance for working in this repository.

## What this project is

`gha-validator-mcp` is an [MCP](https://modelcontextprotocol.io) server that
validates GitHub Actions workflow files for **correctness** (does the workflow
have triggers, jobs, runners?) and **supply-chain safety** (are actions pinned
to commit SHAs? are secrets inlined? is `GITHUB_TOKEN` scoped?). It returns a
structured JSON report of findings rather than prose, so an agent or CI step can
act on it programmatically.

### Why it's shaped the way it is

The single most important design decision: **the validation engine knows nothing
about MCP.** `rules.py` and `validator.py` are plain Python with no `mcp`
import. `server.py` is a thin FastMCP wrapper over them. This keeps the engine
fast, offline-testable, and reusable as a CLI or pre-commit hook later. Preserve
this separation — don't reach for MCP types, transports, or context inside the
engine.

## Layout

```
src/gha_validator_mcp/
  rules.py       # one small function per check, plus the ALL_RULES registry
  validator.py   # parse YAML -> run rules -> JSON-serializable report
  server.py      # FastMCP wrapper: tools / resource / prompt
  __init__.py    # __version__
  __main__.py    # enables `python -m gha_validator_mcp`
tests/
  test_validator.py   # tests the engine directly, no MCP transport
examples/
  sample-workflow.yml
```

Data flow: `server.py` → `validator.validate_workflow_text(text)` →
`yaml.safe_load` → `rules.run_rules(doc)` → list of `Finding` → `_report` shapes
the JSON.

## Architectural conventions

- **Engine vs. transport.** Anything that inspects a workflow lives in the
  engine (`rules.py`/`validator.py`). Anything MCP-specific (tool decorators,
  JSON string serialization for the wire) lives in `server.py`. New checks go in
  the engine; new ways to *call* the engine go in `server.py`.
- **Rules are pure functions.** A rule is `Callable[[dict], list[Finding]]`. It
  takes a parsed workflow dict and returns zero or more `Finding`s. No I/O, no
  globals, no raising for control flow.
- **The validator never raises on bad input.** A YAML parse error or a
  non-mapping top level comes back as a `WF000` error finding, so callers always
  get the same report shape. Keep this contract — don't let exceptions escape
  `validate_workflow_text`.
- **The report shape is a contract.** `_report` returns
  `{parsed, passed, counts, findings}`. `passed` is true iff zero `error`
  findings. Tests and MCP clients depend on this; don't change keys casually.
- **Docstrings are documentation.** A rule's (and tool's) first docstring line is
  surfaced by `list_rules()` / the `gha-validator://rules` resource. Write the
  first line as a complete, user-facing description of the check — it can't drift
  from the docs because it *is* the docs.

## Rule structure & naming

- **Rule IDs** are `WF` + three digits (`WF001`…`WF009`), stable and never
  reused. `WF000` is reserved for parse/structure failures. New rules take the
  next free number. IDs are public API: clients suppress, track, and assert
  against them, so renumbering is a breaking change.
- **Severities** are the strings `"error" | "warning" | "info"`. `error` fails
  the workflow (`passed: false`); `warning`/`info` do not. Pick `error` only for
  things that are genuinely broken or unsafe.
- **Rule functions** are named `rule_<snake_case>` (e.g. `rule_pinned_actions`).
- **`Finding`** fields: `rule_id`, `severity`, `message`, `location`. `location`
  is a human-readable path into the document using dotted/indexed notation, e.g.
  `<root>`, `jobs.build`, `jobs.build.steps[2].env`. Match this style.
- **Messages** are one sentence, name the offending value, and (for warnings)
  hint at the fix.

## How to add a new rule

1. Write a `rule_<name>(doc) -> list[Finding]` function in `rules.py`. Use the
   `_iter_jobs(doc)` helper to walk jobs (it safely skips non-dict jobs).
2. Give it the next free `WF0NN` ID and a one-line docstring (this becomes its
   public description).
3. Add it to the `ALL_RULES` list — that registration is the only wiring needed;
   `server.py` and the rules resource pick it up automatically.
4. Add a test in `tests/test_validator.py` asserting the new ID appears (or
   doesn't) for the right input. Extend the `CLEAN`/`BAD` fixtures if needed —
   note that `CLEAN` must stay clean of *errors*, so only add warning/info-level
   triggers to it.
5. Add a row to the rule table in `README.md`.

### Gotchas when writing rules

- **`on:` parses as boolean `True`.** PyYAML reads the bare key `on:` as the
  Python bool `True`, not the string `"on"`. `rule_has_trigger` checks for both.
  Any rule that inspects triggers must account for this.
- **Be defensive about types.** A parsed workflow is arbitrary user YAML. Guard
  every `.get()` with `isinstance` checks before indexing — jobs, steps, and env
  may be missing, `None`, or the wrong type. The existing rules show the pattern.
- **Jobs that `uses:` a reusable workflow have no `runs-on`/`steps`/`timeout`.**
  Skip them where those checks don't apply (see `rule_runs_on`,
  `rule_timeout_minutes`).

## How to extend functionality

- **A new way to call the engine** (e.g. `validate_workflow_dir`): add a
  `@mcp.tool()` function in `server.py` that calls into the engine and
  `json.dumps(...)`es the result. Keep return types as JSON strings to match the
  existing tools.
- **A new MCP surface** (resource/prompt): use the FastMCP decorators
  (`@mcp.resource(...)`, `@mcp.prompt()`) as in `server.py`. Don't put logic
  here — delegate to the engine.
- **Don't suggest schema validation without keeping the semantic rules.** The
  intended direction (see README "Next steps") is JSON Schema validation as a
  *first pass* with these semantic rules layered on top — not a replacement.
- **Don't add heavy dependencies to the engine.** Runtime deps are just `mcp`
  and `pyyaml`; the engine itself only needs `pyyaml`. Keeping it light is what
  makes it embeddable. Justify any new dependency.

## Test conventions

- Tests target the **engine**, not the MCP transport — they import
  `validate_workflow_text` directly and run offline/fast. There is no need to
  stand up a server to test a rule.
- Fixtures: `CLEAN` (passes with zero errors) and `BAD` (triggers many rules)
  are module-level YAML strings. The `_ids(report)` helper collapses a report to
  its set of rule IDs; assert on IDs (`assert "WF005" in ids`) rather than on
  message text, which is allowed to change.
- Cover both directions for a rule: that it fires on bad input and stays quiet on
  good input. Also cover the no-raise contract (`test_invalid_yaml_*`).
- `pythonpath = ["src"]` is set in `pyproject.toml`, so imports work without
  installing.

## Build & run commands

```bash
# Setup (Python 3.10+)
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Test
pytest

# Run the MCP server over stdio (expects an MCP client on the other end)
python -m gha_validator_mcp        # or: gha-validator-mcp

# Drive it interactively with the MCP Inspector
npx @modelcontextprotocol/inspector python -m gha_validator_mcp

# Sanity-check the engine without any client
python -c "from gha_validator_mcp.validator import validate_workflow_text as v; \
import json; print(json.dumps(v(open('examples/sample-workflow.yml').read()), indent=2))"
```

## Code style

- Python 3.10+, `from __future__ import annotations` at the top of modules using
  modern type syntax.
- Type-hint public functions. The engine uses `dataclass` for `Finding` and
  `Callable[...]` aliases (`Rule`) for clarity.
- Keep rules small and independent — readability over cleverness. The whole point
  is that a check is one obvious function.
