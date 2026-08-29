# Codebase Graph

This file was generated automatically by graphLM. Use it as a map of the project structure without reading every file.

## Directory Tree

```

graphLM/
  graphlm/
    graphlm/tests/
      graphlm/tests/fixtures/
    graphlm/__init__.py
    graphlm/cli.py
    graphlm/config.py
    graphlm/context.py
    graphlm/llm.py
    graphlm/models.py
    graphlm/prompts.py
    graphlm/render.py
    graphlm/scanner.py
  tests/
    tests/fixtures/
      tests/fixtures/large_project/
        tests/fixtures/large_project/app/
          tests/fixtures/large_project/app/models/
          tests/fixtures/large_project/app/routes/
          tests/fixtures/large_project/app/services/
        tests/fixtures/large_project/docs/
        tests/fixtures/large_project/migrations/
        tests/fixtures/large_project/static/
          tests/fixtures/large_project/static/css/
          tests/fixtures/large_project/static/js/
        tests/fixtures/large_project/templates/
        tests/fixtures/large_project/tests/
      tests/fixtures/medium_project/
        tests/fixtures/medium_project/migrations/
        tests/fixtures/medium_project/src/
          tests/fixtures/medium_project/src/core/
          tests/fixtures/medium_project/src/utils/
        tests/fixtures/medium_project/tests/
      tests/fixtures/small_project/
        tests/fixtures/small_project/mylib/
  .coverage
  .env.example
  CHANGELOG.md
  README.md
  graphs.json
  graphs.md
  pyproject.toml
  uv.lock

```

## Import Edges

| From | To | Kind |
|------|-----|------|
| `graphlm/__init__.py` | `graphlm/config.py` | import |
| `graphlm/__init__.py` | `graphlm/context.py` | import |
| `graphlm/__init__.py` | `graphlm/llm.py` | import |
| `graphlm/__init__.py` | `graphlm/prompts.py` | import |
| `graphlm/__init__.py` | `graphlm/render.py` | import |
| `graphlm/__init__.py` | `graphlm/scanner.py` | import |
| `graphlm/cli.py` | `graphlm/__init__.py` | import |
| `graphlm/config.py` | `dotenv` | import |
| `graphlm/context.py` | `graphlm/scanner.py` | import |
| `graphlm/llm.py` | `graphlm/models.py` | import |
| `graphlm/render.py` | `graphlm/models.py` | import |
| `tests/fixtures/medium_project/src/core/__init__.py` | `tests/fixtures/medium_project/src/utils/__init__.py` | import |

## Modules

| Path | Name | Description |
|------|------|-------------|
| `graphlm/__init__.py` | Library API | Main entry point for library usage, exposing generate_graph() and GraphResult |
| `graphlm/cli.py` | CLI Interface | Typer-based command-line interface for graphLM |
| `graphlm/config.py` | Configuration | Settings management from environment variables |
| `graphlm/context.py` | Context Assembly | Two-pass prompt assembly for LLM interaction |
| `graphlm/llm.py` | LLM Client | HTTP client for OpenAI-compatible LLM endpoints with retry logic |
| `graphlm/models.py` | Data Models | Pydantic v2 models for structured graph data |
| `graphlm/prompts.py` | System Prompts | Static system prompt with security injection guards |
| `graphlm/render.py` | Output Renderer | Converts graph data to Markdown and JSON formats |
| `graphlm/scanner.py` | Project Scanner | Directory walker with smart file ranking and secret redaction |
| `tests/fixtures/medium_project/src/core/__init__.py` | Core Engine | Main processing engine for data transformation |
| `tests/fixtures/medium_project/src/utils/__init__.py` | Utilities | Helper functions for text processing and list manipulation |

## Data Flow

| Source | Destination | Description |
|--------|-------------|-------------|
| CLI | generate_graph() | User provides project directory and options via CLI arguments |
| generate_graph() | scan_project() | Scans project directory to build file fragments and directory tree |
| scan_project() | assemble_pass1_prompt() | Passes directory tree to LLM for key file identification |
| LLM (Pass 1) | filter_requested_files() | LLM returns list of important files to analyze |
| filter_requested_files() | assemble_pass2_prompt() | Assembles context with tree and selected file contents |
| assemble_pass2_prompt() | call_llm() | Sends full context to LLM for graph generation |
| call_llm() | CodebaseGraph | LLM returns structured JSON graph data |
| CodebaseGraph | write_outputs() | Converts graph to Markdown and JSON files |

## Test Organization

| Test File | Covers |
|-----------|--------|
| `tests/test_cli.py` | CLI argument parsing and command execution |
| `tests/test_config.py` | Configuration loading from environment variables |
| `tests/test_context.py` | Two-pass prompt assembly and file filtering logic |
| `tests/test_integrat` | Integration tests for LLM interaction and end-to-end flows |

## Architecture Notes

- Two-pass LLM strategy: Pass 1 sends only directory tree to identify key files, Pass 2 sends tree + selected files for comprehensive analysis
- Security-first design: System prompt includes injection guards treating file content as data only
- Secret redaction: Scanner automatically excludes sensitive files and redacts secret-like patterns from content
- OpenAI-compatible API: Works with any OpenAI-compatible endpoint, not just OpenAI
- Pydantic v2 validation: All LLM responses validated against strict schema models
- Exponential backoff retry: LLM calls include retry logic with exponential backoff for resilience
- Token estimation: Uses heuristic of ~4 UTF-8 bytes per token for context window management

## File Summaries

### `graphlm/__init__.py`
Main library entry point exposing generate_graph() function and GraphResult class. Orchestrates the two-pass analysis workflow by importing and coordinating all other modules.

