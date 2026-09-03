"""Tests for the CLI."""

import re
import sys
import types
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from graphlm import GraphResult
from graphlm.cli import app, output_destination
from graphlm.models import CodebaseGraph
from graphlm.render import WriteResult, write_outputs

runner = CliRunner()

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    """Strip ANSI color codes so flag names are searchable in Rich help."""
    return _ANSI.sub("", text)


class TestCLI:
    def test_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Analyze a project directory" in result.stdout or "project directory" in result.stdout

    def test_version_flag(self):
        # --version is eager: it prints and exits 0 without needing project_dir.
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        out = result.stdout + result.stderr
        assert "graphlm" in out
        # Never prints a bare "None" (the source-checkout fallback path).
        assert "None" not in out

    def test_version_short_flag(self):
        result = runner.invoke(app, ["-V"])
        assert result.exit_code == 0
        assert "graphlm" in (result.stdout + result.stderr)

    def test_install_skill_without_project_dir(self, tmp_path, monkeypatch):
        # The whole point: --install-skill works with no PROJECT_DIR.
        monkeypatch.setenv("HOME", str(tmp_path))
        result = runner.invoke(app, ["--install-skill", "claude"])
        assert result.exit_code == 0, result.stdout + result.stderr
        assert (tmp_path / ".claude" / "skills" / "graphlm" / "SKILL.md").is_file()

    def test_install_skill_unknown_harness(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        result = runner.invoke(app, ["--install-skill", "vim"])
        assert result.exit_code == 2
        assert "unknown harness" in (result.stdout + result.stderr)

    def test_serve_flag_in_help(self):
        result = runner.invoke(app, ["--help"])
        assert "--serve" in _plain(result.stdout)

    def test_serve_without_map_exits_2_before_needing_mcp(self, tmp_path, monkeypatch):
        # The map check runs first, so a user without the extra still gets the
        # actionable message (run graphlm) rather than an install hint.
        monkeypatch.setitem(sys.modules, "mcp", None)
        result = runner.invoke(app, [str(tmp_path), "--serve"])
        assert result.exit_code == 2
        assert "run `graphlm .`" in (result.stdout + result.stderr)

    def test_serve_without_mcp_extra_exits_2_with_install_hint(self, tmp_path, monkeypatch):
        (tmp_path / ".graphlm").mkdir()
        write_outputs(CodebaseGraph(directory_tree=""), tmp_path / ".graphlm", html=False, diff=False)
        monkeypatch.setitem(sys.modules, "mcp", None)
        monkeypatch.setitem(sys.modules, "graphlm.mcp_server", None)
        result = runner.invoke(app, [str(tmp_path), "--serve"])
        assert result.exit_code == 2
        assert "graphlm[mcp]" in (result.stdout + result.stderr)

    def test_serve_runs_server_with_resolved_paths(self, tmp_path, monkeypatch):
        # -o is honored for the map location, and PROJECT_DIR defaults to cwd.
        out = tmp_path / "maps"
        write_outputs(CodebaseGraph(directory_tree=""), out, html=False, diff=False)
        calls = []
        fake = types.ModuleType("graphlm.mcp_server")
        fake.run_server = lambda project, json_path: calls.append((project, json_path))
        monkeypatch.setitem(sys.modules, "graphlm.mcp_server", fake)
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["--serve", "-o", str(out)])
        assert result.exit_code == 0, result.stdout + result.stderr
        assert calls == [(tmp_path.resolve(), (out / "GRAPH.json").resolve())]

    def test_install_skill_local_needs_project_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        result = runner.invoke(app, ["--install-skill", "claude", "--skill-local"])
        assert result.exit_code == 2
        assert "PROJECT_DIR" in (result.stdout + result.stderr)

    def test_no_args_errors_cleanly(self):
        # project_dir is optional (so --install-skill can run alone), but the
        # analyze path still requires it — with a clean message, not a traceback.
        result = runner.invoke(app, [])
        assert result.exit_code == 2
        assert "PROJECT_DIR" in (result.stdout + result.stderr)

    def test_install_skill_idempotent_skip_via_cli(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        first = runner.invoke(app, ["--install-skill", "claude"])
        assert first.exit_code == 0
        second = runner.invoke(app, ["--install-skill", "claude"])
        assert second.exit_code == 0
        out = second.stdout + second.stderr
        assert "Skipped" in out and "--skill-force" in out

    def test_install_skill_codex_prints_note_via_cli(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        result = runner.invoke(app, ["--install-skill", "codex"])
        assert result.exit_code == 0, result.stdout + result.stderr
        out = result.stdout + result.stderr
        # The wiring note (Codex won't auto-read the standalone guide).
        assert "AGENTS.md" in out
        assert (tmp_path / ".codex" / "graphlm.md").is_file()

    def test_install_skill_symlink_exits_cleanly(self, tmp_path, monkeypatch):
        # A symlink at the target → clean exit-2 error, not a traceback (#33).
        monkeypatch.setenv("HOME", str(tmp_path))
        target = tmp_path / ".claude" / "skills" / "graphlm" / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.symlink_to(tmp_path / "elsewhere.txt")
        result = runner.invoke(app, ["--install-skill", "claude", "--skill-force"])
        assert result.exit_code == 2
        assert "symlink" in (result.stdout + result.stderr)

    def test_nonexistent_directory(self):
        result = runner.invoke(app, ["/nonexistent/directory"])
        assert result.exit_code == 1
        combined = result.stdout + result.stderr
        assert "not a directory" in combined or "Error:" in combined

    def test_dry_run_small_project(self, small_project):
        result = runner.invoke(app, [str(small_project), "--dry-run"])
        assert result.exit_code == 0
        assert "Dry run complete" in result.stdout or "Dry run complete" in result.stderr
        assert (
            "Files selected for pass-2 analysis:" in result.stdout
            or "Files selected for pass-2 analysis:" in result.stderr
        )

    def test_dry_run_medium_project(self, medium_project):
        result = runner.invoke(app, [str(medium_project), "--dry-run"])
        assert result.exit_code == 0
        assert "Dry run complete" in result.stdout or "Dry run complete" in result.stderr

    def test_dry_run_with_no_tests(self, medium_project):
        result = runner.invoke(app, [str(medium_project), "--dry-run", "--no-tests"])
        assert result.exit_code == 0
        assert "Dry run complete" in result.stdout or "Dry run complete" in result.stderr

    def test_dry_run_with_exclude(self, large_project):
        result = runner.invoke(
            app, [str(large_project), "--dry-run", "--exclude", "*.css"]
        )
        assert result.exit_code == 0
        assert "Dry run complete" in result.stdout or "Dry run complete" in result.stderr

    def test_dry_run_with_custom_max_files(self, small_project):
        result = runner.invoke(app, [str(small_project), "--dry-run", "--max-files", "2"])
        assert result.exit_code == 0
        assert "Dry run complete" in result.stdout or "Dry run complete" in result.stderr

    def test_dry_run_with_output_dir(self, small_project, tmp_path):
        output = tmp_path / "output"
        result = runner.invoke(
            app, [str(small_project), "--dry-run", "-o", str(output)]
        )
        # Dry run exits early, but we can verify it doesn't crash with -o
        assert result.exit_code == 0

    def test_missing_project_dir_shows_error(self):
        result = runner.invoke(app, [])
        assert result.exit_code != 0

    def test_dry_run_no_html_with_output_dir(self, small_project, tmp_path):
        result = runner.invoke(
            app,
            [str(small_project), "--dry-run", "--no-html", "-o", str(tmp_path)],
        )
        assert result.exit_code == 0
        assert "Dry run complete" in result.stdout or "Dry run complete" in result.stderr
        assert not (tmp_path / "GRAPH.html").exists()
        assert not (tmp_path / "GRAPH.md").exists()
        assert not (tmp_path / "GRAPH.json").exists()

    def test_dry_run_ast_cyclic_project(self):
        cyclic_project = Path(__file__).parent / "fixtures" / "cyclic_project"
        result = runner.invoke(app, [str(cyclic_project), "--dry-run"])
        assert result.exit_code == 0
        assert "Dry run complete" in result.stdout or "Dry run complete" in result.stderr

    def test_help_lists_no_ast(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        help_text = _plain(result.stdout)
        assert "--no-ast" in help_text
        assert "--ast" not in help_text.replace("--no-ast", "")

    def test_help_lists_no_diff(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "--no-diff" in _plain(result.stdout)

    def test_dry_run_no_ast(self):
        cyclic_project = Path(__file__).parent / "fixtures" / "cyclic_project"
        result = runner.invoke(app, [str(cyclic_project), "--dry-run", "--no-ast"])
        assert result.exit_code == 0
        assert "Dry run complete" in result.stdout or "Dry run complete" in result.stderr

    def test_dry_run_reports_ast_edge_count_not_llm_edges(self):
        # A dry run has no LLM edges, so the old "0 import edges" figure was
        # always 0 and misread as "no imports found". The AST count is what a
        # dry run actually measured.
        cyclic_project = Path(__file__).parent / "fixtures" / "cyclic_project"
        result = runner.invoke(app, [str(cyclic_project), "--dry-run"])
        assert result.exit_code == 0
        out = result.stdout + result.stderr
        assert "AST import edges: 4" in out
        assert "import edges," not in out  # the misleading LLM-field count is gone

    def test_dry_run_no_ast_reports_ast_off(self):
        cyclic_project = Path(__file__).parent / "fixtures" / "cyclic_project"
        result = runner.invoke(app, [str(cyclic_project), "--dry-run", "--no-ast"])
        assert result.exit_code == 0
        assert "AST import edges: AST off" in result.stdout + result.stderr

    def test_full_run_prints_telemetry_lines(self, small_project, tmp_path):
        from graphlm.models import Faithfulness, GraphMeta, PassUsage, RunUsage

        def fake_write(self, output_dir, *, include_html=True, include_diff=True):
            dest = Path(output_dir).resolve()
            return WriteResult(dest / "GRAPH.md", dest / "GRAPH.json", None)

        meta = GraphMeta(
            created_at="2026-09-02T00:00:00Z",
            usage=RunUsage(
                pass2=PassUsage(
                    prompt_tokens=2500, completion_tokens=400, estimated_prompt_tokens=3000
                )
            ),
            faithfulness=Faithfulness(
                precision=0.5, recall=1.0, llm_edges=2, ast_edges=1, matched=1
            ),
        )

        def fake_generate_graph(**_kwargs):
            return GraphResult(CodebaseGraph(directory_tree="t/\n", meta=meta), 1, 1, 1)

        with (
            patch("graphlm.generate_graph", fake_generate_graph),
            patch.object(GraphResult, "write", fake_write),
        ):
            result = runner.invoke(app, [str(small_project), "-o", str(tmp_path)])

        assert result.exit_code == 0, result.stdout + result.stderr
        out = result.stdout + result.stderr
        assert "Usage: pass 2 prompt: 2500 tokens (graphlm estimated 3000); output: 400 tokens" in out
        assert "Faithfulness: LLM import edges vs parser ground truth: precision 0.50, recall 1.00 (n=2 LLM / 1 AST, 1 matched)" in out

    def test_full_run_without_telemetry_prints_no_telemetry_lines(self, small_project, tmp_path):
        # meta present but nothing measured (e.g. a library graph): no Usage /
        # Faithfulness lines rather than "None" placeholders.
        from graphlm.models import GraphMeta

        def fake_write(self, output_dir, *, include_html=True, include_diff=True):
            dest = Path(output_dir).resolve()
            return WriteResult(dest / "GRAPH.md", dest / "GRAPH.json", None)

        def fake_generate_graph(**_kwargs):
            graph = CodebaseGraph(
                directory_tree="t/\n", meta=GraphMeta(created_at="2026-09-02T00:00:00Z")
            )
            return GraphResult(graph, 1, 1, 1)

        with (
            patch("graphlm.generate_graph", fake_generate_graph),
            patch.object(GraphResult, "write", fake_write),
        ):
            result = runner.invoke(app, [str(small_project), "-o", str(tmp_path)])

        assert result.exit_code == 0, result.stdout + result.stderr
        out = result.stdout + result.stderr
        assert "Usage:" not in out
        assert "Faithfulness:" not in out

    def test_output_destination_defaults_to_dot_graphlm(self, tmp_path):
        project = tmp_path / "scanned"
        other = tmp_path / "elsewhere"
        # Default: a .graphlm/ subdir of the scanned project.
        assert output_destination(project, None) == project / ".graphlm"
        # -o is honored literally (no .graphlm appended).
        assert output_destination(project, str(other)) == other

    def test_cli_writes_into_dot_graphlm_not_cwd(
        self, small_project, tmp_path, monkeypatch
    ):
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        recorded: dict[str, Path] = {}

        def fake_write(self, output_dir, *, include_html=True, include_diff=True):
            dest = Path(output_dir).resolve()
            recorded["dest"] = dest
            md = dest / "GRAPH.md"
            js = dest / "GRAPH.json"
            html = dest / "GRAPH.html" if include_html else None
            return WriteResult(md, js, html)

        def fake_generate_graph(**_kwargs):
            return GraphResult(CodebaseGraph(directory_tree="t/\n"), 1, 1, 1)

        with (
            patch("graphlm.generate_graph", fake_generate_graph),
            patch.object(GraphResult, "write", fake_write),
        ):
            result = runner.invoke(app, [str(small_project)])

        assert result.exit_code == 0, result.stdout + result.stderr
        # Default output lands in the scanned project's .graphlm/ subdir.
        assert recorded["dest"] == (small_project / ".graphlm").resolve()
        assert not (cwd / "GRAPH.md").exists()

    def test_cli_dash_o_overrides_project_dir(
        self, small_project, tmp_path, monkeypatch
    ):
        cwd = tmp_path / "cwd"
        out = tmp_path / "out"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        recorded: dict[str, Path] = {}

        def fake_write(self, output_dir, *, include_html=True, include_diff=True):
            dest = Path(output_dir).resolve()
            recorded["dest"] = dest
            md = dest / "GRAPH.md"
            js = dest / "GRAPH.json"
            return WriteResult(md, js, None)

        def fake_generate_graph(**_kwargs):
            return GraphResult(CodebaseGraph(directory_tree="t/\n"), 1, 1, 1)

        with (
            patch("graphlm.generate_graph", fake_generate_graph),
            patch.object(GraphResult, "write", fake_write),
        ):
            result = runner.invoke(app, [str(small_project), "-o", str(out)])

        assert result.exit_code == 0, result.stdout + result.stderr
        assert recorded["dest"] == out.resolve()

    def test_cli_reports_diff_outputs(self, small_project, tmp_path):
        def fake_write(self, output_dir, *, include_html=True, include_diff=True):
            dest = Path(output_dir)
            return WriteResult(
                dest / "GRAPH.md",
                dest / "GRAPH.json",
                dest / "GRAPH.html",
                diff_md=dest / "GRAPH_DIFF.md",
                diff_json=dest / "GRAPH_DIFF.json",
            )

        def fake_generate_graph(**_kwargs):
            return GraphResult(CodebaseGraph(directory_tree="t/\n"), 1, 1, 1)

        with (
            patch("graphlm.generate_graph", fake_generate_graph),
            patch.object(GraphResult, "write", fake_write),
        ):
            result = runner.invoke(
                app, [str(small_project), "-o", str(tmp_path / "out")]
            )

        assert result.exit_code == 0, result.stdout + result.stderr
        assert "Diff (md):" in result.stderr
        assert "Diff (json):" in result.stderr
        # Labels alone would let hard-coded or incorrect output paths pass.
        assert str(tmp_path / "out" / "GRAPH_DIFF.md") in result.stderr
        assert str(tmp_path / "out" / "GRAPH_DIFF.json") in result.stderr

    def test_cli_no_diff_disables_diff_and_omits_output_lines(
        self, small_project, tmp_path
    ):
        recorded: dict[str, bool] = {}

        def fake_write(self, output_dir, *, include_html=True, include_diff=True):
            recorded["write_include_diff"] = include_diff
            dest = Path(output_dir)
            return WriteResult(dest / "GRAPH.md", dest / "GRAPH.json", None)

        def fake_generate_graph(**kwargs):
            recorded["generate_include_diff"] = kwargs["include_diff"]
            return GraphResult(CodebaseGraph(directory_tree="t/\n"), 1, 1, 1)

        with (
            patch("graphlm.generate_graph", fake_generate_graph),
            patch.object(GraphResult, "write", fake_write),
        ):
            result = runner.invoke(
                app,
                [str(small_project), "--no-diff", "-o", str(tmp_path / "out")],
            )

        assert result.exit_code == 0, result.stdout + result.stderr
        assert recorded == {
            "generate_include_diff": False,
            "write_include_diff": False,
        }
        assert "Diff (md):" not in result.stderr
        assert "Diff (json):" not in result.stderr

    def test_help_lists_no_skeleton(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        help_text = _plain(result.stdout)
        assert "--no-skeleton" in help_text
        assert "--skeleton" not in help_text.replace("--no-skeleton", "")

    def test_no_skeleton_threads_through(self, small_project, tmp_path):
        recorded: dict[str, bool] = {}

        def fake_write(self, output_dir, *, include_html=True, include_diff=True):
            dest = Path(output_dir)
            return WriteResult(dest / "GRAPH.md", dest / "GRAPH.json", None)

        def fake_generate_graph(**kwargs):
            recorded["skeleton"] = kwargs["skeleton"]
            return GraphResult(CodebaseGraph(directory_tree="t/\n"), 1, 1, 1)

        with (
            patch("graphlm.generate_graph", fake_generate_graph),
            patch.object(GraphResult, "write", fake_write),
        ):
            result = runner.invoke(
                app, [str(small_project), "--no-skeleton", "-o", str(tmp_path / "out")]
            )
            assert result.exit_code == 0, result.stdout + result.stderr
            assert recorded == {"skeleton": False}

            result = runner.invoke(app, [str(small_project), "-o", str(tmp_path / "out")])
            assert result.exit_code == 0, result.stdout + result.stderr
            assert recorded == {"skeleton": True}

    def test_dry_run_no_skeleton(self):
        project = Path(__file__).parent / "fixtures" / "skeleton_project"
        result = runner.invoke(app, [str(project), "--dry-run", "--no-skeleton"])
        assert result.exit_code == 0
        assert "Dry run complete" in result.stdout or "Dry run complete" in result.stderr
