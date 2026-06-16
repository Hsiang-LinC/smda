import pytest

from smda_scheduler.skill_loader import SkillNotFoundError, load_skill_methodology


def test_loads_skill_body_stripping_frontmatter(tmp_path):
    skill = tmp_path / "tdd" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: tdd\n---\n\n# TDD\nRed green refactor.\n")
    body = load_skill_methodology(tmp_path, "tdd")
    assert "Red green refactor." in body
    assert "name: tdd" not in body


def test_loads_flat_md_layout(tmp_path):
    (tmp_path / "diagnose.md").write_text("# Diagnose\nReproduce then fix.\n")
    assert "Reproduce then fix." in load_skill_methodology(tmp_path, "diagnose")


def test_body_without_frontmatter_passthrough(tmp_path):
    skill = tmp_path / "x" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# X\nNo frontmatter here.\n")
    assert "No frontmatter here." in load_skill_methodology(tmp_path, "x")


def test_missing_skill_raises(tmp_path):
    with pytest.raises(SkillNotFoundError):
        load_skill_methodology(tmp_path, "nope")
