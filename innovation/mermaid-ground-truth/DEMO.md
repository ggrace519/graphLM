# DEMO — Mermaid module graph + ground-truth layers (Innovation #7)

## The problem

The map computes ground truth — `deterministic_edges` (Tree-sitter import
edges) and `import_cycles` (Tarjan SCCs with risk scores) — but neither reached
the pictures. `GRAPH.html` drew only the LLM's `import_edges` and `data_flow`
and never highlighted a cycle, so the interactive view could contradict the
ground-truth table underneath it. And `GRAPH.md` had no diagram at all, while
`GRAPH.html` needs a CDN (D3) and is blank offline.

## What works

- `graphlm/mermaid.py::render_mermaid()` — a `## Module Graph` section in
  `GRAPH.md` right after the directory tree: a `flowchart LR` over
  **directory-level** nodes (files collapse to their parent directory; root
  files stay their own node), deduped, self-edges dropped, capped at 40 nodes
  by degree with a "… N more directories not shown" note. Parser edges are the
  source when present ("ground truth"), LLM edges are the `--no-ast` fallback
  ("inferred"). Cycle edges are emitted last and styled red via `linkStyle`;
  directories containing a cycle member get a red outline. Output is sorted so
  regenerated maps diff cleanly. Section omitted when there are no edges.
- `graphlm/html_render.py` — `deterministic_edges` become `type: "ast"` links
  (solid `#7aa2f7`); an LLM edge with the same `(from, to)` is dropped and the
  AST link marked `corroborated`; LLM-only imports stay grey `import` links.
  AST endpoints are upserted as nodes and every node carries `in_cycle`.
- `graphlm/_html_template.html` — red 2.5px ring on cycle members (survives
  hover), a **Layers** control (Parser imports / LLM imports / Data flow) that
  toggles link visibility with CSS `display` only, legend entries for the new
  link type and the ring, cycle membership in the tooltip, and a stats line
  with the per-type edge counts and the cycle count (`graphData.cycles`).

## How to try it

```bash
# No LLM needed — build the graph from the parser + cycle detector directly.
uv run python - <<'EOF'
from pathlib import Path
from graphlm.cycles import compute_sloc_map, detect_cycles
from graphlm.models import CodebaseGraph
from graphlm.parser import build_dependency_graph
from graphlm.render import write_outputs
from graphlm.scanner import scan_project

project = Path("tests/fixtures/cyclic_project")   # or Path(".") for graphlm itself
scan = scan_project(project)
edges = build_dependency_graph(scan.file_fragments, project_dir=project)
cycles = detect_cycles(edges, compute_sloc_map(scan.file_fragments))
graph = CodebaseGraph(directory_tree=scan.tree, deterministic_edges=edges, import_cycles=cycles)
md, _, html = write_outputs(graph, Path("/tmp/graphlm-demo"))
print(md.read_text().split("## Module Graph", 1)[1])
EOF

# Then open /tmp/graphlm-demo/GRAPH.html (needs network for D3) and try the
# Layers checkboxes; push /tmp/graphlm-demo/GRAPH.md to any GitHub repo to
# see the Mermaid block render.
```

A real run (`graphlm .`) produces the same sections with the LLM's prose
alongside; `--no-ast` switches the Mermaid source to the LLM edges and the
HTML loses the parser layer (the toggle stays, with nothing to hide).

## Verified

- `uv run pytest -q` → 440 passed (404 before; 36 new). `uv run mypy graphlm
  --ignore-missing-imports` clean. `mermaid.py` and `html_render.py` at 100%
  line coverage.
- Both generated Mermaid blocks (the `cyclic_project` fixture and graphlm's
  own tree) parse under real Mermaid 11 (`mermaid.parse` → `flowchart-v2`) in
  headless Chrome.
- The generated `GRAPH.html` for `cyclic_project`, driven in headless Chrome:
  4 AST links drawn, 3 red rings = 3 cycle members, stats line
  `4 nodes, 4 edges (4 parser, 0 LLM, 0 data flow), 1 import cycle`, unticking
  "Parser imports" hides all 4 links and re-ticking restores them, zero JS
  errors.

## What's stubbed / deliberately left out

- No Mermaid rendering in `GRAPH.html` — it stays D3. Mermaid is for the
  Markdown; the HTML already has a force layout.
- No file-level Mermaid option. Directory-level is the only mode; a file-level
  flag (`--mermaid-files`) is an obvious next knob if someone wants it for a
  small repo.
- The `GRAPH_DIFF` is unchanged — the Mermaid block is derived from fields the
  diff already compares, so nothing new to diff.
- The pass-2 prompt is unchanged: nothing here is LLM-emitted.

## Next increments

- A CLI flag for the node cap (`--mermaid-max-nodes`) and a file-level mode.
- Draw the LLM-vs-parser *disagreements* explicitly in the HTML (an LLM edge
  the parser did not find is already visually distinct; an edge the parser
  found that the LLM missed could get a "not corroborated" style).
- Once the JS/TS pack (#42) lands, the Mermaid block gets those edges for free
  — it reads `deterministic_edges`, not a language.
