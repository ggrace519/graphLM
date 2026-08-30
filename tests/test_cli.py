"""Tests for the CLI."""

import re
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from graphlm import GraphResult
from graphlm.cli import app, output_destination
from graphlm.models import CodebaseGraph

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

    def test_dry_run_no_ast(self):
        cyclic_project = Path(__file__).parent / "fixtures" / "cyclic_project"
        result = runner.invoke(app, [str(cyclic_project), "--dry-run", "--no-ast"])
        assert result.exit_code == 0
        assert "Dry run complete" in result.stdout or "Dry run complete" in result.stderr

    def test_output_destination_defaults_to_project(self, tmp_path):
        project = tmp_path / "scanned"
        other = tmp_path / "elsewhere"
        assert output_destination(project, None) == project
        assert output_destination(project, str(other)) == other

    def test_cli_writes_into_scanned_project_not_cwd(
        self, small_project, tmp_path, monkeypatch
    ):
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        recorded: dict[str, Path] = {}

        def fake_write(self, output_dir, *, include_html=True):
            dest = Path(output_dir).resolve()
            recorded["dest"] = dest
            md = dest / "GRAPH.md"
            js = dest / "GRAPH.json"
            html = dest / "GRAPH.html" if include_html else None
            return md, js, html

        def fake_generate_graph(**_kwargs):
            return GraphResult(CodebaseGraph(directory_tree="t/\n"), 1, 1, 1)

        with (
            patch("graphlm.generate_graph", fake_generate_graph),
            patch.object(GraphResult, "write", fake_write),
        ):
            result = runner.invoke(app, [str(small_project)])

        assert result.exit_code == 0, result.stdout + result.stderr
        assert recorded["dest"] == small_project.resolve()
        assert not (cwd / "GRAPH.md").exists()

    def test_cli_dash_o_overrides_project_dir(
        self, small_project, tmp_path, monkeypatch
    ):
        cwd = tmp_path / "cwd"
        out = tmp_path / "out"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        recorded: dict[str, Path] = {}

        def fake_write(self, output_dir, *, include_html=True):
            dest = Path(output_dir).resolve()
            recorded["dest"] = dest
            md = dest / "GRAPH.md"
            js = dest / "GRAPH.json"
            return md, js, None

        def fake_generate_graph(**_kwargs):
            return GraphResult(CodebaseGraph(directory_tree="t/\n"), 1, 1, 1)

        with (
            patch("graphlm.generate_graph", fake_generate_graph),
            patch.object(GraphResult, "write", fake_write),
        ):
            result = runner.invoke(app, [str(small_project), "-o", str(out)])

        assert result.exit_code == 0, result.stdout + result.stderr
        assert recorded["dest"] == out.resolve()
