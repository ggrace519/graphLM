# AST Parser — Deterministic Dependency Graph

## What it does

Uses Tree-sitter to parse source files and extract deterministic import edges,
function/class definitions, and call sites — no LLM needed.

## How to use it

### As a library

```python
from graphlm.parser import parse_file, build_dependency_graph, detect_import_cycles
from pathlib import Path

# Parse a single file
result = parse_file(Path("src/myapp.py"))
print(result.imports)    # list[ImportEdge]
print(result.exports)    # list[str]
print(result.functions)  # list[str]
print(result.call_sites) # list[str]

# Build a dependency graph from scan fragments
edges = build_dependency_graph(file_fragments, max_files=200, project_dir=project_path)

# Detect import cycles
cycles = detect_import_cycles(edges)
```

### From the CLI

```bash
# Dry run (AST is on by default)
graphlm /path/to/project --dry-run

# Skip AST parsing
graphlm /path/to/project -o ./output --no-ast
```

### Integration with graphLM

AST parsing is on by default. After scanning, the parser:

1. Extracts deterministic import edges from all scanned files
2. Passes those edges to the LLM as ground truth in the pass-2 prompt
3. Attaches `deterministic_edges` to the output `CodebaseGraph`

It does not replace the two-pass LLM analysis. Pass `--no-ast` or `ast=False` to skip.

## Supported languages

| Language | Import parsing | Function extraction | Class extraction |
|------------|----------------|--------------------|------------------|
| Python | Yes | Yes | Yes |
| JavaScript | Not implemented | Not implemented | Not implemented |
| TypeScript | Not implemented | Not implemented | Not implemented |

JavaScript and TypeScript files parse to an empty result. Python only.
