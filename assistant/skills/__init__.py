"""Skill registry.

HOW TO ADD A NEW AGENT / SPECIALIST
1. Copy skills/_template.py to skills/<your_skill>.py and fill it in.
2. Add it to AVAILABLE below with a short key.
3. Add the key to ENABLED_SKILLS in your settings (e.g. "google,tasks,research,admin,fitness").
"""
from .admin import AdminSkill
from .base import Skill
from .budget import BudgetSkill
from .career import CareerSkill
from .content import ContentSkill
from .fitness import FitnessSkill
from .google_workspace import GoogleSkill
from .habits import HabitsSkill
from .ideas import IdeasSkill
from .journal import JournalSkill
from .nutrition import NutritionSkill
from .onedrive import OneDriveSkill
from .people import PeopleSkill
from .research import ResearchSkill
from .study import StudySkill
from .tasks import TasksSkill
from .travel import TravelSkill
from .voice_settings import VoiceSkill
from .writing import WritingSkill

AVAILABLE = {
    "google": GoogleSkill,
    "tasks": TasksSkill,
    "research": ResearchSkill,
    "admin": AdminSkill,
    "fitness": FitnessSkill,
    "voice": VoiceSkill,
    "travel": TravelSkill,
    "onedrive": OneDriveSkill,
    "study": StudySkill,
    "writing": WritingSkill,
    "ideas": IdeasSkill,
    "content": ContentSkill,
    "career": CareerSkill,
    "budget": BudgetSkill,
    "nutrition": NutritionSkill,
    "habits": HabitsSkill,
    "people": PeopleSkill,
    "journal": JournalSkill,
}
CORE = ["voice"]  # always on, whatever ENABLED_SKILLS says


def load_skills(names: list[str], db, config) -> list[Skill]:
    skills = []
    for name in dict.fromkeys(names + CORE):  # no duplicates, order kept
        cls = AVAILABLE.get(name)
        if cls is None:
            raise ValueError(f"Unknown skill '{name}'. Available: {', '.join(AVAILABLE)}")
        skill = cls()
        skill.setup(db, config)
        skills.append(skill)
    return skills
