# graphLM

Generate codebase graphs from any project directory using an OpenAI-compatible LLM.

Given a project directory, graphLM produces a structured analysis as **Markdown** and **JSON** — a map of the codebase you can use to understand unfamiliar projects without reading every file.

## What it produces

- **Directory tree** — annotated tree of the project
- **Import edges** — dependency relationships between files
- **Modules** — named components and what they do
- **Data flow** — how data moves through the system
- **Database schema** — tables and columns (if applicable)
- **Test organization** — test files mapped to what they cover
- **Architecture notes** — key decisions and patterns
- **Quick reference** — "where do I find X?" lookups

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
# Analyze a project and write output files
graphlm /path/to/project -o ./output

# Dry run — see context stats without calling the LLM
graphlm /path/to/project --dry-run

# Override LLM settings from the command line
graphlm /path/to/project -b https://api.example.com/v1 -k sk-xxx -m my-model

# Exclude test files and custom patterns
graphlm /path/to/project --no-tests --exclude __pycache__ --exclude .git
```

### Library API

```python
from graphlm import generate_graph

result = generate_graph(
    "/path/to/project",
    base_url="https://api.example.com/v1",
    api_key="sk-xxx",
    model="Qwen3.6-35B",
    output_dir="./output",
)

# Access the graph directly
print(len(result.graph.modules), "modules found")

# Or write outputs manually
md_path, json_path = result.write("./output")
```

## How it works

graphLM uses a **two-pass LLM strategy** to stay within context windows while still producing comprehensive graphs:

1. **Pass 1** — The directory tree (no file contents) is sent to the LLM, which identifies the most important files to read.
2. **Pass 2** — The tree + those key files are sent to the LLM, which produces the final structured graph.

This keeps the first pass lightweight (~tree tokens) and ensures the second pass only includes files that matter.

## Configuration

graphLM reads its LLM settings from environment variables. Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Variable | Description | Default |
|---|---|---|
| `GRAPHLM_BASE_URL` | OpenAI-compatible API endpoint | `https://studio.gracebkp.cloud/v1` |
| `GRAPHLM_API_KEY` | API key for authentication | *(required)* |
| `GRAPHLM_MODEL` | Model name to use | `Qwen3.6-35B` |

Settings can also be passed directly via CLI flags (`-b`, `-k`, `-m`) or library arguments.

## Options

| Flag | Description | Default |
|---|---|---|
| `-o, --output-dir` | Output directory for .md and .json | Current directory |
| `-b, --base-url` | LLM API base URL | `GRAPHLM_BASE_URL` env var |
| `-k, --api-key` | LLM API key | `GRAPHLM_API_KEY` env var |
| `-m, --model` | Model name | `GRAPHLM_MODEL` env var |
| `--max-files` | Maximum files to scan initially | 200 |
| `--max-file-chars` | Maximum characters per file | 4000 |
| `--max-pass2-files` | Max files in pass 2 context | 80 |
| `--no-tests` | Exclude test files | Enabled (included) |
| `--exclude` | Exclude pattern (repeatable) | — |
| `--dry-run` | Show stats without calling LLM | Disabled |

## Project structure

```
graphlm/
├── __init__.py      # Library API — generate_graph()
├── cli.py           # CLI entry point — Typer
├── config.py        # Settings from environment variables
├── context.py       # Two-pass prompt assembly
├── llm.py           # LLM client with retry and JSON recovery
├── models.py        # Pydantic v2 data models
├── prompts.py       # System prompt (injection guard)
├── render.py        # Markdown + JSON output rendering
└── scanner.py       # Project directory scanner
tests/
├── conftest.py
├── test_cli.py
├── test_config.py
├── test_context.py
├── test_integration.py
├── test_llm.py
├── test_models.py
├── test_prompts.py
├── test_render.py
├── test_scanner.py
└── fixtures/        # Small, medium, large test projects
```

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) for dependency management (recommended)
