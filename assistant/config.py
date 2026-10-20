"""All settings come from environment variables (see .env.example)."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str = "") -> str:
    """Like os.getenv, but an empty value (e.g. a blank Railway variable) means 'use the default'."""
    return os.getenv(name) or default


def _list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass
class Config:
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY", ""))
    model: str = field(default_factory=lambda: _env("MODEL", "claude-sonnet-5-5"))
    telegram_token: str = field(default_factory=lambda: _env("TELEGRAM_BOT_TOKEN", ""))
    # Only this Telegram user may talk to the bot. Leave empty on first run:
    # the bot will tell you your ID.
    owner_id: int = field(default_factory=lambda: int(_env("OWNER_TELEGRAM_ID", "0")))
    timezone: str = field(default_factory=lambda: _env("TIMEZONE", "Asia/Taipei"))
    assistant_name: str = field(default_factory=lambda: _env("ASSISTANT_NAME", "Jarvis"))
    owner_name: str = field(default_factory=lambda: _env("OWNER_NAME", "Fabian"))
    # Comma-separated list of skills to switch on.
    enabled_skills: list[str] = field(
        default_factory=lambda: _list(_env("ENABLED_SKILLS", "google,tasks,research,admin,fitness"))
    )
    # Daily briefing time, HH:MM in your timezone. "off" = no briefing.
    briefing_time: str = field(default_factory=lambda: _env("BRIEFING_TIME", "07:30"))
    # Weekly training review, sent on Sundays at HH:MM (needs the fitness skill). "off" = none.
    weekly_review_time: str = field(default_factory=lambda: _env("WEEKLY_REVIEW_TIME", "19:00"))
    google_client_id: str = field(default_factory=lambda: _env("GOOGLE_CLIENT_ID", ""))
    google_client_secret: str = field(default_factory=lambda: _env("GOOGLE_CLIENT_SECRET", ""))
    # Strava (brings in workouts from Garmin/Apple Watch etc.) - connect with /connect_strava
    strava_client_id: str = field(default_factory=lambda: _env("STRAVA_CLIENT_ID", ""))
    strava_client_secret: str = field(default_factory=lambda: _env("STRAVA_CLIENT_SECRET", ""))
    # Voice messages are transcribed with OpenAI's speech-to-text API. Empty = voice off.
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY", ""))
    transcribe_model: str = field(
        default_factory=lambda: _env("TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe"))
    # Railway volume at /data if there is one, otherwise a local folder.
    data_dir: Path = field(default_factory=lambda: Path(
        _env("DATA_DIR", "/data" if Path("/data").is_dir() else "./data")))
    history_turns: int = field(default_factory=lambda: int(_env("HISTORY_TURNS", "20")))
    extra_instructions: str = field(default_factory=lambda: _env("EXTRA_INSTRUCTIONS", ""))

    def missing(self) -> list[str]:
        out = []
        if not self.anthropic_api_key:
            out.append("ANTHROPIC_API_KEY")
        if not self.telegram_token:
            out.append("TELEGRAM_BOT_TOKEN")
        return out
