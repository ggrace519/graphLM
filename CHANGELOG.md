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

- HTML visualization rendered a blank page: D3 `forceLink` threw on import/data-flow endpoints that had no node, and the simulation never ticked positions onto the SVG
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
