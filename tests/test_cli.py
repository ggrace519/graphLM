"""Tests for the CLI."""

import re
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from graphlm import GraphResult
from graphlm.cli import app, output_destination
from graphlm.models import CodebaseGraph
from graphlm.render import WriteResult

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
        assert "Files scanned:" in result.stdout or "Files scanned:" in result.stderr

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
