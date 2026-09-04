"""Tests for the LLM-vs-AST faithfulness score (pure, no I/O)."""

import pytest

from graphlm.faithfulness import score
from graphlm.models import Faithfulness, ImportEdge


def _e(src: str, dst: str, kind: str = "import") -> ImportEdge:
    return ImportEdge(from_path=src, to_path=dst, kind=kind)


class TestScore:
    def test_exact_precision_and_recall(self):
        ast = [_e("a.py", "b.py"), _e("a.py", "c.py"), _e("b.py", "c.py")]
        llm = [
            _e("a.py", "b.py"),  # matched
            _e("b.py", "c.py", kind="from"),  # matched (kind ignored)
            _e("c.py", "a.py"),  # invented — not in AST
            _e("d.py", "a.py"),  # invented — not in AST
        ]
        f = score(llm, ast)
        assert isinstance(f, Faithfulness)
        assert f.matched == 2
        assert f.llm_edges == 4
        assert f.ast_edges == 3
        assert f.precision == pytest.approx(2 / 4)
        assert f.recall == pytest.approx(2 / 3)

    def test_perfect_agreement(self):
        edges = [_e("a.py", "b.py"), _e("b.py", "c.py")]
        f = score(list(edges), list(edges))
        assert f is not None
        assert f.precision == 1.0
        assert f.recall == 1.0
        assert (f.matched, f.llm_edges, f.ast_edges) == (2, 2, 2)

    def test_ast_none_returns_none(self):
        # AST off: no ground truth, so "not scored" — never a fake zero.
        assert score([_e("a.py", "b.py")], None) is None

    def test_ast_empty_is_scored_with_null_recall(self):
        f = score([_e("a.py", "b.py")], [])
        assert f is not None
        assert f.recall is None
        assert f.precision == 0.0
        assert f.ast_edges == 0

    def test_no_comparable_llm_edges_gives_null_precision(self):
        f = score([], [_e("a.py", "b.py")])
        assert f is not None
        assert f.precision is None
        assert f.recall == 0.0
        assert f.llm_edges == 0

    def test_both_empty(self):
        f = score([], [])
        assert f == Faithfulness(
            precision=None, recall=None, llm_edges=0, ast_edges=0, matched=0
        )

    def test_kind_filtering_excludes_non_import_kinds(self):
        ast = [_e("a.py", "b.py")]
        llm = [
            _e("a.py", "b.py", kind="import"),
            _e("a.py", "x.py", kind="register"),
            _e("a.py", "y.py", kind="include"),
            _e("a.py", "z.py", kind="uses"),
        ]
        f = score(llm, ast)
        assert f is not None
        # Only the import edge is comparable; the rest are kinds the AST never claims.
        assert f.llm_edges == 1
        assert f.precision == 1.0

    def test_kind_ignored_in_matching(self):
        # The parser and model may disagree on import-vs-from for one statement.
        f = score([_e("a.py", "b.py", kind="from")], [_e("a.py", "b.py", kind="import")])
        assert f is not None
        assert f.matched == 1

    def test_non_py_edges_excluded_from_llm_side(self):
        ast = [_e("a.py", "b.py")]
        llm = [
            _e("a.py", "b.py"),
            _e("app.ts", "util.ts"),  # no TS edges in this AST run
            _e("a.py", "config.json"),  # one non-.py endpoint
        ]
        f = score(llm, ast)
        assert f is not None
        assert f.llm_edges == 1
        assert f.precision == 1.0

    def test_ts_edges_comparable_when_ast_emitted_ts(self):
        ast = [_e("app.ts", "util.ts"), _e("a.py", "b.py")]
        llm = [
            _e("app.ts", "util.ts"),
            _e("app.ts", "missing.ts"),  # invented TS
            _e("a.py", "b.py"),
        ]
        f = score(llm, ast)
        assert f is not None
        assert f.llm_edges == 3
        assert f.matched == 2
        assert f.precision == pytest.approx(2 / 3)

    def test_require_kind_is_comparable(self):
        ast = [_e("a.js", "b.js", kind="require")]
        llm = [_e("a.js", "b.js", kind="require")]
        f = score(llm, ast)
        assert f is not None
        assert f.matched == 1
        assert f.precision == 1.0
        assert f.recall == 1.0

    def test_path_normalisation(self):
        ast = [_e("pkg/a.py", "pkg/b.py")]
        llm = [_e("./pkg/a.py", "pkg\\b.py")]
        f = score(llm, ast)
        assert f is not None
        assert f.matched == 1
        assert f.precision == 1.0
        assert f.recall == 1.0

    def test_duplicates_collapsed(self):
        ast = [_e("a.py", "b.py"), _e("a.py", "b.py")]
        llm = [_e("a.py", "b.py"), _e("a.py", "b.py", kind="from")]
        f = score(llm, ast)
        assert f is not None
        assert (f.llm_edges, f.ast_edges, f.matched) == (1, 1, 1)

    def test_accepts_any_iterable_for_llm_edges(self):
        f = score(iter([_e("a.py", "b.py")]), [_e("a.py", "b.py")])
        assert f is not None
        assert f.matched == 1
