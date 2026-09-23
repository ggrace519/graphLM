"""Filesystem safety guards for the scanner — symlink escape, nested checkouts,
and reading the project's ``.graphlmignore`` safely.

Split out of ``scanner.py`` (600-line limit). Groups the "is this path safe to
follow / read?" concerns: a symlink that hides a sensitive target, a child dir
that is really another git checkout, project containment, and the ignore-file
reader (which is a safe file read — it rejects an escaping symlink and never
raises — not a pattern matcher, so it lives here beside ``_path_is_inside``).

Imports `exclusions` (`_ALWAYS_EXCLUDE`) and `redact` (`_is_sensitive_file`);
`scanner → scan_guards → exclusions → freshness → models` has no cycle.
"""

from __future__ import annotations

import fnmatch
import logging
from pathlib import Path

from graphlm.exclusions import _ALWAYS_EXCLUDE
from graphlm.redact import _is_sensitive_file

logger = logging.getLogger(__name__)


def _symlink_hides_sensitive(
    path: Path, exclude: tuple[str, ...] | None = None
) -> bool:
    """True when ``path`` is a symlink to a never-read file or excluded tree.

    Guards inspect the *link name*; ``read_text`` follows the target, so
    ``crypto.py → .ssh/id_rsa`` used to send the key body to the LLM, and
    ``config.yaml → secrets/prod.yaml`` still would when ``secrets`` is
    only in ``.graphlmignore``.
    """
    if not path.is_symlink():
        return False
    try:
        target = path.resolve()
    except OSError:
        return True
    if _is_sensitive_file(target):
        return True
    pats = exclude if exclude is not None else tuple(_ALWAYS_EXCLUDE)
    for part in target.parts:
        for pat in pats:
            if fnmatch.fnmatch(part, pat):
                return True
    return False


def _is_nested_checkout(dir_path: Path) -> bool:
    """True if ``dir_path`` is the root of another git checkout.

    A git worktree or submodule marks its root with a ``.git`` *file* (a
    pointer into the parent's gitdir), a vendored clone with a ``.git``
    directory; ``exists()`` covers both. Such a subtree is a different project
    — merging it into the parent's map duplicates every module and edge under a
    second prefix (observed with agent worktrees under ``.claude/worktrees/``
    and would equally hit submodules). The scan root itself is never tested
    here (only children are), so scanning a repo is unaffected.
    """
    try:
        return (dir_path / ".git").exists()
    except OSError:
        return False


def _path_is_inside(project_dir: Path, target: Path) -> bool:
    """Check if target path is inside (or equal to) project_dir.

    Handles symlinks by resolving the parent of each path component,
    which prevents symlink traversal attacks.
    """
    try:
        # Resolve both paths
        project_resolved = project_dir.resolve()
        target_resolved = target.resolve()
        # Check containment via commonpath
        common = str(project_resolved)
        return str(target_resolved).startswith(common + "/") or str(target_resolved) == common
    except (ValueError, OSError):
        return False


def load_graphlmignore(project_dir: Path) -> tuple[str, ...]:
    """Patterns from ``.graphlmignore`` (gitignore-lite). Missing → ``()``.

    One glob per line; ``#`` comments and blanks skipped; trailing ``/``
    stripped so ``.godot/`` matches the ``.godot`` path component. Never
    raises — unreadable / non-UTF-8 / escaping-symlink files are skipped.
    """
    path = project_dir / ".graphlmignore"
    try:
        if path.is_symlink() and not _path_is_inside(project_dir, path):
            return ()
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ()
    except (OSError, UnicodeDecodeError):
        logger.warning("Could not read %s; ignoring it", path)
        return ()
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.rstrip("/")
        if line:
            out.append(line)
    return tuple(out)
