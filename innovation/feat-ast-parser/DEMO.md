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
print(result.imports)   # list[ImportEdge]
print(result.exports)   # list[Symbol]
print(result.functions) # list[FunctionDef]
print(result.call_sites) # list[CallSite]

# Build a dependency graph from scan fragments
edges = build_dependency_graph(file_fragments, max_files=200, project_dir=project_path)

# Detect import cycles
cycles = detect_import_cycles(edges)
```

### From the CLI

```bash
# Dry run with AST detection
graphlm /path/to/project --dry-run --ast

# Full run with AST detection
graphlm /path/to/project -o ./output --ast
```

### Integration with graphLM

When `--ast` (or `ast=True`) is enabled, the parser runs after scanning and:

1. Extracts deterministic import edges from all scanned files
2. Passes those edges to the LLM as ground truth in the pass-2 prompt
3. Attaches `deterministic_edges` to the output `CodebaseGraph`

## Supported languages

| Language | Import parsing | Function extraction | Class extraction |
|------------|----------------|--------------------|------------------|
| Python | Yes | Yes | Yes |
| JavaScript | Partial | Partial | Partial |
| TypeScript | Partial | Partial | Partial |
