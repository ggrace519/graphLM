"""Tests for the render module."""

import copy
import json
import pickle
import random
from pathlib import Path
from tempfile import TemporaryDirectory

from graphlm.mermaid import render_mermaid
from graphlm.models import (
    ArchitectureNote,
    CodebaseGraph,
    Cycle,
    DBColumn,
    DBTable,
    DataFlowEdge,
    GraphMeta,
    ImportEdge,
    ModuleDescription,
    QuickReference,
    TestMapping,
)
from graphlm.render import WriteResult, render_json, render_markdown, write_outputs


class TestRenderMarkdown:
    def test_empty_graph(self):
        graph = CodebaseGraph(directory_tree="root/\n")
        md = render_markdown(graph)
        assert "Codebase Graph" in md
        assert "root/" in md

    def test_with_import_edges(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            import_edges=[
                ImportEdge(from_path="a.py", to_path="b.py", kind="import"),
                ImportEdge(from_path="c.py", to_path="b.py", kind="from"),
            ],
        )
        md = render_markdown(graph)
        assert "| From | To | Kind |" in md
        assert "`a.py`" in md
        assert "import" in md

    def test_with_modules(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            modules=[
                ModuleDescription(path="main.py", name="Main", description="Entry point"),
                ModuleDescription(path="lib.py", name="Lib", description="Library"),
            ],
        )
        md = render_markdown(graph)
        assert "| Path | Name | Description |" in md
        assert "main.py" in md
        assert "Entry point" in md

    def test_with_database_schema(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            database_schema=[
                DBTable(
                    name="users",
                    columns=[
                        DBColumn(name="id", type="INTEGER", constraints="PRIMARY KEY"),
                        DBColumn(name="email", type="TEXT", constraints="NOT NULL"),
                    ],
                    description="User accounts",
                )
            ],
        )
        md = render_markdown(graph)
        assert "users" in md
        assert "User accounts" in md
        assert "`id`" in md
        assert "INTEGER" in md

    def test_with_data_flow(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            data_flow=[
                DataFlowEdge(source="API", destination="DB", description="Queries"),
            ],
        )
        md = render_markdown(graph)
        assert "| Source | Destination | Description |" in md
        assert "API" in md
        assert "DB" in md

    def test_with_quick_reference(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            quick_reference=[
                QuickReference(query="app factory", location="main.py"),
            ],
        )
        md = render_markdown(graph)
        assert "| Find | Location |" in md
        assert "app factory" in md
        assert "main.py" in md

    def test_with_test_organization(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            test_organization=[
                TestMapping(file="test_main.py", covers="App factory"),
            ],
        )
        md = render_markdown(graph)
        assert "| Test File | Covers |" in md
        assert "test_main.py" in md

    def test_with_architecture_notes(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            architecture_notes=[
                ArchitectureNote(note="No ORM used"),
                ArchitectureNote(note="Vanilla HTML/CSS/JS"),
            ],
        )
        md = render_markdown(graph)
        assert "No ORM used" in md
        assert "Vanilla HTML/CSS/JS" in md

    def test_markdown_has_newline_terminator(self):
        graph = CodebaseGraph(directory_tree="root/\n")
        md = render_markdown(graph)
        assert md.endswith("\n")


class TestRenderJson:
    def test_serializes_all_fields(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            import_edges=[ImportEdge(from_path="a.py", to_path="b.py", kind="import")],
            modules=[ModuleDescription(path="a.py", name="A", description="A module")],
            database_schema=[
                DBTable(name="t", columns=[DBColumn(name="c", type="INT")])
            ],
        )
        data = render_json(graph)
        assert b'"directory_tree"' in data
        assert b'"import_edges"' in data
        assert b'"modules"' in data
        assert b'"database_schema"' in data

    def test_null_database_schema_excluded(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            database_schema=None,
        )
        data = render_json(graph)
        assert b'"database_schema"' not in data

    def test_empty_lists_included(self):
        graph = CodebaseGraph(directory_tree="root/")
        data = render_json(graph)
        assert b'"import_edges": []' in data


