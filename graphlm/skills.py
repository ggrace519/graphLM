"""Install an agent guide that teaches a coding harness to use graphlm.

``graphlm --install-skill <harness>`` drops a small guide telling a coding agent
(Claude Code, Codex, …) two things: *how to run graphlm*, and *to read
``.graphlm/GRAPH.md`` when it starts working in a codebase* (regenerating the map
with ``graphlm .`` when it is missing or stale).

Design constraints (see ADR-003):

- **Never edit a file graphlm didn't create.** We only ever *create* graphlm's
  own files. For a harness whose config is a user-owned instruction file
  (Codex's ``AGENTS.md``), we write a standalone guide and *print* a one-line
  snippet for the user to include themselves — we don't append to their file.
- **Idempotent.** Skip if the target already exists, unless ``force=True``.
- **User-global by default**, project-local on request.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Supported harness identifiers (for the CLI's error message and validation).
SUPPORTED_HARNESSES = ("claude", "codex")


@dataclass
class SkillInstallResult:
    """Outcome of an ``--install-skill`` run."""

    harness: str
    path: Path
    #: True when the file already existed and was left untouched (no --force).
    skipped: bool
    #: A message to print for the user (e.g. how to wire a Codex guide into
    #: their own AGENTS.md). ``None`` when there's nothing extra to say.
    note: str | None = None


def _skill_markdown_body() -> str:
    """The guide's Markdown body — shared by every harness.

    Written to no-op gracefully in a repo that has no map yet (it tells the
    agent to generate one), so a user-global install doesn't misfire in
    unmapped repos.
    """
    return """\
## Use graphlm's codebase map

