# DEMO — AST Parser (Innovation #1)

## What works

- `graphlm/parser.py` — Tree-sitter-based AST parser that extracts:
  - Import edges (from `import X` and `from X import Y` statements)
  - Function definitions (names, signatures, async detection)
  - Class definitions (names, line numbers)
  - Call sites (function calls, method calls)
  - Export symbols (public classes and dunder functions)

- `graphlm.parser.detect_language()` — auto-detects language from file extension
- `graphlm.parser.build_dependency_graph()` — builds deterministic import graph from file fragments
- `graphlm.parser.detect_import_cycles()` — Tarjan's SCC algorithm for cycle detection

## How to try it

```bash
# Parse a single file
uv run python -c "
from graphlm.parser import parse_file
result = parse_file('/path/to/project/main.py')
print('Functions:', result.functions)
print('Imports:', [e.to_path for e in result.imports])
"

# Build a dependency graph from a project
uv run python -c "
from pathlib import Path
from graphlm.scanner import scan_project
from graphlm.parser import build_dependency_graph

scan = scan_project(Path('/path/to/project'))
edges = build_dependency_graph(scan.file_fragments, project_dir=Path('/path/to/project'))
for e in edges:
    print(f'{e.from_path} -> {e.to_path} ({e.kind})')
"

# Check for import cycles
uv run python -c "
from pathlib import Path
from graphlm.scanner import scan_project
from graphlm.parser import build_dependency_graph, detect_import_cycles

scan = scan_project(Path('/path/to/project'))
edges = build_dependency_graph(scan.file_fragments, project_dir=Path('/path/to/project'))
cycles = detect_import_cycles(edges)
print(f'Found {len(cycles)} cycles')
for c in cycles:
    print('  Cycle:', ' -> '.join(c))
"
```

## Status

Working — all 32 tests pass, 163 total tests pass.

## Next increments

- Add JavaScript/TypeScript parsing support (currently returns empty results)
- AST parsing is on by default (`--no-ast` to skip)
- Add caller/callee edge analysis (beyond just imports)
