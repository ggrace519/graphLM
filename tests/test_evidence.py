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


def _frag(path: str, content: str | None = None) -> FileFragment:
    # Default content must be above evidence._MIN_EVIDENCE_CHARS so a fragment is
    # scored, not skipped as thin. Callers pass explicit thin content to test the
    # skip predicate.
    if content is None:
        content = "def f():\n    return 42  # substantive enough to be scored\n" * 2
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

    def test_thin_source_is_skipped_not_scored(self):
        # A near-empty file (below _MIN_EVIDENCE_CHARS of stripped content) has
        # nothing to verify a claim against — skip it, don't score a correct
        # minimal summary as weakly supported.
        fc = _FakeClient()
        res = evidence.score(
            [_summary("pkg/__init__.py"), _summary("real.py")],
            [_frag("pkg/__init__.py", '"""Pkg."""\n'), _frag("real.py", "x" * 200)],
            redact_secrets=True, api_key="k", client=fc,
        )
        assert res.scored == 1 and res.skipped == 1
        assert fc.total_questions == 1  # only the substantive file
        assert all(f.path != "pkg/__init__.py" for f in res.low)

    def test_whitespace_only_source_is_skipped(self):
        fc = _FakeClient()
        res = evidence.score(
            [_summary("blank.py")], [_frag("blank.py", "   \n\n  \t\n")],
            redact_secrets=True, api_key="k", client=fc,
        )
        assert res.scored == 0 and res.skipped == 1
        assert fc.batches == 0

    def test_source_at_threshold_is_scored(self):
        # Exactly _MIN_EVIDENCE_CHARS of stripped content is scored (boundary).
        fc = _FakeClient()
        src = "a" * evidence._MIN_EVIDENCE_CHARS
        res = evidence.score(
            [_summary("edge.py")], [_frag("edge.py", src)],
            redact_secrets=True, api_key="k", client=fc,
        )
        assert res.scored == 1 and res.skipped == 0

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


class _ScoreAns:
    def __init__(self, score: float) -> None:
        self.score = score


class _ScoreResp:
    def __init__(self, scores: dict) -> None:
        self.scores = scores


class _FakeScoreClient:
    """Returns a per-question role Score; `by_index` maps question idx -> score."""

    def __init__(self, by_index: dict[int, float] | None = None, default: float = 1.5):
        self.by_index = by_index or {}
        self.default = default
        self.batches = 0
        self.total = 0

    def system_one(self, *, state, questions, timeout=None):  # noqa: ANN001
        self.batches += 1
        self.total += len(questions)
        return _ScoreResp(
            {k: _ScoreAns(self.by_index.get(int(k[1:]), self.default)) for k in questions}
        )


def _mod(path, desc="does things"):
    from graphlm.models import ModuleDescription
    return ModuleDescription(path=path, name=path, description=desc)


def _edge(a, b):
    from graphlm.models import ImportEdge
    return ImportEdge(from_path=a, to_path=b, kind="import")


class TestFileDegree:
    def test_in_plus_out(self):
        deg = evidence.file_degree([_edge("a.py", "b.py"), _edge("c.py", "b.py")])
        assert deg == {"a.py": 1, "b.py": 2, "c.py": 1}

    def test_normalises_paths(self):
        deg = evidence.file_degree([_edge("./a.py", "sub/b.py")])
        assert deg == {"a.py": 1, "sub/b.py": 1}

    def test_empty(self):
        assert evidence.file_degree([]) == {}


class TestScoreImportance:
    def test_gates(self):
        assert evidence.score_importance([_mod("a.py")], [], api_key=None) is None
        assert evidence.score_importance([], [], api_key="k") is None

    def test_scores_modules(self):
        fc = _FakeScoreClient(by_index={0: 2.9, 1: 0.1})
        res = evidence.score_importance(
            [_mod("app.py"), _mod("settings.py")],
            [_edge("app.py", "settings.py")],
            api_key="k", client=fc,
        )
        assert res == {"app.py": 2.9, "settings.py": 0.1}

    def test_no_redact_param_at_all(self):
        # score_importance has no redact_secrets param — it sends no source.
        import inspect
        assert "redact_secrets" not in inspect.signature(evidence.score_importance).parameters

    def test_batches_at_15(self):
        mods = [_mod(f"m{i}.py") for i in range(32)]
        fc = _FakeScoreClient()
        evidence.score_importance(mods, [], api_key="k", client=fc)
        assert fc.batches == 3 and fc.total == 32

    def test_client_raises_returns_none(self):
        class _Boom:
            def system_one(self, **k):  # noqa: ANN001
                raise RuntimeError("down")
        assert evidence.score_importance([_mod("a.py")], [], api_key="k", client=_Boom()) is None

    def test_summary_passed_when_present(self):
        # summaries_by_path threads a summary into the question without error.
        fc = _FakeScoreClient(by_index={0: 2.0})
        res = evidence.score_importance(
            [_mod("a.py")], [], api_key="k", client=fc,
            summaries_by_path={"a.py": "the real summary"},
        )
        assert res == {"a.py": 2.0}


