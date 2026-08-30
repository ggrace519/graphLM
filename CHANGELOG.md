# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to Semantic Versioning.

## [Unreleased]

### Added

- Two-pass LLM strategy: pass 1 sends directory tree only to identify key files, pass 2 sends tree + selected files for full analysis
- CLI tool via Typer with `--dry-run`, `--no-tests`, `--exclude`, and `--max-files` options
- Library API via single `generate_graph()` function returning `GraphResult`
- Pydantic v2 models for structured graph data (import edges, modules, data flow, DB schema, test mapping, architecture notes, quick reference)
- Project scanner with smart file ranking (config files > package init > source > tests)
- Token estimation heuristic (~4 UTF-8 bytes per token)
- LLM client with JSON recovery (strips code fences, finds braces in text)
- Retry logic with exponential backoff on connection errors
- Markdown and JSON output rendering
- System prompt with injection guard (treats file content as data only)
- Test fixtures: small, medium, and large project directories
- Tree-sitter-based AST parser for deterministic import/edge extraction (Python, JS, TS)
- `--ast` CLI flag: enables AST-derived deterministic import edges alongside LLM analysis
- Import cycle detection via Tarjan's SCC algorithm with risk scoring based on module size and cycle length
- `--no-show-cycles` / `--cycle-threshold` CLI flags for cycle control
- Interactive D3 force-graph HTML visualization output with zoom/pan, hover tooltips, click highlighting, search, and dark/light mode
- `--no-html` CLI flag (HTML enabled by default)
- New `deterministic_edges` and `import_cycles` fields on `CodebaseGraph` model

### Changed

- CLI writes `GRAPH.md` / `GRAPH.json` / `GRAPH.html` into the scanned project directory by default (not the process working directory). `-o` still overrides
- Output files are `GRAPH.md`, `GRAPH.json`, and `GRAPH.html` (were `graphs.md` / `graphs.json` / `graph.html`)
- AST import parsing is on by default; pass `--no-ast` or `ast=False` to skip. The `--ast` flag is removed
- `GraphResult.write()` now returns `tuple[Path, Path, Path | None]` (md, json, html_or_none) instead of `tuple[Path, Path]`
- `write_outputs()` now optionally writes HTML alongside Markdown and JSON

### Fixed

- Sensitive-file read gap: arbitrary `.env.<name>` files (e.g. `.env.qa`, `.env.test`) were scanned into LLM context because the sensitive-file check used a fixed allowlist. Any dotenv file is now treated as secret-bearing, except the non-secret templates `.env.example` / `.env.sample` / `.env.template` / `.env.dist` (#10)
- `GRAPHLM_MAX_CONTEXT` had no effect: it was parsed into `Settings` but never read, so the pass-2 context budget was always 120000. The budget now resolves as `--max-context` flag > `GRAPHLM_MAX_CONTEXT` env var > 120000 (#11)
- Pass-2 prompt could exceed `max_context` (#12): per-file admission respected the budget, but the AST-edge table was appended uncapped and the instruction block was never counted, so a project with many import edges produced an over-budget prompt (a 6000-edge table alone reached ~62k tokens regardless of the budget). Now every fixed section is reserved up front and the edge table is capped at a bounded share of the budget; when the table is truncated, its framing changes to tell the model the list is not exhaustive so it still infers the dropped edges. The full edge list is unaffected — it still reaches `graph.deterministic_edges` and cycle detection. Also removes spurious truncation of files that would have fit
- External symlinked *files* pointing outside the project were listed in the directory tree and consumed a `max_files` slot (only symlinked directories were guarded). Any symlink escaping the project is now skipped in the tree walk; file content was already blocked before reading

### Changed

- `--max-context` CLI flag now defaults to unset (falls back to `GRAPHLM_MAX_CONTEXT`, then 120000) instead of a hardcoded 120000, so the env var is honored
- HTML threw `TypeError: e is not iterable` on load: D3 v7 `scaleOrdinal(null, palette)` iterates a null domain; use `scaleOrdinal(palette)` as the range
- HTML visualization did not initialize: `initGraph` was never called on page load, and a recursive self-call could hang the page
- `--ast` computed import edges then discarded them; cycle detection ran on LLM edges without SLOC-based risk scores
- `--no-html` still wrote `graph.html` when `-o` was set (HTML was written twice)
- `result.write()` returned three paths but the README unpacked two; string output paths failed
- AST import resolver mapped packages to non-existent `pkg.py` files and stdlib modules to `os.py`
- LLM copied test-fixture database schemas into the host project graph

### Infrastructure

- Python 3.11+ with hatchling build, uv dependency management
- pytest-httpx for mock HTTP integration testing
- pytest + coverage in CI
- `.env.example` for LLM endpoint configuration
- GitHub Actions CI testing on Python 3.11, 3.12, 3.13 with coverage upload to Codecov
- mypy type checking in CI
- Removed stale generated artifacts (`graphs.md`, `graphs.json`, `graph.html`) left over from before the `GRAPH.*` output rename, and the committed `.coverage` database; the repo no longer ships tool output. Added `.coverage`, `coverage.xml`, and the `GRAPH.*` output files to `.gitignore` so generated artifacts stay out of version control
