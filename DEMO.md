# Import Cycle Detection with Risk Scoring

Detects circular import dependencies using Tarjan's strongly-connected-components algorithm and assigns a risk score to each cycle.

## How it works

1. `detect_cycles(edges)` runs Tarjan's SCC algorithm over the import edge graph
2. Self-loops (single-node SCCs) are excluded — only cycles with 2+ nodes are reported
3. Each cycle gets a risk score: `log10(sum of SLOC for all nodes) * cycle_length`
4. Cycles are sorted by risk score (highest first)

## CLI usage

```bash
graphlm /path/to/project

# Hide cycle results
graphlm /path/to/project --no-show-cycles

# Only show cycles with risk score >= 2.0
graphlm /path/to/project --cycle-threshold 2.0
```

## Library usage

```python
from graphlm import generate_graph
from graphlm.cycles import detect_cycles, compute_sloc_map

# detect_cycles runs automatically on generate_graph output
result = generate_graph("/path/to/project")
print(result.graph.import_cycles)  # list[Cycle]

# Or compute SLOC map from scanner fragments
from graphlm.scanner import scan_project
scan = scan_project(Path("/path/to/project"))
sloc_map = compute_sloc_map(scan.file_fragments)
cycles = detect_cycles(edges, sloc_map=sloc_map)
```

## Data model

`Cycle` is a frozen dataclass with:

- `nodes: list[str]` — sorted file paths in the cycle
- `edges: list[ImportEdge]` — edges where both endpoints are in the SCC
- `length: int` — number of nodes
- `risk_score: float` — computed risk score

## Example output

```
## Import Cycles

### Cycle 1 (risk score: 3.4)
*3 nodes*
- `app/main.py`
- `app/routes.py`
- `app/services.py`
```
