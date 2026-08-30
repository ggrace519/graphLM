# graphLM

Generate codebase graphs from any project directory using an OpenAI-compatible LLM.

Given a project directory, graphLM produces a structured analysis as **Markdown**, **JSON**, and an interactive **HTML** graph — a map of the codebase you can use to understand unfamiliar projects without reading every file.

## What it produces

- **Directory tree** — annotated tree of the project
- **Import edges** — dependency relationships between files
- **Modules** — named components and what they do
- **Data flow** — how data moves through the system
- **Database schema** — tables and columns (if applicable)
- **Test organization** — test files mapped to what they cover
- **Architecture notes** — key decisions and patterns
- **Quick reference** — "where do I find X?" lookups
- **Import cycles** — strongly-connected components with SLOC-based risk scores
- **Interactive HTML** — D3 force graph (`GRAPH.html`) with zoom/pan, search, and theme toggle

## Installation

```bash
cd /path/to/graphLM
uv sync
```

Or install the CLI globally:

```bash
uv pip install -e .
```

## Usage

### CLI

```bash
# Analyze a project; writes GRAPH.md, GRAPH.json, GRAPH.html into that project
graphlm /path/to/project

# Write to a different directory
graphlm /path/to/project -o ./output

# Dry run — see context stats without calling the LLM
graphlm /path/to/project --dry-run

# Override LLM settings from the command line
graphlm /path/to/project -b https://api.example.com/v1 -k sk-xxx -m my-model

# Exclude test files and custom patterns
graphlm /path/to/project --no-tests --exclude __pycache__ --exclude .git

# Skip Tree-sitter AST import edges
graphlm /path/to/project -o ./output --no-ast

# Skip writing GRAPH.html
graphlm /path/to/project -o ./output --no-html
```

### Library API

```python
from graphlm import generate_graph
from pathlib import Path

result = generate_graph("/path/to/project")
md_path, json_path, html_path = result.write(Path("./output"))
# html_path is Path | None (None if include_html=False)
```

`GraphResult.write` accepts `str | Path` and returns `tuple[Path, Path, Path | None]` (Markdown, JSON, HTML).

```python
result = generate_graph(
    "/path/to/project",
    base_url="https://api.example.com/v1",
    api_key="sk-xxx",
    model="Qwen3.6-35B",
    output_dir="./output",
    ast=True,              # Tree-sitter import edges + SLOC cycle scores (default)
    include_html=True,     # skip GRAPH.html when False (default: write it)
    show_cycles=True,      # skip the cycle section when False
    cycle_threshold=0.0,   # min cycle risk score
)

print(len(result.graph.modules), "modules found")
```

AST parsing is on by default: graphLM runs Tree-sitter, attaches `graph.deterministic_edges`, passes those edges into the pass-2 prompt as ground truth, and runs cycle detection on the AST edges with SLOC-based risk scores. Pass `ast=False` or `--no-ast` to skip. `include_html=False` skips writing `GRAPH.html` when `output_dir` is set (HTML is on by default).

## How it works

graphLM uses a **two-pass LLM strategy** to stay within context windows while still producing comprehensive graphs:

1. **Pass 1** — The directory tree (no file contents) is sent to the LLM, which identifies the most important files to read.
2. **Pass 2** — The tree + those key files are sent to the LLM, which produces the final structured graph.

This keeps the first pass lightweight (~tree tokens) and ensures the second pass only includes files that matter.

A Tree-sitter pass (Python imports) runs by default. It does not replace the LLM: the two-pass analysis still runs, and AST edges are extra ground truth plus cycle detection. Pass `--no-ast` to skip.

## Configuration

graphLM reads its LLM settings from environment variables. Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Variable | Description | Default |
|---|---|---|
| `GRAPHLM_BASE_URL` | OpenAI-compatible API endpoint | `https://openrouter.ai/api/v1` |
| `GRAPHLM_API_KEY` | API key for authentication | *(required)* |
| `GRAPHLM_MODEL` | Model name to use | `openai/gpt-4o` |

Settings can also be passed directly via CLI flags (`-b`, `-k`, `-m`) or library arguments.

## Options

| Flag | Description | Default |
|---|---|---|
| `-o, --output-dir` | Output directory for `GRAPH.md`, `GRAPH.json`, and `GRAPH.html` | The scanned project |
| `-b, --base-url` | LLM API base URL | `GRAPHLM_BASE_URL` env var |
| `-k, --api-key` | LLM API key | `GRAPHLM_API_KEY` env var |
| `-m, --model` | Model name | `GRAPHLM_MODEL` env var |
| `--max-files` | Maximum files to scan initially | 200 |
| `--max-file-chars` | Maximum characters per file | 4000 |
| `--max-pass2-files` | Max files in pass 2 context | 80 |
| `--max-context` | Token budget for pass-2 context | `GRAPHLM_MAX_CONTEXT` env var, else 120000 |
| `--no-tests` | Exclude test files | Tests included by default |
| `--exclude` | Exclude pattern (repeatable) | — |
| `--no-redact` | Skip secret redaction | Redaction on |
| `--dry-run` | Show stats without calling LLM | Disabled |
| `--no-ast` | Skip Tree-sitter AST import edges | AST on |
| `--no-html` | Do not write `GRAPH.html` | HTML on |
| `--no-show-cycles` | Skip the cycle section | Cycles on |
| `--cycle-threshold` | Minimum cycle risk score | 0.0 |

## Project structure

```
graphlm/
├── __init__.py           # Library API — generate_graph()
├── _html_template.html   # D3 visualization template
├── cli.py                # CLI entry point — Typer
├── config.py             # Settings from environment variables
├── context.py            # Two-pass prompt assembly
├── cycles.py             # Import cycle detection (Tarjan + SLOC risk)
├── html_render.py        # Interactive D3 HTML visualization
├── llm.py                # LLM client with retry and JSON recovery
├── models.py             # Pydantic v2 data models
├── parser.py             # Tree-sitter AST import parser
├── prompts.py            # System prompt (injection guard)
├── render.py             # Markdown + JSON + HTML output rendering
└── scanner.py            # Project directory scanner
tests/
├── conftest.py
├── test_cli.py
├── test_config.py
├── test_context.py
├── test_cycles.py
├── test_html_render.py
├── test_integration.py
├── test_llm.py
├── test_models.py
├── test_parser.py
├── test_prompts.py
├── test_render.py
├── test_scanner.py
└── fixtures/             # Small, medium, large test projects
```

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) for dependency management (recommended)