| Symbol | Type | Description |
|--------|------|-------------|
| `GraphResult` | class | Output artifacts container with graph data and metadata |
| `generate_graph` | function | Main API function to generate codebase graph from project directory |

### `graphlm/cli.py`
Typer-based CLI application providing command-line interface for graphLM. Defines all CLI options and handles argument parsing, error handling, and output display.

| Symbol | Type | Description |
|--------|------|-------------|
| `app` | variable | Typer application instance |
| `main` | function | CLI entry point command that orchestrates graph generation |

### `graphlm/config.py`
Configuration management module that loads LLM settings from environment variables. Provides frozen dataclass for immutable settings with validation.

| Symbol | Type | Description |
|--------|------|-------------|
| `Settings` | class | Frozen dataclass containing LLM endpoint configuration |

### `graphlm/context.py`
Context assembly module implementing the two-pass LLM strategy. Handles prompt construction for tree-only analysis and tree+files analysis.

| Symbol | Type | Description |
|--------|------|-------------|
| `Pass1Result` | class | Result container for first LLM pass containing requested files |
| `Pass2Context` | class | Context container for second LLM pass with tree and file fragments |
| `assemble_pass1_prompt` | function | Constructs user prompt for directory tree analysis |
| `filter_requested_files` | function | Filters and ranks requested files against scan results |

### `graphlm/llm.py`
LLM client module providing HTTP communication with OpenAI-compatible APIs. Includes retry logic, JSON recovery, and response parsing with Pydantic validation.

| Symbol | Type | Description |
|--------|------|-------------|
| `GraphLLError` | class | Base exception class for graphLM errors |
| `LLMResponse` | class | Normalized LLM response container |
| `_extract_json` | function | Extracts JSON from LLM response with multiple recovery strategies |
| `call_llm` | function | Main function to call LLM endpoint with retry and recovery |

### `graphlm/models.py`
Pydantic v2 data models defining the structure of codebase graph output. Includes models for import edges, modules, data flow, database schema, tests, and more.

| Symbol | Type | Description |
|--------|------|-------------|
| `ArchitectureNote` | class | Records architecture decisions or notes |
| `CodebaseGraph` | class | Complete codebase graph containing all analysis sections |
| `DBTable` | class | Represents a database table with columns |
| `DataFlowEdge` | class | Represents data flow relationship between components |
| `EntryPoint` | class | Represents application entry points like main functions or routes |
| `FileSummary` | class | Summary of an analyzed source file with symbols |
| `ImportEdge` | class | Represents import/dependency relationship between files |
| `ModuleDescription` | class | Describes a module or component in the codebase |
| `QuickReference` | class | Quick reference lookup entry for finding components |
| `Symbol` | class | Represents a public symbol (class, function, constant) |
| `TestMapping` | class | Maps test files to functionality they verify |

### `graphlm/prompts.py`
System prompt module containing the static prompt with security injection guards. Ensures LLM treats file content as data only.

| Symbol | Type | Description |
|--------|------|-------------|
| `SYSTEM_PROMPT` | constant | Static system prompt with security rules for codebase analysis |

### `graphlm/render.py`
Output rendering module that converts CodebaseGraph objects to Markdown and JSON formats. Handles formatting of all graph sections.

| Symbol | Type | Description |
|--------|------|-------------|
| `render_markdown` | function | Converts graph to formatted Markdown document |
| `write_outputs` | function | Writes Markdown and JSON output files to directory |

### `graphlm/scanner.py`
Project scanner module that walks directory trees, reads file contents, and excludes binary/sensitive files. Includes secret detection and token estimation.

| Symbol | Type | Description |
|--------|------|-------------|
| `FileFragment` | class | Container for file path, content, and token estimate |
| `ScanResult` | class | Result of scanning a project directory |
| `estimate_tokens` | function | Estimates token count from text using byte heuristic |
| `scan_project` | function | Main function to scan project directory and return file fragments |

### `tests/fixtures/medium_project/src/core/__init__.py`
Core engine module that processes input data using utility functions. Contains the main Engine class for data transformation.

| Symbol | Type | Description |
|--------|------|-------------|
| `Engine` | class | Main processing engine that transforms input data |

### `tests/fixtures/medium_project/src/utils/__init__.py`
Utility functions module providing text sanitization, output formatting, and list chunking helpers.

| Symbol | Type | Description |
|--------|------|-------------|
| `chunk_list` | function | Splits list into chunks of specified size |
| `format_output` | function | Joins list of strings with newlines |
| `sanitize` | function | Removes control characters and trims whitespace from text |

## Entry Points

| File | Name | Type | Description |
|------|------|------|-------------|
| `graphlm/__init__.py` | `generate_graph` | factory | Library API function that orchestrates two-pass graph generation workflow |
| `graphlm/cli.py` | `main` | cli_command | CLI entry point command that analyzes project directory and generates codebase graph |

## Quick Reference

| Find | Location |
|------|----------|
| Where are LLM settings configured? | `graphlm/config.py:Settings` |
| Where are test fixtures located? | `tests/fixtures/` |
| Where are the Pydantic models defined? | `graphlm/models.py` |
| Where is output rendering to Markdown/JSON? | `graphlm/render.py` |
| Where is the LLM client with retry logic? | `graphlm/llm.py:call_llm()` |
| Where is the library API function? | `graphlm/__init__.py:generate_graph()` |
| Where is the main CLI entry point? | `graphlm/cli.py:main()` |
| Where is the project directory scanner? | `graphlm/scanner.py:scan_project()` |
| Where is the system prompt with security guards? | `graphlm/prompts.py:SYSTEM_PROMPT` |
| Where is the two-pass strategy implemented? | `graphlm/context.py` |

