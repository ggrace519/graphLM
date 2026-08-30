# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`graphlm` is a CLI + library that generates a codebase graph (Markdown + JSON + interactive HTML) from any project directory, using an OpenAI-compatible LLM plus deterministic Tree-sitter AST parsing. Python 3.11+, `uv`-managed, Pydantic v2, Typer CLI, `httpx` for the LLM call. No async — the LLM client is synchronous.

## Commands

```bash
uv sync --group dev                          # install (incl. pytest, pytest-cov, pytest-httpx, mypy)
uv run pytest -q                             # full suite (~266 tests, ~2.5s, no network — LLM is mocked via pytest-httpx)
uv run pytest tests/test_parser.py -q        # one file
uv run pytest tests/test_parser.py::test_name -q   # one test
uv run pytest --cov=graphlm --cov-report=term-missing   # coverage (CI reports it; ~90%, but NOT gated — no --cov-fail-under)
uv run mypy graphlm --ignore-missing-imports # type check (separate CI job; keep it clean)
graphlm /path/to/project --dry-run           # exercise scan + AST + context packing without any LLM call
```

CI (`.github/workflows/ci.yml`) runs pytest+coverage on Python 3.11/3.12/3.13 and mypy on 3.12. There is no linter/formatter configured — match surrounding style.

## Architecture — the big picture

The *analysis* pipeline lives in `graphlm/__init__.py::generate_graph()` — read that function first; it orchestrates everything below in order. (Output is separate: the library only writes when `output_dir` is set; the CLI leaves it `None` and writes itself — see below.)

**Two-pass LLM strategy** (the core design, to stay inside context windows):
1. **Pass 1** — `context.assemble_pass1_prompt(tree)` sends *only* the directory tree. The LLM returns `{"requested_files": [...]}` — the files it wants to read.
2. **Pass 2** — `context.filter_requested_files()` maps those back to scanned fragments (with a fuzzy-match fallback), then `assemble_pass2_prompt()` assembles tree + file contents + the AST-edge table + the instruction block, and asks for the full `CodebaseGraph` JSON. The token budget is enforced: the tree, edge table, instruction block, and an output reserve are all counted up front, and files are admitted only until the running total would exceed `max_context` (over-budget files land in `truncated_paths`). So the assembled prompt stays within `max_context`.

`--dry-run` skips both LLM calls. It does *not* model "all scanned files" — it selects `scan.file_fragments[:max_pass2_files]` (default cap 80), builds a `CodebaseGraph` carrying the AST edges + cycles + a dry-run note, and the CLI prints token estimates *and* graph-section counts. Tokens are estimated by a crude heuristic — `estimate_tokens` = UTF-8 bytes // 4 (defined in *both* `context.py` and `scanner.py`).

**AST parser is ground truth, not a replacement for the LLM** (`parser.py`, on by default; `--no-ast` disables). `build_dependency_graph()` extracts Python import edges with Tree-sitter and resolves them *only against files that exist in the scan* (stdlib/third-party/missing modules are dropped — resolution is against the `known_files` set, independent of `project_dir`). `project_dir` is *optional*: given, `_source_bytes` reads the untruncated/unredacted file off disk; omitted, it falls back to the (truncated) `frag.content`. Those `deterministic_edges` are (a) injected into the pass-2 prompt as a "do not contradict" table, and (b) used for cycle detection instead of the LLM's edges. So the LLM's `import_edges` and the AST's `deterministic_edges` are separate fields on `CodebaseGraph` and can differ. Only Python is fully implemented; JS/TS are recognized by extension but return empty `ParsedFile`.

**Cycle detection** (`cycles.py`) runs Tarjan SCC over the AST edges (falling back to LLM edges if AST is off), scoring each cycle `log10(total_lines) * cycle_length`. Note the SLOC term is a *physical* line count (`frag.content.count("\n") + 1`, including blanks/comments) over the scanned fragment — which is truncated at `max_file_chars` (default 4000) — so it under-counts large files; it is not true source-lines-of-code. Also: `parser.py` *also* has its own `detect_import_cycles()` (returns bare node lists, no scores) — the live path uses `cycles.detect_cycles()`; don't confuse the two.

