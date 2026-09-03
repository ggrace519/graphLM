# DEMO — Serve the map to agents over MCP (Innovation #1)

## What works

- `graphlm/query.py` — pure query layer over a `CodebaseGraph`: unified edge
  index (AST ∪ LLM, labelled `ast`/`llm`/`both`), fuzzy path resolution,
  `overview`, `module_info`, `neighbors`, `dependents` (BFS blast radius with a
  cap), `find` (ranked search across quick-reference / modules / entry points /
  symbols / summaries), `cycles`, `entry_points`, `staleness`, `load_map`.
- `graphlm/mcp_server.py` — stdio MCP server (SDK v2) registering the eight
  tools; reloads `GRAPH.json` on mtime change; unreadable map → `ToolError`.
- `graphlm --serve [PROJECT_DIR] [-o DIR]` — CLI entry; map-exists check before
  the `mcp` import; clear exit-2 messages for "no map" and "no extra".
- `pyproject.toml` — `mcp` optional extra; CI installs it.
- `--install-skill` guide — tells the agent to prefer the MCP tools when present.

## How to try it

```bash
uv sync --group dev --extra mcp
uv run graphlm .                                   # generate the map (needs the LLM endpoint)
claude mcp add graphlm -- uv run --directory "$PWD" graphlm --serve "$PWD"
# then in Claude Code: "use the graphlm tools to tell me who imports scanner.py"
```

Or drive it from Python with the SDK's in-memory client:

```python
import anyio
from pathlib import Path
from mcp.client import Client
from graphlm.mcp_server import build_server

server = build_server(Path("."), Path(".graphlm/GRAPH.json"))
async def go():
    async with Client(server) as c:
        print((await c.call_tool("neighbors", {"path": "scanner.py"})).structured_content)
anyio.run(go)
```

## What's stubbed

Nothing. Serving never calls the LLM; it only reads the generated JSON.

## Next increment

- `resources`: expose `GRAPH.md` sections as MCP resources so an agent can pull
  the data-flow table on demand.
- A `search_code` bridge is deliberately **not** included — agents already have
  file tools; the map's value is the curated structure.
- Once innovation #3 (PageRank) lands, `overview.most_imported` can become a
  real centrality ranking instead of raw in-degree.
