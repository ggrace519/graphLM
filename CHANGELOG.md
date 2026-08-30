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

- `GraphResult.write()` now returns `tuple[Path, Path, Path | None]` (md, json, html_or_none) instead of `tuple[Path, Path]`
- `write_outputs()` now optionally writes HTML alongside Markdown and JSON

### Infrastructure

- Python 3.11+ with hatchling build, uv dependency management
- pytest-httpx for mock HTTP integration testing
- 105 tests across 9 module test files, 90% code coverage
- `.env.example` for LLM endpoint configuration
- GitHub Actions CI testing on Python 3.11, 3.12, 3.13 with coverage upload to Codecov
- mypy type checking in CI
