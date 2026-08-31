# Contributing to graphLM

Thanks for your interest in graphLM! It's a small, focused tool, and
contributions — bug reports, fixes, docs, new language support — are welcome.
This guide covers how to get set up, what "done" looks like here, and the few
invariants that must not be weakened.

## TL;DR

```bash
git clone https://github.com/ggrace519/graphLM && cd graphLM
uv sync --group dev            # install deps + pytest, pytest-cov, pytest-httpx, mypy
uv run pytest -q               # full suite — no network, the LLM is mocked
uv run mypy graphlm --ignore-missing-imports
```

Branch off `main`, make your change with tests, keep mypy clean, add a CHANGELOG
entry, and open a PR. Details below.

## Development setup

graphLM is Python 3.11+ managed with [uv](https://github.com/astral-sh/uv).

```bash
uv sync --group dev
```

That's the whole setup — no services, no Docker, no API keys needed for the test
suite. (You only need an LLM endpoint to run graphlm against a *real* project;
the tests mock it.)

## Running the checks

The test suite is fast (a few seconds) and hits no network — the LLM HTTP call is
mocked with `pytest-httpx`.

```bash
uv run pytest -q                                   # full suite
uv run pytest tests/test_parser.py -q              # one file
uv run pytest tests/test_parser.py::test_name -q   # one test
uv run pytest --cov=graphlm --cov-report=term-missing   # with coverage
uv run mypy graphlm --ignore-missing-imports       # type check
```

CI runs the suite on Python 3.11 / 3.12 / 3.13 and mypy on 3.12 (see
`.github/workflows/ci.yml`). There is **no linter or formatter** configured —
match the style of the surrounding code.

`graphlm <project> --dry-run` is a handy no-network smoke test: it exercises the
scan, AST parse, and context packing without any LLM call.

## What "done" looks like

This project holds a few standards; a change isn't finished until it meets them:

- **Tests ship with the change**, not after. Aim to keep coverage at or above its
  current level (~90%). Prefer extending a fixture under `tests/fixtures/` over
  mocking file I/O when you add scanner/parser behavior.
- **`uv run pytest -q` passes and `mypy` is clean.** "Done" means you ran them and
  saw green — please paste the result in the PR.
- **Keep modules cohesive and under ~600 lines.** Split logically rather than
  growing a god-module.
- **A CHANGELOG entry** under `## [Unreleased]` for anything with an
  externally-observable effect (a flag, an output change, a fixed bug). Lead with
  what changed and why it matters.
- **Docs in lockstep.** If your change touches something the README, `CLAUDE.md`,
  or the pass-2 prompt describes (a flag, an output field, a default), update it
  in the *same* PR — not "later."
- **Data-model changes are not auto-derived.** If you add or rename a field on
  `CodebaseGraph` (`graphlm/models.py`), update the hand-written schema
  description in the pass-2 prompt (`graphlm/context.py`) **and** `render.py` in
  the same change — they don't update themselves.

## Security invariants — please don't weaken these

graphLM points an LLM at a directory of code it did not write, so it treats every
scanned file as **hostile input**. Several layered defenses exist for that reason;
preserve them when editing `scanner.py` / `prompts.py` / `context.py`:

- **Sensitive files are never read** — TLS/key/cert extensions, any dotenv file
  (except non-secret templates), and secret-name globs (`_is_sensitive_file`).
- **Secrets are redacted** from file content by default (`_redact_secrets`).
- **Symlinks escaping the project are skipped** — in the tree walk and again
  before reading content (`_path_is_inside`).
- **Prompt-injection guard** — the system prompt and pass-2 prompt both instruct
  the model to treat file content as data, never instructions. Keep that clause.

If a change would relax one of these, say so explicitly in the PR and explain why
— it needs a deliberate look, not a silent slip.

## Branching, commits, and PRs

- **Branch off `main`** — never commit to `main` directly. Name branches
  `<type>/<kebab-summary>` (e.g. `fix/src-layout-edges`, `feat/js-parser`).
- **One coherent change per PR.** Split unrelated themes.
- **Conventional Commits with a scope**: `fix(scanner): …`, `feat(cli): …`,
  `docs: …`. Short imperative subject; a body explaining the *what and why* when
  the change isn't self-evident. Reference an issue/PR number (`#NN`) when
  relevant.
- **Open the PR against `main`.** The body should have a Summary, what changed and
  why, and a **Verification** section (the test/mypy results you saw). Fill in the
  PR template.
- **Bugs get a tracking issue.** For anything that affects correctness, scoring,
  or output, open an issue (symptom, root cause, impact, fix) and reference it
  from the PR (`Closes #NN`).

## Adding language support

The Tree-sitter parser (`graphlm/parser.py`) fully implements **Python** import
resolution today; JS/TS are recognized by extension but return an empty parse.
Adding a language means wiring its Tree-sitter grammar, an import-edge extractor,
and edge resolution against the scanned file set — plus a fixture project under
`tests/fixtures/` and tests. This is a great, well-scoped contribution; open an
issue first so we can talk through the approach.

## Reporting security issues

**Do not** open a public issue for a security vulnerability. See
[SECURITY.md](SECURITY.md) for private reporting.

## Code of conduct

By participating you agree to abide by our
[Code of Conduct](CODE_OF_CONDUCT.md).