**Data models** (`models.py`) — `CodebaseGraph` is the Pydantic schema the LLM must emit and the single source of truth for output shape. `Cycle` is a frozen dataclass (not Pydantic). The pass-2 prompt in `context.py` hand-writes the JSON schema description for the LLM; **if you add/rename a field on `CodebaseGraph`, update that prompt text and `render.py` in the same change** — they are not auto-derived from the model.

**Output** (`render.py`) — writes `GRAPH.md`, `GRAPH.json`, `GRAPH.html`. The `*_suffix` params default to `"GRAPH"`. HTML (`html_render.py` + `_html_template.html`) is a single self-contained *file* (string-substituted, no build step) — but it loads D3 from a CDN (`_html_template.html` → `https://d3js.org/d3.v7.min.js`), so the graph won't render offline. HTML is on by default; `--no-html` / `include_html=False` skips it.

**Output destination is the scanned project, not cwd.** The CLI passes `output_dir=None` into `generate_graph` (so the library doesn't write), then writes via `result.write(output_destination(...))`, which defaults to the *scanned project dir* unless `-o` is given. This split (fixed in #8) is deliberate — don't "simplify" it by having `generate_graph` write directly.

## Security invariants (don't weaken these)

The scanner treats scanned files as hostile input and has layered defenses — preserve them when editing `scanner.py`/`prompts.py`/`context.py`:
- **Sensitive files are never read** (`_is_sensitive_file`): TLS/key/cert extensions (`.pem/.key/.crt/…`); *any* dotenv file (`.env`, `.env.<anything>`) except the non-secret templates `.env.example/.sample/.template/.dist` (see `_ENV_SAFE_SUFFIXES`); and name globs like `*secrets*`/`*token*`. Source extensions (`.py`, `.ts`, …) are exempted from the name globs so `token.py` still gets analyzed.
- **Secret redaction** (`_redact_secrets`) runs on every file's content by default (`--no-redact` disables) — regex passes for AWS keys, GitHub tokens, private-key headers, connection strings, etc.
- **Symlink escape prevention** (`_path_is_inside`): any symlink (file *or* directory) pointing outside the project is skipped — in the tree walk (so it never appears in the tree or consumes a `max_files` slot) and again before reading content in `os.walk`.
- **Prompt-injection guard**: `SYSTEM_PROMPT` (`prompts.py`) and the pass-2 prompt both instruct the model to treat all file content as data, never instructions. Keep that clause if you touch the prompts.

## Config

LLM settings come from `GRAPHLM_BASE_URL` / `GRAPHLM_API_KEY` / `GRAPHLM_MODEL`, loaded from `.env` via `python-dotenv` in `config.py`. CLI flags `-b/-k/-m` override; if you pass any of the three to `generate_graph`, you must pass all three. The context budget resolves `--max-context` flag > `GRAPHLM_MAX_CONTEXT` env var > 120000 (the `--max-context` flag and `generate_graph(max_context=...)` default to `None` so the env var can take effect). `.env.example` shows the shape (defaults point at a self-hosted `studio.gracebkp.cloud` Qwen endpoint). `.env` is gitignored — never commit it.

## Tests

`tests/fixtures/{small,medium,large,cyclic}_project/` are realistic sample trees the scanner/parser/cycle tests run against; `pyproject.toml` sets `norecursedirs = ["tests/fixtures"]` so pytest doesn't collect them as tests. `tests/test_integration.py` mocks the LLM HTTP call with `pytest-httpx` — no real network. When adding a scanner/parser feature, add or extend a fixture rather than mocking file I/O.

## CLI flags worth knowing

Beyond the config flags above: `--dry-run` (scan + AST, no LLM), `--no-ast`, `--no-html`, `--no-tests`, `--no-redact`, `--exclude <pat>` (repeatable), and the cycle controls `--no-show-cycles` (skip the import-cycle section) / `--cycle-threshold <float>` (only report cycles with risk ≥ threshold). Sizing knobs: `--max-files` (scan cap, default 200), `--max-file-chars` (per-file, 4000), `--max-pass2-files` (files in pass-2 context, 80), `--max-context` (token budget). See `graphlm --help` for the full list.
