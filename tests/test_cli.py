"""Tests for the CLI."""

from pathlib import Path

from typer.testing import CliRunner

from graphlm.cli import app

runner = CliRunner()


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
        assert "--no-ast" in result.stdout
        assert "--ast" not in result.stdout.replace("--no-ast", "")

    def test_dry_run_no_ast(self):
        cyclic_project = Path(__file__).parent / "fixtures" / "cyclic_project"
        result = runner.invoke(app, [str(cyclic_project), "--dry-run", "--no-ast"])
        assert result.exit_code == 0
        assert "Dry run complete" in result.stdout or "Dry run complete" in result.stderr
