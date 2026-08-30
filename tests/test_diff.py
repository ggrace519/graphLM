"""Tests for the graph-vs-graph diff (GRAPH_DIFF.*) — ADR-002."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graphlm.diff import (
    DIFF_SCHEMA_VERSION,
    BaselineState,
    compute_diff,
    load_baseline,
    render_diff_json,
    render_diff_markdown,
)
from graphlm.models import (
    CodebaseGraph,
    Cycle,
    DataFlowEdge,
    EntryPoint,
    FileSummary,
    GraphMeta,
    ImportEdge,
    ModuleDescription,
)
from graphlm.render import WriteResult, write_outputs


# --- Helpers -----------------------------------------------------------------


def _graph(
    *,
    modules=(),
    import_edges=(),
    deterministic_edges=None,
    data_flow=(),
    entry_points=(),
    file_summaries=(),
    cycles=(),
    sha="a" * 40,
    with_meta=True,
) -> CodebaseGraph:
    meta = GraphMeta(created_at="2026-08-30T00:00:00Z", commit_sha=sha) if with_meta else None
    return CodebaseGraph(
        directory_tree="root/",
        modules=[ModuleDescription(path=p, name=p, description="x") for p in modules],
        import_edges=[ImportEdge(from_path=a, to_path=b, kind=k) for a, b, k in import_edges],
        deterministic_edges=(
            None
            if deterministic_edges is None
            else [ImportEdge(from_path=a, to_path=b, kind=k) for a, b, k in deterministic_edges]
        ),
        data_flow=[DataFlowEdge(source=s, destination=d, description="x") for s, d in data_flow],
        entry_points=[
            EntryPoint(path=p, name=n, kind="cli_command", description="x") for p, n in entry_points
        ],
        file_summaries=[FileSummary(path=p, summary="x") for p in file_summaries],
        import_cycles=[Cycle(nodes=list(c), edges=[], length=len(c), risk_score=1.0) for c in cycles],
        meta=meta,
    )


# --- load_baseline: the three states -----------------------------------------


def test_missing_baseline_is_first_run(tmp_path):
    graph, state = load_baseline(tmp_path / "GRAPH.json")
    assert graph is None
    assert state is BaselineState.FIRST_RUN


def test_corrupt_baseline_is_uncomparable(tmp_path):
    p = tmp_path / "GRAPH.json"
    p.write_text("{ not valid json ")
    graph, state = load_baseline(p)
    assert graph is None
    assert state is BaselineState.UNCOMPARABLE


def test_unreadable_baseline_is_uncomparable(tmp_path, monkeypatch):
    """Exercise a read failure directly; corrupt bytes test decoding, not access."""
    p = tmp_path / "GRAPH.json"
    p.write_text("{}")

    def deny_read(_path):
        raise PermissionError("baseline is unreadable")

    monkeypatch.setattr(Path, "read_bytes", deny_read)

    graph, state = load_baseline(p)

    assert graph is None
    assert state is BaselineState.UNCOMPARABLE


@pytest.mark.parametrize(
    "schema_version",
    [[], {}, True, 1.0],
    ids=["list", "dict", "bool", "float"],
)
def test_invalid_schema_version_types_are_uncomparable(tmp_path, schema_version):
    p = tmp_path / "GRAPH.json"
    data = json.loads(render_json_bytes(_graph(modules=["a.py"])))
    data["meta"]["schema_version"] = schema_version
    p.write_text(json.dumps(data))

    graph, state = load_baseline(p)

    assert graph is None
    assert state is BaselineState.UNCOMPARABLE


def test_invalid_utf8_baseline_is_uncomparable(tmp_path):
    p = tmp_path / "GRAPH.json"
    p.write_bytes(b"\xff\xfe poison")

    graph, state = load_baseline(p)

    assert graph is None
    assert state is BaselineState.UNCOMPARABLE


def test_baseline_truncated_mid_utf8_codepoint_is_uncomparable(tmp_path):
    p = tmp_path / "GRAPH.json"
    rendered = render_json_bytes(_graph(modules=["caf\N{LATIN SMALL LETTER E WITH ACUTE}.py"]))
    codepoint = "\N{LATIN SMALL LETTER E WITH ACUTE}".encode()
    codepoint_start = rendered.index(codepoint)
    p.write_bytes(rendered[: codepoint_start + 1])

    graph, state = load_baseline(p)

    assert graph is None
    assert state is BaselineState.UNCOMPARABLE


def test_broken_symlink_baseline_is_uncomparable(tmp_path):
    p = tmp_path / "GRAPH.json"
    p.symlink_to(tmp_path / "missing-target.json")
    assert not p.exists()
    assert p.is_symlink()

    graph, state = load_baseline(p)

    assert graph is None
    assert state is BaselineState.UNCOMPARABLE


def test_unknown_schema_version_is_uncomparable(tmp_path):
    p = tmp_path / "GRAPH.json"
    data = json.loads(render_json_bytes(_graph(modules=["a.py"])))
    data["meta"]["schema_version"] = 999
    p.write_text(json.dumps(data))
    graph, state = load_baseline(p)
    assert graph is None
    assert state is BaselineState.UNCOMPARABLE


def test_valid_baseline_is_normal(tmp_path):
    p = tmp_path / "GRAPH.json"
    data = json.loads(render_json_bytes(_graph(modules=["a.py"])))
    data["meta"]["schema_version"] = 1
    p.write_text(json.dumps(data))
    graph, state = load_baseline(p)
    assert state is BaselineState.NORMAL
    assert graph is not None
    assert graph.modules[0].path == "a.py"


def test_old_format_meta_less_baseline_is_normal(tmp_path):
    """A pre-stamp GRAPH.json (no meta) parses and compares as NORMAL, not uncomparable."""
    p = tmp_path / "GRAPH.json"
    p.write_text(json.dumps({"directory_tree": "r/", "modules": [{"path": "z.py", "name": "z", "description": "x"}]}))
    graph, state = load_baseline(p)
    assert state is BaselineState.NORMAL
    assert graph is not None
    assert graph.meta is None


def test_baseline_with_schema_version_absent_is_normal(tmp_path):
    p = tmp_path / "GRAPH.json"
    data = json.loads(render_json_bytes(_graph(modules=["a.py"])))
    del data["meta"]["schema_version"]
    p.write_text(json.dumps(data))

    graph, state = load_baseline(p)

    assert state is BaselineState.NORMAL
    assert graph is not None
    assert graph.meta is not None
    assert graph.meta.schema_version == 1


def test_det_edges_none_survives_baseline_round_trip(tmp_path):
    """`deterministic_edges=None` (AST off) must read back as None from a baseline.

    render_json's `exclude_none=True` drops the key entirely, and re-parse falls
    back to the field default (None) — so the "AST was off" signal survives, and
    decision 5's None-vs-[] distinction still fires on a prior graph read from
    disk. Guarded explicitly because the field's default happening to be None is
    what makes this hold (nit from review).
    """
    p = tmp_path / "GRAPH.json"
    p.write_bytes(render_json_bytes(_graph(modules=["a.py"], deterministic_edges=None)))
    assert '"deterministic_edges"' not in p.read_text()  # dropped by exclude_none
    graph, state = load_baseline(p)
    assert state is BaselineState.NORMAL
    assert graph is not None
    assert graph.deterministic_edges is None  # not [] — the signal survived


def test_det_edges_empty_survives_baseline_round_trip(tmp_path):
    """`deterministic_edges=[]` (AST ran, none found) reads back as [], not None."""
    p = tmp_path / "GRAPH.json"
    p.write_bytes(render_json_bytes(_graph(modules=["a.py"], deterministic_edges=[])))
    graph, _ = load_baseline(p)
    assert graph is not None
    assert graph.deterministic_edges == []


# --- compute_diff: dimensions ------------------------------------------------


def test_modules_added_and_removed():
    old = _graph(modules=["a.py", "b.py"])
    new = _graph(modules=["a.py", "c.py"])
    diff = compute_diff(old, new, BaselineState.NORMAL)
    assert diff.dimensions["modules"].added == ["`c.py`"]
    assert diff.dimensions["modules"].removed == ["`b.py`"]


def test_import_edges_keyed_by_triple():
    old = _graph(import_edges=[("a.py", "b.py", "import")])
    new = _graph(import_edges=[("a.py", "b.py", "from")])  # kind change → remove+add
    diff = compute_diff(old, new, BaselineState.NORMAL)
    d = diff.dimensions["import_edges"]
    assert d.added == ["`a.py` -> `b.py` (from)"]
    assert d.removed == ["`a.py` -> `b.py` (import)"]


def test_cycles_keyed_by_node_set_order_independent():
    old = _graph(cycles=[["a.py", "b.py"]])
    new = _graph(cycles=[["b.py", "a.py"]])  # same set, different order → no change
    diff = compute_diff(old, new, BaselineState.NORMAL)
    assert diff.dimensions["import_cycles"].added == []
    assert diff.dimensions["import_cycles"].removed == []


def test_data_flow_and_entry_points_and_summaries():
    old = _graph(data_flow=[("a", "b")], entry_points=[("cli.py", "main")], file_summaries=["a.py"])
    new = _graph(data_flow=[("a", "c")], entry_points=[("api.py", "app")], file_summaries=["b.py"])
    diff = compute_diff(old, new, BaselineState.NORMAL)
    assert diff.dimensions["data_flow"].added == ["a -> c"]
    assert diff.dimensions["data_flow"].removed == ["a -> b"]
    assert diff.dimensions["entry_points"].added == ["`api.py` :: `app`"]
    assert diff.dimensions["file_summaries"].added == ["`b.py`"]
    assert diff.dimensions["file_summaries"].removed == ["`a.py`"]


def test_no_changes_when_structurally_identical():
    """Prose-only differences are invisible (added/removed-only, ADR-002 dec. 2)."""
    old = _graph(modules=["a.py"])
    new = _graph(modules=["a.py"])
    new.modules[0].description = "totally different prose"  # not a structural key
    diff = compute_diff(old, new, BaselineState.NORMAL)
    assert not diff.has_changes


# --- deterministic_edges None vs [] (ADR-002 decision 5) ---------------------


def test_det_edges_none_on_either_side_not_compared():
    # new run with --no-ast (None) against a prior run that had edges
    old = _graph(deterministic_edges=[("a.py", "b.py", "import")])
    new = _graph(deterministic_edges=None)
    diff = compute_diff(old, new, BaselineState.NORMAL)
    d = diff.dimensions["deterministic_edges"]
    assert d.compared is False
    assert d.added == [] and d.removed == []


def test_det_edges_both_empty_is_compared_no_changes():
    old = _graph(deterministic_edges=[])
    new = _graph(deterministic_edges=[])
    diff = compute_diff(old, new, BaselineState.NORMAL)
    d = diff.dimensions["deterministic_edges"]
    assert d.compared is True
    assert d.added == [] and d.removed == []


def test_det_edges_both_lists_diffed():
    old = _graph(deterministic_edges=[("a.py", "b.py", "import")])
    new = _graph(deterministic_edges=[("a.py", "c.py", "import")])
    d = compute_diff(old, new, BaselineState.NORMAL).dimensions["deterministic_edges"]
    assert d.compared is True
    assert d.added == ["`a.py` -> `c.py` (import)"]
    assert d.removed == ["`a.py` -> `b.py` (import)"]


def test_no_change_banner_qualified_when_a_dimension_not_compared():
    """A skipped (not-compared) dimension must NOT be collapsed into "no change".

    Regression for the render-layer conflation: everything unchanged *except*
    AST edges, which are `None` on one side (--no-ast toggled). The headline
    must not claim "No structural changes" unqualified, or an agent reads
    "unchanged" as "checked and unchanged" (ADR-002 dec. 4/5).
    """
    old = _graph(modules=["a.py"], deterministic_edges=[("a.py", "b.py", "import")], sha="1" * 40)
    new = _graph(modules=["a.py"], deterministic_edges=None, sha="2" * 40)
    diff = compute_diff(old, new, BaselineState.NORMAL)
    assert diff.has_changes is False
    assert diff.all_compared is False
    md = render_diff_markdown(diff)
    assert "**No structural changes** since the prior graph." not in md
    assert "not compared" in md.lower()
    assert "compared dimensions" in md


def test_no_change_banner_clean_when_all_compared():
    """The unqualified banner is still shown when every dimension was compared."""
    old = _graph(modules=["a.py"], deterministic_edges=[], sha="1" * 40)
    new = _graph(modules=["a.py"], deterministic_edges=[], sha="2" * 40)
    diff = compute_diff(old, new, BaselineState.NORMAL)
    assert diff.all_compared is True
    md = render_diff_markdown(diff)
    assert "**No structural changes** since the prior graph." in md


# --- SHA range ---------------------------------------------------------------


def test_sha_range_both_present():
    old = _graph(sha="1" * 40)
    new = _graph(sha="2" * 40)
    md = render_diff_markdown(compute_diff(old, new, BaselineState.NORMAL))
    assert "`11111111` → `22222222`" in md


def test_sha_range_null_side_reads_unknown():
    old = _graph(with_meta=False)  # meta absent → old sha unknown
    new = _graph(sha="2" * 40)
    diff = compute_diff(old, new, BaselineState.NORMAL)
    md = render_diff_markdown(diff)
    assert "unknown → `22222222`" in md
    assert diff.old_sha is None


# --- non-normal states carry the label, no dimensions ------------------------


def test_first_run_diff_has_state_and_no_dimensions():
    diff = compute_diff(None, _graph(sha="2" * 40), BaselineState.FIRST_RUN)
    assert diff.state is BaselineState.FIRST_RUN
    assert diff.dimensions == {}
    md = render_diff_markdown(diff)
    assert "initial graph — no prior version" in md


def test_uncomparable_diff_distinct_from_first_run():
    diff = compute_diff(None, _graph(sha="2" * 40), BaselineState.UNCOMPARABLE)
    md = render_diff_markdown(diff)
    assert "could not be read" in md
    assert "initial graph" not in md


# --- JSON artifact -----------------------------------------------------------


def test_diff_json_shape():
    old = _graph(modules=["a.py"], deterministic_edges=[], sha="1" * 40)
    new = _graph(modules=["b.py"], deterministic_edges=[], sha="2" * 40)
    data = json.loads(render_diff_json(compute_diff(old, new, BaselineState.NORMAL)))
    assert data["diff_schema_version"] == DIFF_SCHEMA_VERSION
    assert data["state"] == "normal"
    assert data["old_commit_sha"] == "1" * 40
    assert data["new_commit_sha"] == "2" * 40
    assert data["dimensions"]["modules"]["added"] == ["`b.py`"]
    assert data["dimensions"]["modules"]["removed"] == ["`a.py`"]
    assert data["dimensions"]["deterministic_edges"]["compared"] is True


def test_diff_json_null_sha_preserved():
    old = _graph(with_meta=False)
    new = _graph(sha="2" * 40)
    data = json.loads(render_diff_json(compute_diff(old, new, BaselineState.NORMAL)))
    assert data["old_commit_sha"] is None


# --- write_outputs integration: ordering, WriteResult, on/off ----------------


def test_write_outputs_reads_baseline_before_overwrite(tmp_path):
    """The diff must reflect the *prior* GRAPH.json, not the just-written one."""
    write_outputs(_graph(modules=["a.py"], sha="1" * 40), tmp_path)
    result = write_outputs(_graph(modules=["b.py"], sha="2" * 40), tmp_path)
    diff = json.loads(result.diff_json.read_text())
    assert diff["state"] == "normal"
    assert diff["dimensions"]["modules"]["added"] == ["`b.py`"]
    assert diff["dimensions"]["modules"]["removed"] == ["`a.py`"]
    assert "`11111111` → `22222222`" in result.diff_md.read_text()


def test_write_outputs_first_run_writes_diff(tmp_path):
    result = write_outputs(_graph(modules=["a.py"]), tmp_path)
    assert result.diff_md.exists() and result.diff_json.exists()
    assert json.loads(result.diff_json.read_text())["state"] == "first_run"


def test_write_outputs_poison_baseline_still_writes_new_graph(tmp_path):
    (tmp_path / "GRAPH.json").write_bytes(b"\xff\xfe poison")

    result = write_outputs(_graph(modules=["new.py"]), tmp_path)

    assert (tmp_path / "GRAPH.md").exists()
    assert (tmp_path / "GRAPH.json").exists()
    written_graph = json.loads((tmp_path / "GRAPH.json").read_text())
    assert written_graph["modules"][0]["path"] == "new.py"
    assert result.diff_json is not None
    assert json.loads(result.diff_json.read_text())["state"] == "uncomparable"


def test_write_outputs_no_diff_writes_nothing(tmp_path):
    result = write_outputs(_graph(modules=["a.py"]), tmp_path, diff=False)
    assert result.diff_md is None and result.diff_json is None
    assert not (tmp_path / "GRAPH_DIFF.md").exists()
    assert not (tmp_path / "GRAPH_DIFF.json").exists()


def test_write_result_is_backward_compatible_tuple(tmp_path):
    result = write_outputs(_graph(modules=["a.py"]), tmp_path)
    md, json_, html = result  # 3-way unpack must still work
    assert md.name == "GRAPH.md"
    assert json_.name == "GRAPH.json"
    assert html.name == "GRAPH.html"
    assert isinstance(result, WriteResult)


def test_diff_suffix_follows_json_suffix(tmp_path):
    """The baseline read and diff filenames honor a custom suffix."""
    write_outputs(_graph(modules=["a.py"], sha="1" * 40), tmp_path, json_suffix="map")
    result = write_outputs(_graph(modules=["b.py"], sha="2" * 40), tmp_path, json_suffix="map")
    assert result.diff_md == tmp_path / "map_DIFF.md"
    assert result.diff_json == tmp_path / "map_DIFF.json"
    assert result.diff_md.name == "map_DIFF.md"
    assert result.diff_md.exists() and result.diff_json.exists()
    # baseline was read from map.json → normal, not first-run
    assert json.loads(result.diff_json.read_text())["state"] == "normal"


def test_explicit_diff_suffix_overrides_json_suffix(tmp_path):
    write_outputs(
        _graph(modules=["a.py"], sha="1" * 40),
        tmp_path,
        json_suffix="map",
        diff_suffix="custom",
    )
    result = write_outputs(
        _graph(modules=["b.py"], sha="2" * 40),
        tmp_path,
        json_suffix="map",
        diff_suffix="custom",
    )

    assert result.diff_md == tmp_path / "custom_DIFF.md"
    assert result.diff_json == tmp_path / "custom_DIFF.json"
    assert result.diff_md.exists() and result.diff_json.exists()
    assert json.loads(result.diff_json.read_text())["state"] == "normal"


# --- small helper reused above ------------------------------------------------


def render_json_bytes(graph: CodebaseGraph) -> bytes:
    from graphlm.render import render_json

    return render_json(graph)
