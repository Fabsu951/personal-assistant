"""TEMPLATE for a new skill. Copy this file, rename the class, and register it
in skills/__init__.py. (Or just ask Claude: "add a skill that does X".)"""
from .base import Skill, Tool, schema


def say_hello(args, ctx):
    # args = what Claude decided to pass in; ctx.db = database; ctx.config = settings
    return f"Hello, {args['name']}!"


class TemplateSkill(Skill):
    def __init__(self):
        super().__init__(
            name="Template",
            description="What this specialist does.",
            instructions="When and how the assistant should use these tools.",
            tools=[
                Tool("say_hello", "Greets someone by name.",
                     schema({"name": {"type": "string"}}, ["name"]), say_hello,
                     needs_approval=False),  # True = ask the user before running
            ],
        )

    def setup(self, db, config):
        # Create any database tables you need here.
        pass
