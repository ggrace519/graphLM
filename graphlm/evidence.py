"""LLM-prose-vs-source evidence-support score (TypeSafe/Jev).

graphlm can vouch for its *edges* (``faithfulness.py`` compares the LLM's
``import_edges`` to the AST ground truth) but nothing checks its *prose*: the
``file_summaries`` the model wrote. This module scores each summary against the
**source the model actually saw** — the redacted / skeletonised / truncated
``FileFragment.content`` from pass 2, not the file on disk — with a TypeSafe
System-One Noul: "does this claim correctly identify the file's role and the
symbols it defines?" The probabilities are a downstream-trust **weight**, the
same idea as ``faithfulness``: a low score means the claim outruns its evidence,
which happens honestly when the fragment was skeletonised (bodies elided) or
truncated, and dishonestly when the model invented a symbol.

Everything here is best-effort and **never raises past its own boundary**. It
runs in ``generate_graph`` *after* the paid pass-2 call — an escaping exception
would discard the finished graph — so every failure path returns ``None`` (which
reads as "not scored", never "scored zero"). It is also **off** unless it is
safe and wanted: redaction must be on (TypeSafe is a different third party than
graphlm's own LLM endpoint, so unredacted source must not reach it), a
``TYPESAFE_API_KEY`` must be present, and the ``typesafe-sdk`` optional extra
(``graphlm[typesafe]``) must be importable. The SDK import is function-local so a
base install without the extra never fails at module import; nothing outside this
module imports ``typesafe_sdk``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from typing import Any

from graphlm.models import EvidenceSupport, FileScore, FileSummary

# Summaries scoring below this are surfaced as low outliers (a reader-facing
# "look here" list, not a hard threshold — the raw mean is also reported).
_LOW_THRESHOLD = 0.5
# Files per TypeSafe request. Each carries its own CLAIM+SOURCE in the question's
# instructions over a shared state; ~15 kept one request well inside the input
# budget in testing (≈14k input tokens/request).
_BATCH = 15
# A summary whose source has fewer than this many non-whitespace bytes is not
# scored: there is nothing substantive to verify a claim against. An empty
# ``__init__.py`` (a bare docstring) or a thin entry point (``from x import
# main`` then ``main()``) defines nothing, so the support Noul — "do the named
# symbols match the SOURCE?" — has no signal and returns a meaningless ~0.2 no
# matter how accurate the summary is. Measured: the two such files in the tetris
# fixture are 21 and 72 stripped bytes; the smallest real file that scores well
# is ~168, and substantive modules are 1000+. Scoring a claim against near-empty
# evidence is unfalsifiable by construction, so those files are *skipped* (like a
# missing pass-2 fragment), never counted as weakly supported.
_MIN_EVIDENCE_CHARS = 64

# The validated SOFT Noul: it keeps strong discrimination (a mismatched file or
# an invented symbol scores ~0.05) while tolerating the unverifiable detail that
# a skeletonised fragment legitimately can't confirm.
_INSTRUCTIONS = (
    "The CLAIM describes the SOURCE file. Using only the SOURCE as evidence, does "
    "the CLAIM correctly identify the file's main role and the symbols it actually "
    "defines? Minor unverifiable detail is acceptable; a wrong role or an invented "
    "symbol is not."
)
_TRUE = "The main role and the named defined symbols match the SOURCE."
_FALSE = (
    "The stated role is wrong, or the CLAIM names symbols the SOURCE does not define."
)


def _norm(path: str) -> str:
    """Forward slashes, no leading ``./`` — match FileFragment.rel_path spelling."""
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def _claim(summary: FileSummary) -> str:
    """Flatten a summary into a single checkable claim string."""
    parts = [summary.summary]
    for sym in summary.symbols:
        parts.append(f"Defines {sym.kind} `{sym.name}`: {sym.description}")
    return "\n".join(p for p in parts if p)


def score(
    file_summaries: Sequence[FileSummary],
    pass2_files: Iterable[Any],
    *,
    redact_secrets: bool,
    api_key: str | None,
    client: Any | None = None,
    timeout: float = 60.0,
) -> EvidenceSupport | None:
    """Score each summary's support against the pass-2 source the model saw.

    Returns ``None`` (not scored) when scoring is off or impossible:

    * ``redact_secrets is False`` — TypeSafe is a third party; do not send it
      source that redaction was told to leave intact;
    * ``api_key`` is empty — no credential;
    * ``file_summaries`` is empty — nothing to score;
    * no summary maps to a pass-2 fragment — every summary would be skipped;
    * the ``typesafe-sdk`` extra is not installed, or any SDK error occurs.

    ``client`` is injectable (a live ``TypeSafeClient`` is constructed when
    ``None``) so the test suite runs with a fake and no network. Never raises.

    A summary whose file was **not** in ``pass2_files`` is *skipped*, not scored:
    it was written from the directory tree alone, so its evidence set is empty and
    scoring it against content the model never received would manufacture a pass.
    """
    if not redact_secrets or not api_key or not file_summaries:
        return None

    # The evidence set: only files the model actually saw in pass 2.
    content_by_path = {_norm(frag.rel_path): frag.content for frag in pass2_files}

    to_score: list[tuple[str, str, str]] = []  # (path, claim, source)
    skipped = 0
    for summ in file_summaries:
        source = content_by_path.get(_norm(summ.path))
        # Skip a summary with no pass-2 fragment (tree-only), and one whose source
        # is too thin to verify a claim against (an empty __init__ / a bare entry
        # point defines nothing — see _MIN_EVIDENCE_CHARS). Both are "no evidence
        # to compare", counted in `skipped`, never scored as weakly supported.
        if source is None or len(source.strip()) < _MIN_EVIDENCE_CHARS:
            skipped += 1
            continue
        to_score.append((_norm(summ.path), _claim(summ), source))

    if not to_score:
        # Every summary was tree-only — nothing to score, but this is a real
        # "ran and found nothing to compare" state; report it, don't fake a mean.
        return EvidenceSupport(mean=None, scored=0, skipped=skipped, low=[])

    try:
        results = _run(to_score, api_key=api_key, client=client, timeout=timeout)
    except Exception as e:  # SDK missing, network, auth, malformed response — all None
        logging.debug("Evidence scoring unavailable, skipping: %s", e)
        return None

    scored = len(results)
    mean = sum(s for _, s in results) / scored if scored else None
    low = sorted(
        (FileScore(path=p, score=s) for p, s in results if s < _LOW_THRESHOLD),
        key=lambda fs: fs.score,
    )
    return EvidenceSupport(mean=mean, scored=scored, skipped=skipped, low=low)


def _run(
    items: list[tuple[str, str, str]],
    *,
    api_key: str,
    client: Any | None,
    timeout: float,
) -> list[tuple[str, float]]:
    """Send the SOFT Noul per item, batched. Returns (path, probability) pairs.

    Raises on any SDK problem; ``score`` turns that into ``None``. The
    ``typesafe_sdk`` import is here (function-local) so a base install without the
    ``graphlm[typesafe]`` extra never fails importing this module.
    """
    from typesafe_sdk import Noul, NoulCriteria, TypeSafeClient  # local: optional extra

    criteria = NoulCriteria(true=_TRUE, false=_FALSE)

    def _question(claim: str, source: str) -> Noul:
        return Noul(
            instructions={"task": _INSTRUCTIONS, "CLAIM": claim, "SOURCE": source},
            criteria=criteria,
        )

    owns_client = client is None
    client = client if client is not None else TypeSafeClient(api_key=api_key)
    out: list[tuple[str, float]] = []
    try:
        for start in range(0, len(items), _BATCH):
            chunk = items[start : start + _BATCH]
            questions = {
                f"q{start + i}": _question(claim, source)
                for i, (_path, claim, source) in enumerate(chunk)
            }
            resp = client.system_one(
                state={"note": "Each question carries its own CLAIM and SOURCE."},
                questions=questions,
                timeout=timeout,
            )
            for i, (path, _claim_text, _source) in enumerate(chunk):
                out.append((path, float(resp.nouls[f"q{start + i}"].noul)))
    finally:
        if owns_client:
            _close(client)
    return out


def _close(client: Any) -> None:
    """Best-effort close of a client we constructed (context-manager or .close)."""
    try:
        closer = getattr(client, "close", None)
        if callable(closer):
            closer()
    except Exception:
        pass
