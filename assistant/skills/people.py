"""People: a personal address book with birthdays, notes, gift ideas and keeping in touch."""
from datetime import date, timedelta

from .base import Skill, Tool, schema, today

TABLES = """
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE COLLATE NOCASE, relation TEXT,
    birthday TEXT, phone TEXT, email TEXT, notes TEXT DEFAULT '', gift_ideas TEXT DEFAULT '',
    last_contact TEXT
);
"""
FIELDS = ["relation", "birthday", "phone", "email"]


def contact_save(a, ctx):
    rows = ctx.db.query("SELECT * FROM contacts WHERE name=?", (a["name"],))
    if not rows:
        ctx.db.execute("INSERT INTO contacts(name) VALUES(?)", (a["name"],))
        rows = ctx.db.query("SELECT * FROM contacts WHERE name=?", (a["name"],))
    c = rows[0]
    stamp = f"[{today(ctx)}] "
    notes = c["notes"] + (f"\n{stamp}{a['add_note']}" if a.get("add_note") else "")
    gifts = c["gift_ideas"] + (f"\n{stamp}{a['add_gift_idea']}" if a.get("add_gift_idea") else "")
    values = [a.get(f, c[f]) for f in FIELDS]
    ctx.db.execute(f"UPDATE contacts SET {', '.join(f + '=?' for f in FIELDS)}, notes=?, gift_ideas=? "
                   "WHERE id=?", (*values, notes, gifts, c["id"]))
    return f"Saved {a['name']}."


def contact_find(a, ctx):
    like = f"%{a['query']}%"
    return ctx.db.query("SELECT * FROM contacts WHERE name LIKE ? OR relation LIKE ? OR notes LIKE ?",
                        (like, like, like)) or "No one found."


def contact_touch(a, ctx):
    rows = ctx.db.query("SELECT id FROM contacts WHERE name=?", (a["name"],))
    if not rows:
        return f"{a['name']} isn't saved yet; use contact_save first."
    ctx.db.execute("UPDATE contacts SET last_contact=? WHERE id=?",
                   (a.get("date") or today(ctx).isoformat(), rows[0]["id"]))
    if a.get("note"):
        contact_save({"name": a["name"], "add_note": a["note"]}, ctx)
    return f"Noted that you were in touch with {a['name']}."


def days_until_birthday(birthday: str, now: date) -> int | None:
    """Accepts YYYY-MM-DD or MM-DD."""
    try:
        month, day = map(int, birthday[-5:].split("-"))
        nxt = date(now.year, month, day)
    except ValueError:
        if birthday[-5:] != "02-29":
            return None
        nxt = date(now.year, 3, 1)  # leap-day birthdays in normal years
    if nxt < now:
        nxt = nxt.replace(year=now.year + 1)
    return (nxt - now).days


def birthdays_upcoming(a, ctx):
    now = today(ctx)
    out = []
    for c in ctx.db.query("SELECT name, relation, birthday, gift_ideas FROM contacts WHERE birthday IS NOT NULL"):
        days = days_until_birthday(c["birthday"], now)
        if days is not None and days <= int(a.get("days", 30)):
            turns = (now + timedelta(days=days)).year - int(c["birthday"][:4]) \
                if len(c["birthday"]) == 10 else None
            out.append({**c, "in_days": days, "turns": turns})
    return sorted(out, key=lambda c: c["in_days"]) or "No birthdays coming up."


def contacts_neglected(a, ctx):
    since = int(a.get("days", 60))
    rows = ctx.db.query("SELECT name, relation, last_contact FROM contacts")
    now = today(ctx)
    return [r for r in rows if not r["last_contact"]
            or (now - date.fromisoformat(r["last_contact"])).days >= since] or "You're in touch with everyone."


class PeopleSkill(Skill):
    def __init__(self):
        super().__init__(
            name="People & relationships",
            description="Birthdays, notes about people, gift ideas, keeping in touch.",
            instructions=(
                "Remember the people in the user's life: when they share something about "
                "someone (birthday, partner, job, likes, what they talked about), save it with "
                "contact_save. Before the user meets or messages someone, recall what you know. "
                "Bring up birthdays a week ahead with gift ideas that fit the person and the "
                "user's budget, and offer a reminder. Suggest reaching out to people they haven't "
                "talked to in a while, and help write messages and cards in the right tone."
            ),
            tools=[
                Tool("contact_save", "Save or update a person (fields given are updated, notes appended).",
                     schema({"name": {"type": "string"}, "relation": {"type": "string"},
                             "birthday": {"type": "string", "description": "YYYY-MM-DD or MM-DD"},
                             "phone": {"type": "string"}, "email": {"type": "string"},
                             "add_note": {"type": "string"}, "add_gift_idea": {"type": "string"}},
                            ["name"]), contact_save),
                Tool("contact_find", "Look up people by name, relation or notes.",
                     schema({"query": {"type": "string"}}, ["query"]), contact_find),
                Tool("contact_touch", "Note that the user was in touch with someone.",
                     schema({"name": {"type": "string"}, "note": {"type": "string"},
                             "date": {"type": "string"}}, ["name"]), contact_touch),
                Tool("birthdays_upcoming", "Birthdays in the next N days (default 30).",
                     schema({"days": {"type": "integer"}}), birthdays_upcoming),
                Tool("contacts_neglected", "People not contacted in N days (default 60).",
                     schema({"days": {"type": "integer"}}), contacts_neglected),
            ],
        )

    def setup(self, db, config):
        db.executescript(TABLES)
