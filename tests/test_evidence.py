"""Tests for prose evidence-support scoring (no network — client injected).

Requires the ``typesafe-sdk`` extra for the real ``Noul``/``NoulCriteria`` types
(the fake client only substitutes ``system_one``, i.e. the network call). Skips
cleanly without it, like the other language-pack tests.
"""

from __future__ import annotations

import pytest

pytest.importorskip("typesafe_sdk")

from graphlm import evidence  # noqa: E402
from graphlm.models import EvidenceSupport, FileSummary, Symbol  # noqa: E402
from graphlm.scanner import FileFragment  # noqa: E402


class _Ans:
    def __init__(self, noul: float) -> None:
        self.noul = noul


class _Resp:
    def __init__(self, nouls: dict[str, _Ans]) -> None:
        self.nouls = nouls


class _FakeClient:
    """Returns a per-question Noul; ``scores`` maps question index → probability."""

    def __init__(self, scores: dict[int, float] | None = None, default: float = 0.9):
        self.scores = scores or {}
        self.default = default
        self.batches = 0
        self.total_questions = 0

    def system_one(self, *, state, questions, timeout=None):  # noqa: ANN001
        self.batches += 1
        self.total_questions += len(questions)
        nouls = {}
        for key in questions:
            idx = int(key[1:])  # keys are "q<idx>"
            nouls[key] = _Ans(self.scores.get(idx, self.default))
        return _Resp(nouls)


def _frag(path: str, content: str = "code") -> FileFragment:
    return FileFragment(path, content, 1)


def _summary(path: str, symbols: list[Symbol] | None = None) -> FileSummary:
    return FileSummary(path=path, summary=f"summary of {path}", symbols=symbols or [])


class TestGates:
    def test_no_redact_returns_none(self):
        assert evidence.score(
            [_summary("a.py")], [_frag("a.py")],
            redact_secrets=False, api_key="k", client=_FakeClient(),
        ) is None

    def test_no_key_returns_none(self):
        assert evidence.score(
            [_summary("a.py")], [_frag("a.py")],
            redact_secrets=True, api_key=None, client=_FakeClient(),
        ) is None
        assert evidence.score(
            [_summary("a.py")], [_frag("a.py")],
            redact_secrets=True, api_key="", client=_FakeClient(),
        ) is None

    def test_empty_summaries_returns_none(self):
        assert evidence.score(
            [], [_frag("a.py")], redact_secrets=True, api_key="k", client=_FakeClient(),
        ) is None

    def test_gate_never_constructs_client(self):
        # A gate hit must not touch the client at all.
        fc = _FakeClient()
        evidence.score(
            [_summary("a.py")], [_frag("a.py")],
            redact_secrets=False, api_key="k", client=fc,
        )
        assert fc.batches == 0


class TestScoring:
    def test_scores_and_mean(self):
        fc = _FakeClient(scores={0: 0.8, 1: 0.6})
        res = evidence.score(
            [_summary("a.py"), _summary("b.py")],
            [_frag("a.py"), _frag("b.py")],
            redact_secrets=True, api_key="k", client=fc,
        )
        assert isinstance(res, EvidenceSupport)
        assert res.scored == 2 and res.skipped == 0
        assert res.mean == pytest.approx(0.7)

    def test_low_outliers_collected_sorted(self):
        fc = _FakeClient(scores={0: 0.9, 1: 0.2, 2: 0.35})
        res = evidence.score(
            [_summary("a.py"), _summary("b.py"), _summary("c.py")],
            [_frag("a.py"), _frag("b.py"), _frag("c.py")],
            redact_secrets=True, api_key="k", client=fc,
        )
        # Only < 0.5 collected, worst first.
        assert [(fs.path, fs.score) for fs in res.low] == [("b.py", 0.2), ("c.py", 0.35)]

    def test_pass2_miss_is_skipped_not_scored(self):
        # A summary whose file was not in pass2 is skipped, never scored against
        # content the model never saw.
        fc = _FakeClient()
        res = evidence.score(
            [_summary("a.py"), _summary("gone.py")],
            [_frag("a.py")],  # gone.py absent from the evidence set
            redact_secrets=True, api_key="k", client=fc,
        )
        assert res.scored == 1 and res.skipped == 1
        assert fc.total_questions == 1  # only the one with a fragment

    def test_all_skipped_returns_zero_scored_not_none(self):
        # Every summary tree-only → a real "nothing to compare" state, not None.
        fc = _FakeClient()
        res = evidence.score(
            [_summary("gone.py")], [_frag("a.py")],
            redact_secrets=True, api_key="k", client=fc,
        )
        assert res is not None
        assert res.scored == 0 and res.skipped == 1 and res.mean is None
        assert fc.batches == 0  # never called the API

    def test_batching_chunks_at_15(self):
        summaries = [_summary(f"f{i}.py") for i in range(32)]
        frags = [_frag(f"f{i}.py") for i in range(32)]
        fc = _FakeClient()
        res = evidence.score(
            summaries, frags, redact_secrets=True, api_key="k", client=fc,
        )
        assert res.scored == 32
        assert fc.batches == 3  # 15 + 15 + 2
        assert fc.total_questions == 32

    def test_symbols_flattened_into_claim(self):
        # The claim string includes symbol names — a smoke check that symbols
        # reach the question (the fake ignores content, so assert via no crash +
        # a real score for a summary carrying symbols).
        summ = _summary("a.py", [Symbol(name="Foo", kind="class", description="does foo")])
        res = evidence.score(
            [summ], [_frag("a.py")], redact_secrets=True, api_key="k", client=_FakeClient(),
        )
        assert res.scored == 1


class TestResilience:
    def test_client_raises_returns_none(self):
        class _Boom:
            def system_one(self, **k):  # noqa: ANN001
                raise RuntimeError("api down")

        assert evidence.score(
            [_summary("a.py")], [_frag("a.py")],
            redact_secrets=True, api_key="k", client=_Boom(),
        ) is None

    def test_malformed_response_returns_none(self):
        class _BadResp:
            def system_one(self, **k):  # noqa: ANN001
                return object()  # no .nouls

        assert evidence.score(
            [_summary("a.py")], [_frag("a.py")],
            redact_secrets=True, api_key="k", client=_BadResp(),
        ) is None


class TestClose:
    def test_close_called_on_owned_client(self):
        # When we construct the client (client=None path), we close it. Simulate
        # by driving _run with an injected client and owns_client via _close.
        closed = {"n": 0}

        class _Closable:
            def close(self):
                closed["n"] += 1

        evidence._close(_Closable())
        assert closed["n"] == 1

    def test_close_swallows_errors(self):
        class _BadClose:
            def close(self):
                raise RuntimeError("nope")

        evidence._close(_BadClose())  # must not raise

    def test_close_no_op_without_close_method(self):
        evidence._close(object())  # no .close — must not raise


class TestFlatten:
    def test_claim_includes_summary_and_symbols(self):
        summ = _summary("a.py", [Symbol(name="Foo", kind="class", description="the foo")])
        claim = evidence._claim(summ)
        assert "summary of a.py" in claim
        assert "Defines class `Foo`: the foo" in claim

    def test_norm_strips_dot_slash_and_backslashes(self):
        assert evidence._norm("./a/b.py") == "a/b.py"
        assert evidence._norm("a\\b.py") == "a/b.py"