class TestWriteOutputs:
    def test_writes_both_files(self):
        graph = CodebaseGraph(directory_tree="root/\n")
        with TemporaryDirectory() as tmpdir:
            md_path, json_path, html_path = write_outputs(graph, Path(tmpdir))
            assert md_path.exists()
            assert json_path.exists()
            assert html_path is not None
            assert html_path.exists()
            assert md_path.name == "GRAPH.md"
            assert json_path.name == "GRAPH.json"
            assert html_path.name == "GRAPH.html"

    def test_no_html_when_disabled(self):
        graph = CodebaseGraph(directory_tree="root/\n")
        with TemporaryDirectory() as tmpdir:
            md_path, json_path, html_path = write_outputs(
                graph, Path(tmpdir), html=False
            )
            assert md_path.exists()
            assert json_path.exists()
            assert html_path is None

    def test_creates_output_directory(self):
        graph = CodebaseGraph(directory_tree="root/\n")
        with TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "nested" / "dir"
            md_path, json_path, html_path = write_outputs(graph, out)
            assert md_path.parent == out
            assert html_path.parent == out

    def test_custom_suffixes(self):
        graph = CodebaseGraph(directory_tree="root/\n")
        with TemporaryDirectory() as tmpdir:
            result = write_outputs(
                graph, Path(tmpdir), md_suffix="graph", json_suffix="graph"
            )
            md_path, json_path, html_path = result
            assert md_path.name == "graph.md"
            assert json_path.name == "graph.json"
            assert result.diff_md is not None
            assert result.diff_md.name == "graph_DIFF.md"
            assert result.diff_md.exists()
            assert result.diff_json is not None
            assert result.diff_json.name == "graph_DIFF.json"
            assert result.diff_json.exists()

    def test_custom_diff_suffix_overrides_json_suffix(self):
        graph = CodebaseGraph(directory_tree="root/\n")
        with TemporaryDirectory() as tmpdir:
            result = write_outputs(
                graph,
                Path(tmpdir),
                json_suffix="graph",
                diff_suffix="custom",
            )
            assert result.diff_md is not None
            assert result.diff_md.name == "custom_DIFF.md"
            assert result.diff_md.exists()
            assert result.diff_json is not None
            assert result.diff_json.name == "custom_DIFF.json"
            assert result.diff_json.exists()

    def test_write_result_preserves_diff_paths_across_round_trips(self):
        result = WriteResult(
            Path("GRAPH.md"),
            Path("GRAPH.json"),
            Path("GRAPH.html"),
            diff_md=Path("GRAPH_DIFF.md"),
            diff_json=Path("GRAPH_DIFF.json"),
        )

        round_trips = (
            copy.copy(result),
            copy.deepcopy(result),
            pickle.loads(pickle.dumps(result)),
        )
        for round_trip in round_trips:
            assert tuple(round_trip) == tuple(result)
            assert round_trip.diff_md == result.diff_md
            assert round_trip.diff_json == result.diff_json
            assert len(round_trip) == 3
            md_path, json_path, html_path = round_trip
            assert (md_path, json_path, html_path) == tuple(result)

    def test_meta_bearing_graph_renders_html_default_path(self):
        # The CLI default is html=True, so the real path renders a meta-bearing
        # graph to HTML. The directive is GRAPH.md-only and must NOT leak in.
        graph = CodebaseGraph(
            directory_tree="root/\n",
            meta=GraphMeta(
                created_at="2026-08-30T00:00:00Z", commit_sha="a" * 40
            ),
        )
        with TemporaryDirectory() as tmpdir:
            md_path, json_path, html_path = write_outputs(graph, Path(tmpdir))
            assert html_path is not None and html_path.stat().st_size > 0
            assert "Provenance & refresh directive" not in html_path.read_text()
            assert "Provenance & refresh directive" in md_path.read_text()


_GIT_META = GraphMeta(
    created_at="2026-08-30T14:22:05Z",
    commit_sha="d38e47d21406cf6482c0272587d17d92629059be",
    graphlm_version="0.1.0",
)
_NONGIT_META = GraphMeta(
    created_at="2026-08-30T14:22:05Z", commit_sha=None, graphlm_version=None
)


class TestRefreshDirective:
    def test_git_form_present_when_sha_set(self):
        md = render_markdown(CodebaseGraph(directory_tree="root/\n", meta=_GIT_META))
        # Directive is the first line, above the heading.
        assert md.lstrip().startswith(">")
        assert "generated against commit `d38e47d2`" in md
        assert "2026-08-30T14:22:05Z" in md
        assert "graphlm ." in md
        assert "git rev-parse HEAD" in md
        assert "advisory" in md.lower()

    def test_non_git_form_when_sha_none(self):
        md = render_markdown(
            CodebaseGraph(directory_tree="root/\n", meta=_NONGIT_META)
        )
        assert md.lstrip().startswith(">")
        assert "No git commit tracking" in md
        assert "whenever you believe the code has changed" in md
        assert "graphlm ." in md
        # The git-only comparison instruction must not appear.
        assert "generated against commit" not in md

    def test_no_directive_without_meta(self):
        md = render_markdown(CodebaseGraph(directory_tree="root/\n"))
        assert not md.lstrip().startswith(">")
        assert "# Codebase Graph" in md

    def test_dirty_tree_honesty_never_says_reflects(self):
        # Wording guard: "generated against", never "reflects" — a SHA-fresh
        # graph can still not match an uncommitted working tree.
        for meta in (_GIT_META, _NONGIT_META):
            md = render_markdown(CodebaseGraph(directory_tree="root/\n", meta=meta))
            assert "reflect" not in md.lower()


