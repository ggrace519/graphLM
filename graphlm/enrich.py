"""Post-pass-2 local enrichment helpers filled onto the graph / its meta stamp.

Split out of ``__init__.py`` (600-line limit). These are the small, pure(-ish)
functions ``generate_graph`` calls *after* the paid pass-2 LLM call to build the
provenance stamp, account token usage, and (when Jev is on) score file-level
importance. They are **not** LLM-emitted. The public entry points
(``generate_graph``, ``GraphResult``, ``WriteResult``) stay in ``__init__.py``.
"""

from __future__ import annotations

from pathlib import Path

from graphlm.models import (
    CodebaseGraph,
    FileImportance,
    GraphMeta,
    ImportEdge,
    PassUsage,
)
from graphlm.provenance import git_commit_sha, graphlm_version, now_utc_iso


def is_directory_granular(graph: CodebaseGraph) -> bool:
    """True when the LLM described modules at directory (not file) granularity.

    A module path is a directory when its final segment has no file extension. On a
    large repo the LLM emits packages (``src/pkg/sub``); on small/medium repos it
    emits files (``src/pkg/mod.py``). We treat the graph as directory-granular when
    *most* module paths are directories, so a stray extensionless file among real
    file modules doesn't flip a file-granular graph onto the file-importance path.
    """
    mods = graph.modules
    if not mods:
        return False
    dir_like = sum(1 for m in mods if "." not in m.path.replace("\\", "/").rsplit("/", 1)[-1])
    return dir_like > len(mods) / 2


def score_file_importance(
    graph: CodebaseGraph,
    edges: list[ImportEdge],
    *,
    api_key: str | None,
    summaries_by_path: dict[str, str],
    evidence,  # the graphlm.evidence module (passed to avoid a re-import)
    client=None,  # injectable Jev client (tests pass a fake; None → real)
) -> "list[FileImportance] | None":
    """Score file-level importance over file_summaries → sorted FileImportance list.

    Builds file "modules" from ``file_summaries`` (always file-level), reuses
    ``score_importance`` for the Jev role, fuses with per-file degree the same way
    ``render._fused_importance`` does, and returns the files sorted most load-bearing
    first. ``None`` when Jev is off or there are no summaries. Never raises past the
    caller's guard.
    """
    summaries = graph.file_summaries
    if not summaries:
        return None

    class _FileMod:
        __slots__ = ("path", "description")

        def __init__(self, path: str, description: str) -> None:
            self.path = path
            self.description = description

    norm = evidence._norm
    file_mods = [_FileMod(norm(s.path), s.summary) for s in summaries]
    roles = evidence.score_importance(
        file_mods, edges, api_key=api_key, summaries_by_path=summaries_by_path,
        client=client,
    )
    if roles is None:
        return None

    degree = evidence.file_degree(edges)
    scored = [(p, roles[p], degree.get(p, 0)) for _m in file_mods if (p := _m.path) in roles]
    if not scored:
        return None
    # Rank-normalise degree, blend 0.6*role + 0.4*degree (render's weighting).
    degs = sorted({d for _p, _r, d in scored})
    dmax = len(degs) - 1
    drank = {d: (i / dmax if dmax else 1.0) for i, d in enumerate(degs)}
    out = [
        FileImportance(
            path=p, role=r, degree=d, fused=round(0.6 * (r / 3.0) + 0.4 * drank[d], 4)
        )
        for p, r, d in scored
    ]
    out.sort(key=lambda fi: (-fi.fused, fi.path))
    return out


def build_meta(project_path: Path) -> GraphMeta:
    """Build the provenance stamp for a run against ``project_path``.

    Failure-tolerant throughout: a non-git project yields ``commit_sha=None``,
    a non-installed checkout yields ``graphlm_version=None``. Never raises.
    """
    return GraphMeta(
        created_at=now_utc_iso(),
        commit_sha=git_commit_sha(project_path),
        graphlm_version=graphlm_version(),
    )


def pass_usage(usage: dict[str, object] | None, estimated: int) -> PassUsage:
    """Build one pass's ``PassUsage`` from the server's raw ``usage`` dict.

    The dict is untrusted telemetry from the endpoint: a missing key, a
    non-int (some servers emit floats or strings), or ``None`` all read as
    "not reported" rather than raising — the run must never fail on
    accounting. ``bool`` is excluded explicitly because it is an ``int``
    subclass and ``true`` would otherwise stamp as ``1``.
    """

    def _int(key: str) -> int | None:
        value = usage.get(key) if usage else None
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value

    return PassUsage(
        prompt_tokens=_int("prompt_tokens"),
        completion_tokens=_int("completion_tokens"),
        estimated_prompt_tokens=estimated,
    )
