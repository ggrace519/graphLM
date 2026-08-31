"""Tests for the --install-skill agent-guide installer.

Every test injects a temp ``home`` (or ``project_dir``) so no test ever writes
into the real ``~/.claude`` / ``~/.codex``.
"""

import pytest

from graphlm.skills import (
    SUPPORTED_HARNESSES,
    SkillInstallResult,
    install_skill,
)


class TestInstallSkill:
    def test_claude_global_writes_skill_md(self, tmp_path):
        result = install_skill("claude", home=tmp_path)
        expected = tmp_path / ".claude" / "skills" / "graphlm" / "SKILL.md"
        assert result.path == expected
        assert result.skipped is False
        assert expected.is_file()
        content = expected.read_text()
        # Proper Claude skill frontmatter.
        assert content.startswith("---\n")
        assert "name: graphlm" in content
        assert "description:" in content
        # Points at the *current* map location, not the old project-root path.
        assert ".graphlm/GRAPH.md" in content
        # Tells the agent to regenerate when missing/stale (graceful no-op).
        assert "graphlm ." in content

    def test_codex_global_writes_guide_and_note(self, tmp_path):
        result = install_skill("codex", home=tmp_path)
        expected = tmp_path / ".codex" / "graphlm.md"
        assert result.path == expected
        assert expected.is_file()
        # Codex guide is plain markdown (no frontmatter).
        assert not expected.read_text().startswith("---")
        assert ".graphlm/GRAPH.md" in expected.read_text()
        # A note tells the user how to wire it into their own AGENTS.md.
        assert result.note is not None
        assert "AGENTS.md" in result.note

    def test_idempotent_skip_without_force(self, tmp_path):
        first = install_skill("claude", home=tmp_path)
        assert first.skipped is False
        first.path.write_text("SENTINEL — user edited")
        second = install_skill("claude", home=tmp_path)
        assert second.skipped is True
        # Existing file is left untouched.
        assert second.path.read_text() == "SENTINEL — user edited"

    def test_force_overwrites(self, tmp_path):
        install_skill("claude", home=tmp_path)
        path = tmp_path / ".claude" / "skills" / "graphlm" / "SKILL.md"
        path.write_text("SENTINEL")
        result = install_skill("claude", home=tmp_path, force=True)
        assert result.skipped is False
        assert result.path.read_text() != "SENTINEL"
        assert "name: graphlm" in result.path.read_text()

    def test_local_claude_writes_into_project(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        home = tmp_path / "home"
        result = install_skill(
            "claude", project_dir=project, local=True, home=home
        )
        assert result.path == project / ".claude" / "skills" / "graphlm" / "SKILL.md"
        assert result.path.is_file()
        # Global home is NOT touched.
        assert not (home / ".claude").exists()

    def test_local_codex_writes_beside_project(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        result = install_skill(
            "codex", project_dir=project, local=True, home=tmp_path / "home"
        )
        assert result.path == project / "graphlm-agent.md"
        assert result.path.is_file()

    def test_unknown_harness_raises(self, tmp_path):
        with pytest.raises(ValueError, match="unknown harness"):
            install_skill("emacs", home=tmp_path)

    def test_local_without_project_dir_raises(self, tmp_path):
        with pytest.raises(ValueError, match="requires a project_dir"):
            install_skill("claude", local=True, home=tmp_path)

    def test_supported_harnesses_constant(self):
        assert "claude" in SUPPORTED_HARNESSES
        assert "codex" in SUPPORTED_HARNESSES

    def test_result_is_dataclass(self, tmp_path):
        result = install_skill("claude", home=tmp_path)
        assert isinstance(result, SkillInstallResult)
        assert result.harness == "claude"

    def test_symlink_target_refused_not_clobbered(self, tmp_path):
        # A symlink at the target (to a real outside file) must NOT be written
        # through — that would clobber a file graphlm didn't create (#33).
        outside = tmp_path / "important.txt"
        outside.write_text("USER DATA")
        target = tmp_path / "home" / ".claude" / "skills" / "graphlm" / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.symlink_to(outside)

        with pytest.raises(ValueError, match="symlink"):
            install_skill("claude", home=tmp_path / "home", force=True)
        # The outside file is untouched.
        assert outside.read_text() == "USER DATA"

    def test_broken_symlink_target_refused(self, tmp_path):
        # A *broken* symlink: .exists() is False, so without the guard the
        # no-force path would fall through and create a real file at the link's
        # (missing) target. Must be refused instead.
        target = tmp_path / "home" / ".claude" / "skills" / "graphlm" / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.symlink_to(tmp_path / "does-not-exist")

        with pytest.raises(ValueError, match="symlink"):
            install_skill("claude", home=tmp_path / "home")
