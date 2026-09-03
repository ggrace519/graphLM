"""MCP transport for the map queries — ``graphlm --serve``.

A stdio Model Context Protocol server that exposes ``graphlm/query.py`` as
typed tools, so a coding agent (Claude Code, Codex, Cursor, …) can ask the map
"who imports X?" for a few hundred tokens instead of reading the whole
``GRAPH.md``. Zero LLM calls, zero network: every tool is a pure function over
the already-generated ``GRAPH.json``.

Design notes:

- **All logic lives in ``query.py``.** This module only registers tools and
  runs the transport, so the (fast-moving, v2 as of this writing) ``mcp`` SDK
  surface is disposable and the queries stay testable without the extra.
- **The ``mcp`` package is an optional extra** (``graphlm[mcp]``); importing
  this module without it raises ``ImportError``, which the CLI turns into an
  install hint. Nothing else in graphlm imports it.
- **The map is re-read when ``GRAPH.json`` changes on disk** (mtime check per
  call), so a regeneration mid-session is picked up without restarting the
  server. A missing or corrupt map surfaces as a tool error with the
  ``graphlm .`` hint, never a crash of the server process.
- **stdout is the protocol channel.** Never print to stdout here; logging goes
  to stderr.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Optional

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from graphlm import query
from graphlm.query import MapIndex, MapUnavailable, build_index, load_map

logger = logging.getLogger(__name__)

SERVER_NAME = "graphlm"

_INSTRUCTIONS = """\
graphlm serves a generated *map* of this codebase: modules, import edges
(parser-proven and LLM-inferred, labelled), data flow, entry points, import
cycles, and "where is X?" answers. Prefer these tools over reading
.graphlm/GRAPH.md — they answer one question in a few hundred tokens.
Start with `overview`, then `find` / `module` / `neighbors` / `dependents`.
The map is advisory: trust the code over the map when they disagree, and call
`staleness` to see whether the repo has moved on since it was generated.
"""


class MapCache:
    """Load ``GRAPH.json`` lazily and reload it whenever the file changes.

    The mtime (ns) is checked on every access — a stat is microseconds, and it
    means a ``graphlm .`` run in another terminal is reflected in the next tool
    call without restarting the server.
    """

    def __init__(self, json_path: Path) -> None:
        self.json_path = json_path
        self._index: Optional[MapIndex] = None
        self._mtime_ns: Optional[int] = None

    def index(self) -> MapIndex:
        try:
            mtime_ns = self.json_path.stat().st_mtime_ns
        except OSError:
            self._index = None
            self._mtime_ns = None
            raise MapUnavailable(
                f"no map at {self.json_path} — run `graphlm .` from the project root first"
            )
        if self._index is None or mtime_ns != self._mtime_ns:
            logger.info("loading map from %s", self.json_path)
            self._index = build_index(load_map(self.json_path))
            self._mtime_ns = mtime_ns
        return self._index


def build_server(project_dir: Path, json_path: Path) -> MCPServer:
    """Create the MCP server with every map tool registered.

    ``project_dir`` is only used by ``staleness`` (to read the current git
    ``HEAD``); the map itself is read from ``json_path``.
    """
    cache = MapCache(json_path)
    server = MCPServer(SERVER_NAME, instructions=_INSTRUCTIONS)

    def index() -> MapIndex:
        # An unreadable map is an *anticipated* failure: ToolError hands the
        # message (with the `graphlm .` hint) to the model as an is_error
        # result. Any other exception would be masked by the SDK as a bare
        # "Error executing tool" the agent can't act on.
        try:
            return cache.index()
        except MapUnavailable as e:
            raise ToolError(str(e)) from e

    @server.tool()
    def overview() -> dict[str, Any]:
        """Counts, provenance, most-imported files, entry points, and the
        architecture notes of the mapped codebase. Call this first."""
        return query.overview(index())

    @server.tool()
    def module(path: str) -> dict[str, Any]:
        """Everything the map knows about one file: module description, summary,
        public symbols, entry points, import counts, cycle membership, and
        quick-reference entries pointing at it. Accepts a full path or a unique
        suffix such as `cli.py`."""
        return query.module_info(index(), path)

    @server.tool()
    def neighbors(path: str, direction: str = "both") -> dict[str, Any]:
        """Direct import neighbors of a file: what it imports (`imports`) and what
        imports it (`imported_by`). Each edge says its `source`: `ast`
        (parser-proven), `llm` (inferred), or `both`. `direction` is `both`,
        `out`, or `in`."""
        return query.neighbors(index(), path, direction)

    @server.tool()
    def dependents(path: str, transitive: bool = False, limit: int = 200) -> dict[str, Any]:
        """Blast radius: files that import `path` (direct), or with
        `transitive=true` every file that reaches it through imports, each with
        its shortest distance. Capped at `limit` results."""
        return query.dependents(index(), path, transitive=transitive, limit=limit)

    @server.tool()
    def find(query_text: str, limit: int = 20) -> dict[str, Any]:
        """Search the map for a phrase — "where is the app factory", a symbol
        name, a module name. Ranked hits across quick-reference entries, modules,
        entry points, symbols, and file summaries."""
        return query.find(index(), query_text, limit=limit)

    @server.tool()
    def cycles() -> dict[str, Any]:
        """Import cycles (strongly connected components) with risk scores,
        highest risk first."""
        return query.cycles(index())

    @server.tool()
    def entry_points() -> dict[str, Any]:
        """Every known entry point: main functions, routes, CLI commands, hooks,
        plugins, factories."""
        return query.entry_points(index())

    @server.tool()
    def staleness() -> dict[str, Any]:
        """Whether the map is fresh: compares the commit it was generated
        against with the repo's current HEAD. `stale` or `unknown` means
        regenerate with `graphlm .` before trusting fine details."""
        return query.staleness(index(), project_dir)

    return server


def run_server(project_dir: Path, json_path: Path) -> None:
    """Serve the map over stdio until the client disconnects.

    Logging is routed to stderr because stdout carries the MCP protocol.
    """
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(message)s")
    server = build_server(project_dir, json_path)
    logger.info("graphlm MCP server: serving %s (stdio)", json_path)
    server.run("stdio")