class TestRenderJsonMeta:
    def test_meta_serialized_with_sha(self):
        data = json.loads(
            render_json(CodebaseGraph(directory_tree="root/\n", meta=_GIT_META))
        )
        assert data["meta"]["commit_sha"] == _GIT_META.commit_sha
        assert data["meta"]["schema_version"] == 1

    def test_null_commit_sha_preserved_despite_exclude_none(self):
        # The critical case: exclude_none=True must NOT drop commit_sha=None,
        # or a non-git graph is indistinguishable from an old meta-less one.
        data = json.loads(
            render_json(CodebaseGraph(directory_tree="root/\n", meta=_NONGIT_META))
        )
        assert "meta" in data
        assert "commit_sha" in data["meta"]
        assert data["meta"]["commit_sha"] is None

    def test_no_meta_key_when_meta_absent(self):
        data = json.loads(render_json(CodebaseGraph(directory_tree="root/\n")))
        assert "meta" not in data

    def test_round_trips_through_model_validate(self):
        graph = CodebaseGraph(directory_tree="root/\n", meta=_GIT_META)
        reloaded = CodebaseGraph.model_validate_json(render_json(graph))
        assert reloaded.meta is not None
        assert reloaded.meta.commit_sha == _GIT_META.commit_sha

    def test_backward_read_of_meta_less_json(self):
        # Versioned-contract guarantee: an OLD GRAPH.json with no meta block
        # still validates, with meta defaulting to None.
        old = '{"directory_tree": "root/\\n", "modules": []}'
        graph = CodebaseGraph.model_validate_json(old)
        assert graph.meta is None


def _edge(a: str, b: str) -> ImportEdge:
    return ImportEdge(from_path=a, to_path=b, kind="import")


def _mermaid_block(md: str) -> str:
    """The text between the ```mermaid fence and its closing fence."""
    start = md.index("```mermaid\n") + len("```mermaid\n")
    return md[start:md.index("```", start)]