[graphlm](https://github.com/ggrace519/graphLM) generates a **map of a
codebase** — modules, import/dependency edges, data flow, entry points, import
cycles, and "where do I find X?" answers — as Markdown, JSON, and interactive
HTML.

**When you start working in a repository, look for a graphlm map before
exploring the code by hand:**

1. **Check for `.graphlm/GRAPH.md`** in the project root. If it exists, read it
   first — it orients you far faster than opening files one at a time. The
   machine-readable form is `.graphlm/GRAPH.json`; the clickable graph is
   `.graphlm/GRAPH.html`.
2. **Follow the map's refresh directive.** `GRAPH.md` opens with a provenance
   stamp naming the git commit it was generated against. Compare it to the
   repo's current `git rev-parse HEAD`; if they differ, the map may be stale —
   regenerate it with `graphlm .` from the project root.
3. **If there is no `.graphlm/GRAPH.md`,** and graphlm is installed and the
   project is nontrivial, generate one: `graphlm .` (writes into `.graphlm/`).
   If graphlm isn't installed or you can't reach its LLM endpoint, just skip
   this — it's an optional aid, not a requirement.
4. **What changed since last time?** `.graphlm/GRAPH_DIFF.md` lists the modules,
   edges, and cycles added/removed since the previous run — a fast way to see
   structural drift without re-reading the whole map.

Notes:
- The map is **advisory** and best-effort. Trust the code over the map when they
  disagree; a stale map is possible (regenerate to be sure).
- graphlm needs an OpenAI-compatible LLM endpoint (`GRAPHLM_BASE_URL` /
  `GRAPHLM_API_KEY` / `GRAPHLM_MODEL`); `graphlm .` will tell you if it's not
  configured. `graphlm --help` lists every flag.
"""


def _claude_skill_file(body: str) -> str:
    """A Claude Code skill: frontmatter (name/description) + the shared body."""
    frontmatter = (
        "---\n"
        "name: graphlm\n"
        "description: >-\n"
        "  Read and refresh the graphlm codebase map (.graphlm/GRAPH.md) when working in "
        "a repository. Use when orienting in an unfamiliar codebase, before exploring "
        "files by hand, or when you need modules / import edges / entry points / import "
        "cycles at a glance. Regenerate a missing or stale map with `graphlm .`.\n"
        "---\n\n"
        "# graphlm codebase map\n\n"
    )
    return frontmatter + body


def _codex_guide_file(body: str) -> str:
    """A standalone Codex guide (plain Markdown, no frontmatter)."""
    return "# graphlm codebase map\n\n" + body


def _base_dir(project_dir: Path, local: bool, home: Path) -> Path:
    """Root under which the harness config dir lives."""
    return project_dir if local else home


def _claude_target_path(base: Path) -> Path:
    # Claude Code skills live under <base>/.claude/skills/<name>/SKILL.md, for
    # both the global (~) and project-local conventions.
    return base / ".claude" / "skills" / "graphlm" / "SKILL.md"


def _codex_target_path(base: Path, local: bool) -> Path:
    if local:
        return base / "graphlm-agent.md"
    return base / ".codex" / "graphlm.md"


def _codex_note(path: Path, local: bool) -> str:
    """How to wire the standalone Codex guide into the user's AGENTS.md.

    Codex reads AGENTS.md files (root-down, one per directory) and has no
    arbitrary-file include directive, so we tell the user to paste a pointer
    into their own AGENTS.md rather than editing it for them.
    """
    if local:
        agents = "AGENTS.md (in this project)"
    else:
        agents = "~/.codex/AGENTS.md (global)"
    return (
        f"Wrote the Codex guide to {path}.\n"
        f"Codex won't read it automatically. To activate it, add a pointer to "
        f"your own {agents}, e.g.:\n\n"
        f"    ## graphlm\n"
        f"    See {path} — read `.graphlm/GRAPH.md` when working in a repo and\n"
        f"    regenerate it with `graphlm .` when missing or stale.\n\n"
        f"(graphlm won't edit your AGENTS.md for you.)"
    )


def install_skill(
    harness: str,
    *,
    project_dir: Path | None = None,
    local: bool = False,
    force: bool = False,
    home: Path | None = None,
) -> SkillInstallResult:
    """Install the graphlm agent guide for ``harness``.

    Args:
        harness: ``"claude"`` or ``"codex"``.
        project_dir: the scanned project; required when ``local=True``.
        local: write into the project instead of the user-global config dir.
        force: overwrite an existing guide instead of skipping it.
        home: base home dir (injectable for tests); defaults to ``Path.home()``.

    Returns a :class:`SkillInstallResult`. A pre-existing *regular* file is
    reported as ``skipped=True`` (not raised). Raises ``ValueError`` for an
    unknown harness, for ``local=True`` without a ``project_dir``, and when the
    target path is a symlink (graphlm won't write through it — #33).
    """
    if harness not in SUPPORTED_HARNESSES:
        raise ValueError(
            f"unknown harness {harness!r}; supported: {', '.join(SUPPORTED_HARNESSES)}"
        )
    if local and project_dir is None:
        raise ValueError("local install requires a project_dir")

    home = home if home is not None else Path.home()
    base = _base_dir(project_dir or Path.cwd(), local, home)
    body = _skill_markdown_body()

    if harness == "claude":
        path = _claude_target_path(base)
        content = _claude_skill_file(body)
        note = None
    else:  # codex
        path = _codex_target_path(base, local)
        content = _codex_guide_file(body)
        note = _codex_note(path, local)

    # Refuse to write *through* a symlink at the target — the write would land on
    # whatever the link resolves to, clobbering a file graphlm didn't create
    # (e.g. a dotfiles-managed ~/.claude/skills/), violating this module's
    # contract. `is_symlink()` catches broken links too (which `.exists()` would
    # report as absent and let the no-force path fall through to a write). #33
    if path.is_symlink():
        raise ValueError(
            f"refusing to write through a symlink at {path} — graphlm won't "
            f"overwrite a file it didn't create. Remove the symlink and re-run."
        )

    if path.exists() and not force:
        return SkillInstallResult(harness=harness, path=path, skipped=True, note=note)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return SkillInstallResult(harness=harness, path=path, skipped=False, note=note)
