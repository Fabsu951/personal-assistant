"""Habits with streaks, and bigger goals with progress and milestones."""
from datetime import timedelta

from .base import Skill, Tool, schema, today

TABLES = """
CREATE TABLE IF NOT EXISTS habits (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, per_week INTEGER DEFAULT 7, active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS habit_log (
    habit_id INTEGER, day TEXT, PRIMARY KEY (habit_id, day)
);
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, why TEXT, target_date TEXT,
    progress INTEGER DEFAULT 0, status TEXT DEFAULT 'active', log TEXT DEFAULT '', updated TEXT
);
"""
GOAL_STATUSES = ["active", "paused", "achieved", "dropped"]


def habit_add(a, ctx):
    hid = ctx.db.execute("INSERT INTO habits(name, per_week) VALUES(?,?)",
                         (a["name"], int(a.get("per_week", 7))))
    return f"Habit #{hid} added."


def _find_habit(ctx, name_or_id):
    rows = ctx.db.query("SELECT * FROM habits WHERE active=1 AND (CAST(id AS TEXT)=? OR name LIKE ?)",
                        (str(name_or_id), f"%{name_or_id}%"))
    return rows[0] if rows else None


def habit_done(a, ctx):
    day = a.get("date") or today(ctx).isoformat()
    done, missing = [], []
    for h in a["habits"]:
        habit = _find_habit(ctx, h)
        if habit:
            ctx.db.execute("INSERT OR IGNORE INTO habit_log(habit_id, day) VALUES(?,?)", (habit["id"], day))
            done.append(habit["name"])
        else:
            missing.append(h)
    return {"checked": done, "not_found": missing}


def streak(days_done: set[str], start) -> int:
    """Days in a row up to today (or yesterday, if today isn't done yet)."""
    d = start if start.isoformat() in days_done else start - timedelta(days=1)
    n = 0
    while d.isoformat() in days_done:
        n += 1
        d -= timedelta(days=1)
    return n


def habit_status(a, ctx):
    now = today(ctx)
    week_start = now - timedelta(days=now.weekday())
    out = []
    for h in ctx.db.query("SELECT * FROM habits WHERE active=1"):
        days = {r["day"] for r in ctx.db.query("SELECT day FROM habit_log WHERE habit_id=?", (h["id"],))}
        out.append({"id": h["id"], "habit": h["name"], "done_today": now.isoformat() in days,
                    "this_week": sum(d >= week_start.isoformat() for d in days),
                    "target_per_week": h["per_week"], "streak_days": streak(days, now)})
    return out or "No habits yet."


def habit_remove(a, ctx):
    ctx.db.execute("UPDATE habits SET active=0 WHERE id=?", (a["habit_id"],))
    return f"Habit #{a['habit_id']} stopped."


def goal_add(a, ctx):
    gid = ctx.db.execute("INSERT INTO goals(title, why, target_date, updated) VALUES(?,?,?,?)",
                         (a["title"], a.get("why", ""), a.get("target_date"), today(ctx).isoformat()))
    return f"Goal #{gid} added."


def goal_update(a, ctx):
    rows = ctx.db.query("SELECT * FROM goals WHERE id=?", (a["goal_id"],))
    if not rows:
        return "Goal not found."
    g = rows[0]
    log = g["log"] + (f"\n[{today(ctx)}] {a['note']}" if a.get("note") else "")
    ctx.db.execute("UPDATE goals SET progress=?, status=?, target_date=?, log=?, updated=? WHERE id=?",
                   (int(a.get("progress", g["progress"])), a.get("status", g["status"]),
                    a.get("target_date", g["target_date"]), log, today(ctx).isoformat(), g["id"]))
    return f"Goal #{g['id']} updated."


def goal_list(a, ctx):
    sql = "SELECT id, title, why, target_date, progress, status, substr(log, -300) AS recent_log FROM goals"
    if not a.get("include_closed"):
        sql += " WHERE status IN ('active', 'paused')"
    return ctx.db.query(sql + " ORDER BY target_date IS NULL, target_date") or "No goals yet."


class HabitsSkill(Skill):
    def __init__(self):
        super().__init__(
            name="Habits & goals",
            description="Habits with streaks, and goals with progress.",
            instructions=(
                "Help the user build habits that stick: start small and specific (when/where), "
                "tie them to existing routines, and celebrate streaks without guilt-tripping "
                "missed days. When the user says they did something, check it off with "
                "habit_done. GOALS: make them concrete (what, by when, why), break them into "
                "milestones and next actions (tasks/calendar), update progress and notes as they "
                "move, and connect related areas (training, studies, savings)."
            ),
            tools=[
                Tool("habit_add", "Start tracking a habit.",
                     schema({"name": {"type": "string"},
                             "per_week": {"type": "integer", "description": "Target days per week, default 7"}},
                            ["name"]), habit_add),
                Tool("habit_done", "Check off habits for a day (names or ids).",
                     schema({"habits": {"type": "array", "items": {"type": "string"}},
                             "date": {"type": "string", "description": "YYYY-MM-DD, default today"}},
                            ["habits"]), habit_done),
                Tool("habit_status", "Habits: done today, this week vs target, streaks.",
                     schema({}), habit_status),
                Tool("habit_remove", "Stop tracking a habit.",
                     schema({"habit_id": {"type": "integer"}}, ["habit_id"]), habit_remove),
                Tool("goal_add", "Add a goal.",
                     schema({"title": {"type": "string"}, "why": {"type": "string"},
                             "target_date": {"type": "string", "description": "YYYY-MM-DD"}},
                            ["title"]), goal_add),
                Tool("goal_update", "Update a goal's progress (0-100), status, date or add a note.",
                     schema({"goal_id": {"type": "integer"}, "progress": {"type": "integer"},
                             "status": {"type": "string", "enum": GOAL_STATUSES},
                             "target_date": {"type": "string"}, "note": {"type": "string"}},
                            ["goal_id"]), goal_update),
                Tool("goal_list", "List goals (active and paused unless asked).",
                     schema({"include_closed": {"type": "boolean"}}), goal_list),
            ],
        )

    def setup(self, db, config):
        db.executescript(TABLES)
