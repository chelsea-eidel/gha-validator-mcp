# GitHub Actions Validator

Validate GitHub Actions workflows for correctness and supply-chain safety —
as an [MCP](https://modelcontextprotocol.io) server, a CLI, and a Claude Code
hook, all over one engine. Point an MCP client (Claude Desktop, the MCP
Inspector, or your own agent) at it and ask it to check a workflow; run
`gha-validate` in CI or a pre-commit hook; or let the Claude Code hook stop an
agent from writing a broken workflow in the first place. Every path returns the
same structured report of findings instead of a wall of prose.

The validation engine is plain Python and fully testable on its own. Three
thin consumers sit on top of the same engine:

1. **An MCP server** — exposes the checks as tools, a resource, and a prompt.
2. **A CLI** (`gha-validate`) — the same checks for a Makefile, pre-commit, or a
   shell pipeline, with no MCP client involved.
3. **A Claude Code hook** — a `PreToolUse` gate that stops an agent from writing
   an invalid workflow in the first place (see [Claude Code hook](#claude-code-hook)).

One engine, three entry points. Adding a rule improves all three at once.

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

## CLI

The engine also ships as a standalone command, handy outside any agent:

```bash
gha-validate .github/workflows/ci.yml     # one file, prints a JSON report
gha-validate a.yml b.yml some/dir/        # several files and/or directories
gha-validate --github                     # scan .github/workflows/ in this repo
cat ci.yml | gha-validate -               # read from stdin
gha-validate --github --quiet             # summary + exit code, no JSON
```

Exit codes: `0` clean (warnings/info may still be present), `1` error-severity
findings in any file, `2` bad invocation. A compact per-file summary prints to
stderr, so CI logs stay readable even with `--quiet`. That makes it a drop-in
pre-commit, Make, or CI step.

## Claude Code hook

[Claude Code](https://code.claude.com) can run a `PreToolUse` hook before it
writes a file. This repo includes one that blocks the agent from writing an
invalid workflow and hands the findings back so it can fix them and retry.

How it works:

- It fires on the `Write` and `Edit` tools and checks `tool_input.file_path`.
  Non-workflow paths exit immediately with no decision, so nothing else is
  affected.
- For `Write`, it validates `tool_input.content` (the whole new file). For
  `Edit`, Claude Code sends a diff (`old_string`/`new_string`), not the finished
  file, so the hook reads the current file from disk, applies the replacement,
  and validates the *result*.
- If there are any error-severity findings it returns a `deny` decision whose
  reason lists each finding by rule ID. Warnings and info never block.
- It fails open: malformed input or an engine it cannot reach exits without a
  decision, so a broken hook never wedges your session. Pair that with
  `"onFailure": "block"` in settings if you want the opposite stance.

Install it into a repo:

```bash
mkdir -p .claude/hooks
cp hooks/validate_workflow_hook.py .claude/hooks/
# then merge .claude/settings.json (below) into the repo's settings
```

The included `.claude/settings.json` wires it up:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PROJECT_DIR}/.claude/hooks/validate_workflow_hook.py\"",
            "timeout": 30,
            "onFailure": "block"
          }
        ]
      }
    ]
  }
}
```

The hook calls the `gha-validate` CLI as a subprocess, so the package must be
importable by the Python that runs the hook (`pip install -e .` in the repo's
environment is enough).

> The hook lives in two places on purpose: `hooks/` is the canonical source in
> the repo, and `.claude/hooks/` is where Claude Code loads it from via
> `${CLAUDE_PROJECT_DIR}`. Keep them in sync, or symlink one to the other.

To confirm the exact stdin field names on your Claude Code version, set
`GHA_VALIDATOR_DEBUG=1` and the hook dumps the raw payload to the scratchpad
directory on its next run.

## Continuous integration

The hook guards workflows as an agent writes them locally; CI guards them on the
way into the repo. Same engine, two gates. This repo ships two workflows:

- `.github/workflows/ci.yml` — installs the package and runs the test suite on
  Python 3.10 – 3.12.
- `.github/workflows/validate-workflows.yml` — runs `gha-validate --github`,
  validating every workflow in the repo against the same rules. The project
  validates its own CI, so both of these files are held to the strict rule set
  (SHA-pinned actions, scoped `permissions`, job timeouts).

Dropping the second workflow into any repo gives that repo the same check with
no other setup.

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
  cli.py         # gha-validate command (file or stdin)
  __main__.py    # python -m gha_validator_mcp
hooks/
  validate_workflow_hook.py   # Claude Code PreToolUse gate (canonical source)
.claude/
  settings.json               # wires the hook to Write|Edit
  hooks/                      # where Claude Code loads the hook from
.github/workflows/
  ci.yml                      # test suite on Python 3.10-3.12
  validate-workflows.yml      # runs gha-validate --github on the repo itself
tests/
  test_validator.py           # engine checks
  test_hook.py                # hook stdin/stdout contract
examples/
  sample-workflow.yml
```

## Author's notes

I build CI/CD platforms for a living, so the rules here reflect the review
comments I leave most often: pin your actions to a SHA, scope `GITHUB_TOKEN`
with an explicit `permissions` block, and keep secrets out of inline `env`.

The design choice worth calling out is the split between the engine and its
consumers. `validator.py` and `rules.py` know nothing about MCP, the CLI, or
Claude Code. That keeps the checks unit-testable in isolation and is why the
same engine backs an MCP server, a CLI, and a Claude Code hook with no changes
to the rules. Each consumer is deliberately thin: it adapts its input to a YAML
string, calls the engine, and adapts the report back out.

The hook was the most interesting of the three to build. The non-obvious part
is that Claude Code's `Edit` tool sends a diff, not the resulting file, so to
validate what the file *will* look like the hook reads the current version from
disk and applies the replacement itself. It also fails open by design: a gate
that wedges your agent on its own bug is worse than one that occasionally lets a
bad write through, so uncertainty (unparseable input, an unreachable engine, a
tool shape it does not model) results in no decision rather than a block. Teams
that want the stricter stance get it with one line (`"onFailure": "block"`).

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
- The hook validates one write at a time. If the agent builds an invalid
  workflow across several edits, each intermediate state is judged on its own;
  an edit is only blocked once the file as a whole has an error.
- The hook's `Edit` reconstruction assumes `old_string` appears in the on-disk
  file. If Claude Code's `Edit` field names differ on your version, run once
  with `GHA_VALIDATOR_DEBUG=1` and adjust — the field names are confirmed for
  current Claude Code but are the part most likely to drift.

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
