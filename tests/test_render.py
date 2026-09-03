"""Tests for the render module."""

import copy
import json
import pickle
from pathlib import Path
from tempfile import TemporaryDirectory

from graphlm.models import (
    ArchitectureNote,
    CodebaseGraph,
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


class TestRunTelemetryLine:
    """The run-telemetry blockquote (innovation #6): each half optional, the
    whole line omitted when neither is present, `n/a` for a ratio with no
    denominator."""

    @staticmethod
    def _meta(**kw):
        from graphlm.models import GraphMeta

        return GraphMeta(created_at="2026-09-02T00:00:00Z", **kw)

    def test_omitted_when_nothing_measured(self):
        md = render_markdown(CodebaseGraph(directory_tree="r/\n", meta=self._meta()))
        assert "Run telemetry" not in md

    def test_usage_only(self):
        from graphlm.models import PassUsage, RunUsage

        meta = self._meta(
            usage=RunUsage(
                pass2=PassUsage(
                    prompt_tokens=2000, completion_tokens=300, estimated_prompt_tokens=2400
                )
            )
        )
        md = render_markdown(CodebaseGraph(directory_tree="r/\n", meta=meta))
        assert (
            "> **Run telemetry.** pass 2 prompt: 2000 tokens (graphlm estimated 2400); "
            "output: 300 tokens.\n"
        ) in md
        assert "parser ground truth" not in md

    def test_usage_with_pass2_missing_is_omitted(self):
        from graphlm.models import PassUsage, RunUsage

        meta = self._meta(usage=RunUsage(pass1=PassUsage(estimated_prompt_tokens=5)))
        md = render_markdown(CodebaseGraph(directory_tree="r/\n", meta=meta))
        assert "Run telemetry" not in md

    def test_usage_without_completion_tokens_drops_output_clause(self):
        from graphlm.models import PassUsage, RunUsage

        meta = self._meta(
            usage=RunUsage(pass2=PassUsage(prompt_tokens=10, estimated_prompt_tokens=12))
        )
        md = render_markdown(CodebaseGraph(directory_tree="r/\n", meta=meta))
        assert "pass 2 prompt: 10 tokens (graphlm estimated 12)." in md
        assert "output:" not in md

    def test_faithfulness_only_with_na_ratios(self):
        from graphlm.models import Faithfulness

        meta = self._meta(
            faithfulness=Faithfulness(
                precision=None, recall=None, llm_edges=0, ast_edges=0, matched=0
            )
        )
        md = render_markdown(CodebaseGraph(directory_tree="r/\n", meta=meta))
        assert (
            "> **Run telemetry.** LLM import edges vs parser ground truth: "
            "precision n/a, recall n/a (n=0 LLM / 0 AST, 0 matched).\n"
        ) in md
        assert "pass 2 prompt" not in md

    def test_both_halves_joined(self):
        from graphlm.models import Faithfulness, PassUsage, RunUsage

        meta = self._meta(
            usage=RunUsage(
                pass2=PassUsage(prompt_tokens=None, estimated_prompt_tokens=99)
            ),
            faithfulness=Faithfulness(
                precision=0.9333, recall=0.8125, llm_edges=15, ast_edges=16, matched=14
            ),
        )
        md = render_markdown(CodebaseGraph(directory_tree="r/\n", meta=meta))
        assert (
            "> **Run telemetry.** pass 2 prompt: not reported by endpoint "
            "(graphlm estimated 99). LLM import edges vs parser ground truth: "
            "precision 0.93, recall 0.81 (n=15 LLM / 16 AST, 14 matched).\n"
        ) in md

    def test_line_sits_directly_under_directive(self):
        from graphlm.models import Faithfulness

        meta = self._meta(
            faithfulness=Faithfulness(precision=1.0, recall=1.0, llm_edges=1, ast_edges=1, matched=1)
        )
        md = render_markdown(CodebaseGraph(directory_tree="r/\n", meta=meta))
        lines = md.splitlines()
        directive_end = next(i for i, l in enumerate(lines) if "best-effort" in l)
        assert lines[directive_end + 1].startswith("> **Run telemetry.**")
        assert lines[directive_end + 2] == ""
