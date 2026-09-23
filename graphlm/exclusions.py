"""Path-exclusion patterns and matching — what the scanner skips by name.

The always-excluded set (`_ALWAYS_EXCLUDE`) and the fnmatch-based matcher
(`_should_exclude`), split out of `scanner.py` (600-line limit). A leaf module:
imports only stdlib + `freshness.STATE_FILENAME` (the one working-copy name), so
`scanner → scan_guards → exclusions → freshness → models` has no cycle.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

from graphlm.freshness import STATE_FILENAME

# Patterns that are always excluded (in addition to user-specified ones)
_ALWAYS_EXCLUDE = {
    ".git",
    ".svn",
    ".hg",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".hypothesis",  # Hypothesis example DB — thousands of cache files
    ".tox",
    ".eggs",
    "*.egg-info",
    "node_modules",
    ".venv",
    "venv",
    "env",
    ".env",
    ".gitignore",
    ".gitkeep",
    ".graphlmignore",  # the ignore file itself — never sent to the LLM (#38)
    # Build / dist / cache output. These match on any path component, so a
    # legitimately-named source dir called "build"/"dist"/"target" anywhere in
    # the tree is also excluded — an accepted trade-off (precedent: bare "env"
    # above already excludes any component named env). They only remove files
    # from analysis; no security invariant depends on them. Together with the
    # per-directory tree cap, this keeps huge polyglot repos (Rust target/,
    # JS build/, hypothesis caches) from overflowing the LLM context (#17).
    "target",  # Rust/Java build output (crates/*/target/... is thousands of files)
    "build",
    "dist",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".terraform",
    ".gradle",
    "coverage",
    "htmlcov",
    ".idea",
    ".vscode",
    # graphlm's own output directory. The CLI writes GRAPH.* / GRAPH_DIFF.* into
    # a `.graphlm/` subdir of the scanned project by default, so excluding the
    # whole directory keeps graphlm from ingesting its own map (and diff, #28) as
    # source on a re-run. `_should_exclude` matches any path component, so this
    # drops `.graphlm/` and everything under it in one entry.
    ".graphlm",
    # graphlm's own output artifacts *by filename*, for the case where output is
    # redirected into the scanned tree with `-o` (or a library caller writes to
    # the project root) rather than the default `.graphlm/` dir. Named explicitly
    # (not a broad GRAPH*) so a user's GRAPHICS.md etc. is untouched.
    # NOTE: these are the *default* suffix ("GRAPH") only. write_outputs accepts
    # custom *_suffix / diff_suffix params, so a library caller writing e.g.
    # `map.json` / `map_DIFF.json` and then re-scanning that dir would re-ingest
    # them. Not reachable today (the CLI exposes no suffix flag), so it's not
    # live — but if a `--json-suffix` / `--diff-suffix` flag is ever added, make
    # this exclusion suffix-aware (or the self-ingestion bug reopens for it).
    "GRAPH.md",
    "GRAPH.json",
    "GRAPH.html",
    "GRAPH_DIFF.md",
    "GRAPH_DIFF.json",
    # graphlm's internal JSON working copy — always written for the diff baseline
    # / --serve, so exclude it from a re-scan the same way as the deliverables.
    # Sourced from the single definition in freshness.py (not a hardcoded copy).
    STATE_FILENAME,
}


def _should_exclude(rel_path: str, exclude_patterns: tuple[str, ...]) -> bool:
    """Check if a relative path matches any exclusion pattern."""
    parts = Path(rel_path).parts
    for pattern in exclude_patterns:
        # Match against the full relative path
        if fnmatch.fnmatch(rel_path, pattern):
            return True
        # Match against individual path components
        for part in parts:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False
