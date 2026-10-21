"""Journal & reflection: diary with mood, decision help, a thinking partner."""
from datetime import timedelta

from .base import Skill, Tool, schema, today

TABLES = """
CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, entry TEXT, mood INTEGER, tags TEXT
);
"""


def journal_add(a, ctx):
    jid = ctx.db.execute("INSERT INTO journal(day, entry, mood, tags) VALUES(?,?,?,?)",
                         (a.get("date") or today(ctx).isoformat(), a["entry"], a.get("mood"),
                          a.get("tags", "")))
    return f"Journal entry #{jid} saved."


def journal_read(a, ctx):
    if a.get("query"):
        like = f"%{a['query']}%"
        return ctx.db.query("SELECT id, day, mood, tags, entry FROM journal WHERE entry LIKE ? OR tags LIKE ? "
                            "ORDER BY day DESC LIMIT 20", (like, like)) or "Nothing found."
    since = (today(ctx) - timedelta(days=int(a.get("days", 7)))).isoformat()
    return ctx.db.query("SELECT id, day, mood, tags, entry FROM journal WHERE day >= ? ORDER BY day",
                        (since,)) or "No entries in that period."


def mood_trend(a, ctx):
    since = (today(ctx) - timedelta(days=int(a.get("days", 30)))).isoformat()
    rows = ctx.db.query("SELECT day, ROUND(AVG(mood), 1) AS mood FROM journal WHERE mood IS NOT NULL "
                        "AND day >= ? GROUP BY day ORDER BY day", (since,))
    if not rows:
        return "No mood scores logged in that period."
    moods = [r["mood"] for r in rows]
    return {"average": round(sum(moods) / len(moods), 1), "lowest": min(moods),
            "highest": max(moods), "per_day": rows}


class JournalSkill(Skill):
    def __init__(self):
        super().__init__(
            name="Journal & reflection",
            description="Diary with mood, reflection, and help with decisions.",
            instructions=(
                "JOURNAL: when the user wants to write or talk about their day, listen first, "
                "reflect back what you hear, ask one good follow-up question, and save it with "
                "journal_add (mood 1-10 if they give one or it's clear). Spot patterns over time "
                "(mood_trend, and links to sleep, training and stress from other areas) gently. "
                "DECISIONS: clarify what matters to them, then use a fitting tool: pros/cons, a "
                "weighted criteria table, 'what would you advise a friend', regret minimisation "
                "or a pre-mortem; give your honest recommendation but leave the choice to them. "
                "You are not a therapist: if they seem in crisis or mention self-harm, respond "
                "with care and urge them to contact someone now (Taiwan: 1925 or 119; Sweden: "
                "Mind 90101 or 112)."
            ),
            tools=[
                Tool("journal_add", "Save a journal entry.",
                     schema({"entry": {"type": "string"},
                             "mood": {"type": "integer", "description": "1 (awful) - 10 (great)"},
                             "tags": {"type": "string"},
                             "date": {"type": "string", "description": "YYYY-MM-DD, default today"}},
                            ["entry"]), journal_add),
                Tool("journal_read", "Read entries from the last N days (default 7) or search them.",
                     schema({"days": {"type": "integer"}, "query": {"type": "string"}}), journal_read),
                Tool("mood_trend", "Mood scores over the last N days (default 30).",
                     schema({"days": {"type": "integer"}}), mood_trend),
            ],
        )

    def setup(self, db, config):
        db.executescript(TABLES)
