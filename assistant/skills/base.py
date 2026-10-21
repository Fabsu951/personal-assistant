"""The building blocks for skills.

A *skill* is a self-contained "specialist" the assistant can use: it bundles a
few tools plus instructions on how to use them. To add a new agent/specialist,
create a new file in this folder with a Skill subclass and register it in
skills/__init__.py.
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo


@dataclass
class ToolContext:
    """Everything a tool handler may need."""
    db: Any
    config: Any
    chat_id: int = 0
    # Files a tool wants sent to the user with the reply: (filename, bytes).
    files: list = field(default_factory=list)


def today(ctx: ToolContext) -> date:
    """Today's date in the user's timezone (not the server's)."""
    return datetime.now(ZoneInfo(ctx.config.timezone)).date()


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict, ToolContext], Any]
    # If True the assistant must get the user's OK (Telegram button) first.
    needs_approval: bool = False
    # Optional: turn the arguments into a human-readable approval message.
    describe: Callable[[dict], str] | None = None

    def to_api(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def summary(self, args: dict) -> str:
        if self.describe:
            try:
                return self.describe(args)
            except Exception:
                pass
        lines = [f"{self.name}:"] + [f"  {k}: {v}" for k, v in args.items()]
        return "\n".join(lines)


@dataclass
class Skill:
    name: str = "base"
    description: str = ""
    instructions: str = ""
    tools: list[Tool] = field(default_factory=list)

    def setup(self, db, config) -> None:
        """Called once at start-up (create tables etc.)."""

    def server_tools(self) -> list[dict]:
        """Anthropic-hosted tools (e.g. web search) this skill wants."""
        return []


def schema(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or []}
