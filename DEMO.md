# DEMO — Interactive HTML Visualization (Innovation #2)

## What works

- `graphlm/html_render.py` — D3.js force-directed graph visualization
- `graphlm/_html_template.html` — Self-contained HTML template with zoom/pan, search, dark mode

The visualization initializes on page load: zoom/pan, node search, and theme toggle are ready without extra setup.

## How to try

```bash
graphlm /path/to/project -o ./output
# Open output/GRAPH.html in a browser
```

Pass `--no-html` to skip writing `GRAPH.html`.

## Status

Working. Tests live under `tests/` — run `uv run pytest`.
