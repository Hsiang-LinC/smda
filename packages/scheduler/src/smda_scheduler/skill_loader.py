from __future__ import annotations

from pathlib import Path


class SkillNotFoundError(FileNotFoundError):
    """Raised when a declared methodology skill cannot be resolved."""


def load_skill_methodology(skills_dir: Path, skill_id: str) -> str:
    """Return a skill's methodology body from the consumer repo's skills_dir.

    Resolves the marketplace layout `<skills_dir>/<skill_id>/SKILL.md` first, then
    a flat `<skills_dir>/<skill_id>.md`. Leading YAML frontmatter is stripped.
    """
    for path in (skills_dir / skill_id / "SKILL.md", skills_dir / f"{skill_id}.md"):
        if path.is_file():
            if not path.resolve().is_relative_to(skills_dir.resolve()):
                raise SkillNotFoundError(f"Skill escapes configured directory: {skill_id}")
            return _strip_frontmatter(path.read_text(encoding="utf-8")).strip()
    raise SkillNotFoundError(skill_id)


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    lines = text.splitlines()
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[index + 1 :])
    return text