class TestMermaidModuleGraph:
    def test_section_present_with_ast_edges(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            deterministic_edges=[_edge("pkg/a.py", "lib/b.py")],
        )
        md = render_markdown(graph)
        assert "## Module Graph" in md
        assert "parser-extracted import edges (ground truth)" in md
        block = _mermaid_block(md)
        assert block.startswith("flowchart LR")
        assert 'n_pkg["pkg"]' in block
        assert 'n_lib["lib"]' in block
        assert "n_pkg --> n_lib" in block

    def test_section_sits_right_after_directory_tree(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            deterministic_edges=[_edge("pkg/a.py", "lib/b.py")],
            import_edges=[_edge("pkg/a.py", "lib/b.py")],
        )
        md = render_markdown(graph)
        assert (
            md.index("## Directory Tree")
            < md.index("## Module Graph")
            < md.index("## Import Edges")
        )

    def test_absent_when_no_edges(self):
        graph = CodebaseGraph(directory_tree="root/")
        assert render_mermaid(graph) == []
        assert "## Module Graph" not in render_markdown(graph)
        # An explicitly empty AST list with no LLM edges is also "no edges".
        empty_ast = CodebaseGraph(directory_tree="root/", deterministic_edges=[])
        assert render_mermaid(empty_ast) == []

    def test_falls_back_to_llm_edges_when_ast_is_none(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            deterministic_edges=None,
            import_edges=[_edge("pkg/a.py", "lib/b.py")],
        )
        md = render_markdown(graph)
        assert "LLM-inferred import edges" in md
        assert "ground truth" not in md
        assert "n_pkg --> n_lib" in _mermaid_block(md)

    def test_ast_edges_win_over_llm_edges(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            deterministic_edges=[_edge("pkg/a.py", "lib/b.py")],
            import_edges=[_edge("pkg/a.py", "other/c.py")],
        )
        block = _mermaid_block(render_markdown(graph))
        assert "n_pkg --> n_lib" in block
        assert "n_other" not in block

    def test_collapses_files_to_directory_and_drops_self_edges(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            deterministic_edges=[
                _edge("pkg/a.py", "lib/x.py"),
                _edge("pkg/b.py", "lib/y.py"),  # same dir pair -> one edge
                _edge("pkg/a.py", "pkg/b.py"),  # self-edge after collapse -> dropped
            ],
        )
        block = _mermaid_block(render_markdown(graph))
        assert block.count(" --> ") == 1
        assert "n_pkg --> n_lib" in block
        assert "n_pkg --> n_pkg" not in block
        assert block.count('["pkg"]') == 1

    def test_root_level_file_is_its_own_node(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            deterministic_edges=[_edge("setup.py", "pkg/a.py")],
        )
        block = _mermaid_block(render_markdown(graph))
        assert 'n_setup_py["setup.py"]' in block
        assert "n_setup_py --> n_pkg" in block

    def test_unsafe_path_chars_yield_safe_ids_and_escaped_labels(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            deterministic_edges=[_edge("my-dir/a.b.py", 'we"ird/c.py')],
        )
        block = _mermaid_block(render_markdown(graph))
        assert 'n_my_dir["my-dir"]' in block
        assert 'n_we_ird["we#quot;ird"]' in block
        assert "n_my_dir --> n_we_ird" in block
        # Every id token is [A-Za-z0-9_] only.
        for line in block.splitlines()[1:]:
            for tok in line.split():
                if tok.startswith("n_"):
                    ident = tok.split("[", 1)[0]
                    assert ident.replace("_", "a").isalnum(), ident

    def test_colliding_sanitized_ids_are_disambiguated(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            deterministic_edges=[_edge("a-b/x.py", "a_b/y.py")],
        )
        block = _mermaid_block(render_markdown(graph))
        assert 'n_a_b["a-b"]' in block
        assert 'n_a_b_2["a_b"]' in block
        assert "n_a_b --> n_a_b_2" in block

    def test_max_nodes_cap_keeps_highest_degree_and_notes_the_rest(self):
        # hub has degree 5; leaves have degree 1. Cap at 3 keeps hub + 2 leaves
        # (alphabetical tie-break) and hides 3 directories.
        edges = [_edge("hub/h.py", f"leaf{i}/l.py") for i in range(5)]
        graph = CodebaseGraph(directory_tree="root/", deterministic_edges=edges)
        text = "\n".join(render_mermaid(graph, max_nodes=3))
        assert 'n_hub["hub"]' in text
        assert 'n_leaf0["leaf0"]' in text
        assert 'n_leaf1["leaf1"]' in text
        assert "leaf2" not in text and "leaf4" not in text
        assert "*… 3 more directories not shown*" in text
        assert text.count(" --> ") == 2

    def test_no_more_note_when_under_cap(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            deterministic_edges=[_edge("pkg/a.py", "lib/b.py")],
        )
        assert "more directories not shown" not in render_markdown(graph)

    def test_cycle_edges_styled_with_exact_link_indices(self):
        # Four collapsed edges, two of which are cycle edges (both file-level
        # endpoints in the same SCC). Cycle links are emitted last, so with two
        # plain links at indices 0 and 1 the cycle links are indices 2 and 3.
        graph = CodebaseGraph(
            directory_tree="root/",
            deterministic_edges=[
                _edge("a/x.py", "b/y.py"),
                _edge("b/y.py", "a/x.py"),
                _edge("c/z.py", "d/w.py"),
                _edge("d/w.py", "e/v.py"),
            ],
            import_cycles=[
                Cycle(
                    nodes=["a/x.py", "b/y.py"],
                    edges=[_edge("a/x.py", "b/y.py"), _edge("b/y.py", "a/x.py")],
                    length=2,
                    risk_score=1.0,
                )
            ],
        )
        md = render_markdown(graph)
        block = _mermaid_block(md)
        links = [ln.strip() for ln in block.splitlines() if " --> " in ln]
        assert links == [
            "n_c --> n_d",
            "n_d --> n_e",
            "n_a --> n_b",
            "n_b --> n_a",
        ]
        assert "linkStyle 2,3 stroke:#e11,stroke-width:2px" in block
        assert "style n_a stroke:#e11,stroke-width:2px" in block
        assert "style n_b stroke:#e11,stroke-width:2px" in block
        assert "Red edges are members of an import cycle." in md
        assert "Red-outlined directories contain a file in an import cycle." in md

    def test_single_cycle_edge_gets_index_of_last_link(self):
        # Three collapsed edges, exactly one a cycle edge -> linkStyle 2.
        graph = CodebaseGraph(
            directory_tree="root/",
            deterministic_edges=[
                _edge("a/x.py", "b/y.py"),
                _edge("b/y.py", "a/z.py"),  # a/y.py is NOT in the cycle
                _edge("c/z.py", "d/w.py"),
            ],
            import_cycles=[
                Cycle(nodes=["a/x.py", "b/y.py"], edges=[], length=2, risk_score=1.0)
            ],
        )
        block = _mermaid_block(render_markdown(graph))
        links = [ln.strip() for ln in block.splitlines() if " --> " in ln]
        assert links == ["n_b --> n_a", "n_c --> n_d", "n_a --> n_b"]
        assert "linkStyle 2 stroke:#e11,stroke-width:2px" in block

    def test_intra_directory_cycle_shows_as_red_node_outline(self):
        # All cycle members in one directory: the edges collapse to a dropped
        # self-edge, so the directory outline is the only trace of the cycle.
        graph = CodebaseGraph(
            directory_tree="root/",
            deterministic_edges=[
                _edge("app/a.py", "app/b.py"),
                _edge("app/b.py", "app/a.py"),
                _edge("app/a.py", "lib/c.py"),
            ],
            import_cycles=[
                Cycle(nodes=["app/a.py", "app/b.py"], edges=[], length=2, risk_score=1.0)
            ],
        )
        md = render_markdown(graph)
        block = _mermaid_block(md)
        assert "linkStyle" not in block
        assert "style n_app stroke:#e11,stroke-width:2px" in block
        assert "style n_lib" not in block
        assert "Red edges are members of an import cycle." not in md
        assert "Red-outlined directories contain a file in an import cycle." in md

    def test_single_package_project_still_renders_its_node(self):
        # Every edge collapses to a self-edge (all files in one package). The
        # node must survive — with its cycle outline — even though no edge does.
        # Caught by the cyclic_project fixture: the block came out empty.
        graph = CodebaseGraph(
            directory_tree="root/",
            deterministic_edges=[
                _edge("app/a.py", "app/b.py"),
                _edge("app/b.py", "app/a.py"),
            ],
            import_cycles=[
                Cycle(nodes=["app/a.py", "app/b.py"], edges=[], length=2, risk_score=1.0)
            ],
        )
        block = _mermaid_block(render_markdown(graph))
        assert 'n_app["app"]' in block
        assert " --> " not in block
        assert "style n_app stroke:#e11,stroke-width:2px" in block

    def test_cap_keeps_cycle_member_over_equal_degree_peer(self):
        # hub->a, hub->b, hub->z: all leaves have degree 1. With z in a cycle
        # and max_nodes=2, z must beat a and b despite sorting last by name.
        graph = CodebaseGraph(
            directory_tree="root/",
            deterministic_edges=[
                _edge("hub/h.py", "a/x.py"),
                _edge("hub/h.py", "b/x.py"),
                _edge("hub/h.py", "z/x.py"),
            ],
            import_cycles=[
                Cycle(nodes=["z/x.py", "z/y.py"], edges=[], length=2, risk_score=1.0)
            ],
        )
        text = "\n".join(render_mermaid(graph, max_nodes=2))
        assert 'n_z["z"]' in text
        assert 'n_a["a"]' not in text
        assert "*… 2 more directories not shown*" in text

    def test_no_cycle_legend_without_cycles(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            deterministic_edges=[_edge("pkg/a.py", "lib/b.py")],
        )
        md = render_markdown(graph)
        section = md.split("## Module Graph", 1)[1]
        assert "linkStyle" not in section
        assert "style n_" not in section
        assert "import cycle" not in section

    def test_output_stable_under_shuffled_edge_order(self):
        edges = [
            _edge("a/x.py", "b/y.py"),
            _edge("b/y.py", "a/x.py"),
            _edge("c/z.py", "d/w.py"),
            _edge("a/x.py", "d/w.py"),
            _edge("e/q.py", "a/x.py"),
            _edge("a-b/x.py", "a_b/y.py"),
        ]
        cycles = [Cycle(nodes=["a/x.py", "b/y.py"], edges=[], length=2, risk_score=1.0)]
        baseline = render_mermaid(
            CodebaseGraph(
                directory_tree="root/", deterministic_edges=edges, import_cycles=cycles
            )
        )
        rng = random.Random(7)
        for _ in range(5):
            shuffled = list(edges)
            rng.shuffle(shuffled)
            got = render_mermaid(
                CodebaseGraph(
                    directory_tree="root/",
                    deterministic_edges=shuffled,
                    import_cycles=cycles,
                )
            )
            assert got == baseline
