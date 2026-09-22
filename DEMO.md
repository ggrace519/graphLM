# DEMO — innovation #1: semantic `find` for `graphlm --serve`

The `--serve` MCP map answers "where is X?" — but its `find` was a token/substring
matcher. This adds **`search`**: an agent asks a natural-language question and Jev
ranks modules by *meaning*, not token overlap. It is the first graphlm Jev call at
**query time** rather than graph-generation time.

## What works (verified)

- `graphlm.evidence.score_relevance(candidates, query, ...)` — a Jev Noul per module
  ("is this the module you'd open to do/understand `<query>`?"), batched ~15/request,
  gated + never-raises + injectable client.
- `graphlm.query.semantic_find(index, query, ...)` — ranks modules, returns
  `{available, hits:[{path, name, relevance, description}], total}`. Returns
  `available: False` (never raises) when Jev is off, so callers fall back to `find`.
- New MCP tool **`search`** in `graphlm.mcp_server`, alongside the eight zero-LLM
  tools. Reads `TYPESAFE_API_KEY`; when Jev is unavailable it transparently falls
  back to token `find` and adds a `note` saying so.

**Live proof** (graphlm's own map, real Jev). Query: *"which module talks to the
LLM / makes the API calls?"*

| tool | top result |
|---|---|
| `search` (Jev) | **`graphlm/llm.py` — relevance 0.98** ✓ (the actual LLM client) |
| `find` (tokens) | `graphlm/__init__.py` first; `llm.py` buried at #2 behind a false hit |

The semantic version put the correct module first with high confidence; the token
version led with a worse match.

## How to run it

Needs the map + the TypeSafe extra + a key:

```bash
uv sync --group dev --extra mcp --extra typesafe
# ensure TYPESAFE_API_KEY is in ~/.config/graphlm/.env (or exported)
graphlm .                       # generate .graphlm/GRAPH.json for the target repo
```

Programmatically:

```python
from pathlib import Path
from graphlm.query import build_index, load_map, semantic_find
import os
idx = build_index(load_map(Path(".graphlm/GRAPH.json")))
res = semantic_find(idx, "which module handles rate limiting?",
                    api_key=os.environ["TYPESAFE_API_KEY"])
for h in res["hits"][:5]:
    print(h["relevance"], h["path"])
```

Over MCP, the tool is `search(question, limit=10)` — register the server with
`claude mcp add graphlm -- graphlm --serve /path/to/repo` and call `search`.

## Tests

No-network (injected fake Jev client), same discipline as the rest of `evidence.py`:

```bash
uv run pytest tests/test_query.py::TestSemanticFind \
              tests/test_evidence.py::TestScoreRelevance \
              tests/test_mcp_server.py::TestSearchTool -q
```

Full suite: **974 passed, 8 skipped**; mypy clean; 98% `evidence.py` / 99% `query.py`.

## What's stubbed / limits

- Nothing is stubbed — the Jev call is real, only the *tests* inject a fake client.
- Latency: one batched Jev round per query on the agent hot path (~seconds). A miss
  falls back to `find` instantly. A per-`(query, map-mtime)` cache is the obvious
  next increment but isn't built.
- Ranks **modules** only (the unit an agent navigates to). Ranking individual
  symbols/functions is a possible extension.

## Next increment

Cache results per `(query, map mtime)` so repeated questions in a session are free;
optionally widen candidates from modules to `file_summaries` for finer targets.

## Branch note

Built on `feat/module-importance` (the Jev surface + the #170 directory-degree fix
live there). Lands after that branch merges to `develop`.
