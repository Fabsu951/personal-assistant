"""Skill registry.

HOW TO ADD A NEW AGENT / SPECIALIST
1. Copy skills/_template.py to skills/<your_skill>.py and fill it in.
2. Add it to AVAILABLE below with a short key.
3. Add the key to ENABLED_SKILLS in your settings (e.g. "google,tasks,research,admin,fitness").
"""
from .admin import AdminSkill
from .base import Skill
from .google_workspace import GoogleSkill
from .research import ResearchSkill
from .tasks import TasksSkill

AVAILABLE = {
    "google": GoogleSkill,
    "tasks": TasksSkill,
    "research": ResearchSkill,
    "admin": AdminSkill,
}


def load_skills(names: list[str], db, config) -> list[Skill]:
    skills = []
    for name in names:
        cls = AVAILABLE.get(name)
        if cls is None:
            raise ValueError(f"Unknown skill '{name}'. Available: {', '.join(AVAILABLE)}")
        skill = cls()
        skill.setup(db, config)
        skills.append(skill)
    return skills
