# Contributing

Thanks for looking. This package talks to a live brokerage account, so the bar is deliberate.

## Setup

```bash
git clone https://github.com/stephus182/ibkr_core_mcp.git && cd ibkr_core_mcp
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,server]"
git config core.hooksPath .githooks     # the four CI gates as a pre-push hook
```

## Before you push

Run the four gates as four separate commands — never piped, never chained with `&&` — and read
each status:

```bash
ruff check .
ruff format --check .
mypy
pytest -m "not integration" -q > out.txt; ec=$?; tail -3 out.txt
```

CI runs the same four, then `pip-audit` and `gitleaks`.

## Rules that will get a PR declined

- **Never weaken the order gates.** No bypass flag, no cached approval, no fallback beyond the
  OS's own password prompt, and the gates stay inside `IBKRClient`. `tests/security/` checks this
  from source; see `SECURITY.md` and `docs/security-architecture.md`.
- **Docs first.** Any change to IBKR endpoint behaviour, paths, field names or error codes cites
  the official page (`docs/external-docs-reference.md` has the URL tables) in the commit message.
  Nothing is assumed from memory.
- **A new tool declares its side effects** in its `capabilities` set, and no tool may declare order
  execution.
- **A new model is tested against a captured live response**, never against a dict written to
  match the model (`tests/fixtures/ibkr_live_shapes.json`).
- **Public definitions carry docstrings** (`ruff`'s D1xx rules are enforced).

## What to include in a PR

What changed and why, the official source for any API claim, the test that would have caught the
bug (for fixes), and `CHANGELOG.md` under `[Unreleased]`.
