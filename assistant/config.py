"""All settings come from environment variables (see .env.example)."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass
class Config:
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    model: str = field(default_factory=lambda: os.getenv("MODEL", "claude-sonnet-5-5"))
    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    # Only this Telegram user may talk to the bot. Leave empty on first run:
    # the bot will tell you your ID.
    owner_id: int = field(default_factory=lambda: int(os.getenv("OWNER_TELEGRAM_ID", "0") or 0))
    timezone: str = field(default_factory=lambda: os.getenv("TIMEZONE", "Asia/Taipei"))
    assistant_name: str = field(default_factory=lambda: os.getenv("ASSISTANT_NAME", "Jarvis"))
    owner_name: str = field(default_factory=lambda: os.getenv("OWNER_NAME", "Fabian"))
    # Comma-separated list of skills to switch on.
    enabled_skills: list[str] = field(
        default_factory=lambda: _list(os.getenv("ENABLED_SKILLS", "google,tasks,research,admin"))
    )
    # Daily briefing time, HH:MM in your timezone. Empty = off.
    briefing_time: str = field(default_factory=lambda: os.getenv("BRIEFING_TIME", "07:30"))
    google_client_id: str = field(default_factory=lambda: os.getenv("GOOGLE_CLIENT_ID", ""))
    google_client_secret: str = field(default_factory=lambda: os.getenv("GOOGLE_CLIENT_SECRET", ""))
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", "./data")))
    history_turns: int = field(default_factory=lambda: int(os.getenv("HISTORY_TURNS", "20")))
    extra_instructions: str = field(default_factory=lambda: os.getenv("EXTRA_INSTRUCTIONS", ""))

    def missing(self) -> list[str]:
        out = []
        if not self.anthropic_api_key:
            out.append("ANTHROPIC_API_KEY")
        if not self.telegram_token:
            out.append("TELEGRAM_BOT_TOKEN")
        return out
