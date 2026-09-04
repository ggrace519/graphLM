"""Tests for ``graphlm --upgrade`` (no network — the installer is injected)."""

from __future__ import annotations

import subprocess

from graphlm.upgrade import (
    _collapse_extras,
    _spec,
    detect_installer,
    installed_extras,
    make_plan,
    run_upgrade,
)


class TestCollapseExtras:
    def test_all_language_extras_collapse(self):
        assert _collapse_extras(
            ("js", "java", "rust", "csharp", "cpp", "go", "php", "mcp")
        ) == ("mcp", "all")

    def test_partial_stays_listed(self):
        assert _collapse_extras(("js", "mcp")) == ("mcp", "js")

    def test_spec_empty(self):
        assert _spec(()) == "graphlm"

    def test_spec_joined(self):
        assert _spec(("mcp", "all")) == "graphlm[mcp,all]"


class TestDetectInstaller:
    def test_uv_tool_path(self, tmp_path):
        exe = tmp_path / "uv" / "tools" / "graphlm" / "bin" / "python"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        assert detect_installer(exe) == "uv-tool"

    def test_pipx_path(self, tmp_path):
        exe = tmp_path / "pipx" / "venvs" / "graphlm" / "bin" / "python"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        assert detect_installer(exe) == "pipx"


class TestInstalledExtras:
    def test_uv_receipt(self, tmp_path):
        rec = tmp_path / "graphlm" / "uv-receipt.toml"
        rec.parent.mkdir(parents=True)
        rec.write_text(
            '[tool]\nrequirements = [{ name = "graphlm", extras = ["all", "mcp"] }]\n'
        )
        extras = installed_extras(installer="uv-tool", uv_tools_root=tmp_path)
        assert extras == ("mcp", "all")

    def test_pipx_metadata_list(self, tmp_path):
        meta = tmp_path / "graphlm" / "pipx_metadata.json"
        meta.parent.mkdir(parents=True)
        meta.write_text('{"main_package": {"extras": ["js", "mcp"]}}\n')
        extras = installed_extras(installer="pipx", pipx_venvs_root=tmp_path)
        assert extras == ("mcp", "js")

    def test_pipx_metadata_spec_string(self, tmp_path):
        meta = tmp_path / "graphlm" / "pipx_metadata.json"
        meta.parent.mkdir(parents=True)
        meta.write_text(
            '{"main_package": {"package_or_url": "graphlm[all,mcp]"}}\n'
        )
        extras = installed_extras(installer="pipx", pipx_venvs_root=tmp_path)
        assert extras == ("mcp", "all")

    def test_missing_receipt_falls_back_to_probe(self, tmp_path):
        extras = installed_extras(installer="uv-tool", uv_tools_root=tmp_path)
        assert isinstance(extras, tuple)


class TestMakePlan:
    def test_uv_tool_upgrade_argv(self, tmp_path):
        exe = tmp_path / "uv" / "tools" / "graphlm" / "bin" / "python"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        rec = tmp_path / "tools" / "graphlm" / "uv-receipt.toml"
        rec.parent.mkdir(parents=True)
        rec.write_text(
            '[tool]\nrequirements = [{ name = "graphlm", extras = ["all"] }]\n'
        )
        plan = make_plan(
            executable=exe,
            which=lambda n: "/usr/bin/uv" if n == "uv" else None,
            uv_tools_root=tmp_path / "tools",
        )
        assert plan.installer == "uv-tool"
        assert plan.argv == ("/usr/bin/uv", "tool", "upgrade", "graphlm")
        assert "all" in plan.message

    def test_uv_missing_binary_refuses(self, tmp_path):
        exe = tmp_path / "uv" / "tools" / "graphlm" / "bin" / "python"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        plan = make_plan(executable=exe, which=lambda n: None)
        assert plan.argv == ()
        assert "uv" in plan.message

    def test_pipx_upgrade_argv(self, tmp_path):
        exe = tmp_path / "pipx" / "venvs" / "graphlm" / "bin" / "python"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        plan = make_plan(
            executable=exe,
            which=lambda n: "/usr/bin/pipx" if n == "pipx" else None,
        )
        assert plan.installer == "pipx"
        assert plan.argv == ("/usr/bin/pipx", "upgrade", "graphlm")

    def test_source_checkout_refuses(self, tmp_path, monkeypatch):
        # Pretend graphlm.__file__ is this repo, not site-packages.
        import graphlm as pkg

        monkeypatch.setattr(
            pkg, "__file__", str(tmp_path / "graphLM" / "graphlm" / "__init__.py")
        )
        exe = tmp_path / "graphLM" / ".venv" / "bin" / "python"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        plan = make_plan(executable=exe, which=lambda n: None)
        assert plan.installer == "source"
        assert plan.argv == ()
        assert "source checkout" in plan.message

    def test_pip_restates_extras(self, tmp_path, monkeypatch):
        import graphlm as pkg

        monkeypatch.setattr(
            pkg,
            "__file__",
            str(tmp_path / "lib" / "site-packages" / "graphlm" / "__init__.py"),
        )
        exe = tmp_path / "venv" / "bin" / "python"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        monkeypatch.setattr(
            "graphlm.upgrade.installed_extras",
            lambda **k: ("mcp", "all"),
        )
        plan = make_plan(executable=exe, which=lambda n: None)
        assert plan.installer == "pip"
        assert plan.argv[1:] == ("-m", "pip", "install", "--upgrade", "graphlm[mcp,all]")


class TestRunUpgrade:
    def test_runs_argv_and_returns_code(self, tmp_path):
        exe = tmp_path / "uv" / "tools" / "graphlm" / "bin" / "python"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        calls: list[list[str]] = []

        def fake_run(argv):
            calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0)

        lines: list[str] = []
        code = run_upgrade(
            executable=exe,
            which=lambda n: "/bin/uv" if n == "uv" else None,
            runner=fake_run,
            echo=lines.append,
        )
        assert code == 0
        assert calls == [["/bin/uv", "tool", "upgrade", "graphlm"]]
        assert any("uv tool" in s for s in lines)

    def test_source_returns_2_without_running(self, tmp_path, monkeypatch):
        import graphlm as pkg

        monkeypatch.setattr(
            pkg, "__file__", str(tmp_path / "src" / "graphlm" / "__init__.py")
        )
        exe = tmp_path / "src" / ".venv" / "bin" / "python"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        ran = []
        code = run_upgrade(
            executable=exe,
            which=lambda n: None,
            runner=lambda argv: ran.append(argv) or subprocess.CompletedProcess(argv, 0),
            echo=lambda s: None,
        )
        assert code == 2
        assert ran == []