class TestDegreeForModule:
    """degree_for_module resolves file OR directory modules (#170)."""

    def test_exact_file_match(self):
        fd = {"a/b.py": 5, "a/c.py": 2}
        assert evidence.degree_for_module("a/b.py", fd) == 5

    def test_directory_sums_contained_files(self):
        fd = {"pkg/x.py": 3, "pkg/y.py": 4, "other/z.py": 9}
        assert evidence.degree_for_module("pkg", fd) == 7

    def test_directory_no_match_is_zero(self):
        assert evidence.degree_for_module("nope", {"a/b.py": 5}) == 0

    def test_prefix_guard_no_sibling_bleed(self):
        # 'agents' must not absorb 'agents_foo/'.
        fd = {"a/agents_foo/x.py": 2, "a/agents/y.py": 3}
        assert evidence.degree_for_module("a/agents", fd) == 3

    def test_trailing_slash_normalised(self):
        fd = {"pkg/x.py": 3}
        assert evidence.degree_for_module("pkg/", fd) == 3
class TestScoreRelevance:
    """score_relevance: Jev Noul per module against a query (semantic_find backend)."""

    def _cands(self, n=3):
        return [(f"m{i}.py", f"mod{i}", f"does thing {i}", "") for i in range(n)]

    def test_gates(self):
        assert evidence.score_relevance(self._cands(), "q", api_key=None) is None
        assert evidence.score_relevance([], "q", api_key="k") is None
        assert evidence.score_relevance(self._cands(), "", api_key="k") is None

    def test_scores_each_candidate(self):
        fc = _FakeClient(scores={0: 0.9, 1: 0.2, 2: 0.05})
        res = evidence.score_relevance(self._cands(3), "find the thing", api_key="k", client=fc)
        assert res == {"m0.py": 0.9, "m1.py": 0.2, "m2.py": 0.05}

    def test_batches_at_15(self):
        fc = _FakeClient()
        evidence.score_relevance(self._cands(32), "q", api_key="k", client=fc)
        assert fc.batches == 3 and fc.total_questions == 32

    def test_client_raises_returns_none(self):
        class _Boom:
            def system_one(self, **k):
                raise RuntimeError("down")
        assert evidence.score_relevance(self._cands(), "q", api_key="k", client=_Boom()) is None

    def test_summary_included_when_present(self):
        fc = _FakeClient(scores={0: 0.8})
        cands = [("a.py", "a", "desc", "the summary text")]
        res = evidence.score_relevance(cands, "q", api_key="k", client=fc)
        assert res == {"a.py": 0.8}


class TestFileLevelImportance:
    """The __init__ helpers routing importance to file-level on directory-granular
    graphs (INNOVATIONS #6), tested with an injected fake client."""

    def _dir_graph(self):
        from graphlm.models import CodebaseGraph, ModuleDescription, FileSummary
        return CodebaseGraph(
            directory_tree="t/",
            modules=[ModuleDescription(path="src/pkg", name="pkg", description="pkg"),
                     ModuleDescription(path="src/core", name="core", description="core")],
            file_summaries=[FileSummary(path="src/pkg/main.py", summary="entry"),
                            FileSummary(path="src/pkg/util.py", summary="helper")],
        )

    def test_is_directory_granular(self):
        from graphlm.enrich import is_directory_granular
        from graphlm.models import CodebaseGraph, ModuleDescription
        assert is_directory_granular(self._dir_graph()) is True
        file_g = CodebaseGraph(directory_tree="t/", modules=[
            ModuleDescription(path="a.py", name="a", description="x"),
            ModuleDescription(path="b.py", name="b", description="y")])
        assert is_directory_granular(file_g) is False
        assert is_directory_granular(CodebaseGraph(directory_tree="t/")) is False

    def test_score_file_importance_ranks_files(self):
        from graphlm.enrich import score_file_importance
        from graphlm.models import ImportEdge
        import graphlm.evidence as ev
        g = self._dir_graph()
        edges = [ImportEdge(from_path="src/pkg/util.py", to_path="src/pkg/main.py", kind="import")]
        fc = _FakeScoreClient(by_index={0: 2.8, 1: 0.4})  # main high, util low
        res = score_file_importance(g, edges, api_key="k", summaries_by_path={},
                                     evidence=ev, client=fc)
        assert res is not None
        assert res[0].path == "src/pkg/main.py"  # load-bearing first
        assert res[0].role == 2.8 and res[1].role == 0.4
        assert all(0 <= f.fused <= 1 for f in res)

    def test_score_file_importance_none_without_summaries(self):
        from graphlm.enrich import score_file_importance
        from graphlm.models import CodebaseGraph, ModuleDescription
        import graphlm.evidence as ev
        g = CodebaseGraph(directory_tree="t/", modules=[ModuleDescription(path="src/pkg", name="p", description="x")])
        assert score_file_importance(g, [], api_key="k", summaries_by_path={}, evidence=ev, client=_FakeScoreClient()) is None
