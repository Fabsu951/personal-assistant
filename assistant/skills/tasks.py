"""To-do list and reminders (stored in the assistant's own database)."""
from datetime import datetime
from zoneinfo import ZoneInfo

from .base import Skill, Tool, schema

TABLES = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, notes TEXT, due TEXT,
    priority TEXT DEFAULT 'normal', done INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, text TEXT,
    due_at TEXT, sent INTEGER DEFAULT 0
);
"""


def task_add(a, ctx):
    tid = ctx.db.execute("INSERT INTO tasks(title, notes, due, priority) VALUES(?,?,?,?)",
                         (a["title"], a.get("notes", ""), a.get("due"), a.get("priority", "normal")))
    return f"Task #{tid} added."


def task_list(a, ctx):
    sql = "SELECT id, title, notes, due, priority, done FROM tasks"
    if not a.get("include_done"):
        sql += " WHERE done=0"
    sql += " ORDER BY done, due IS NULL, due, id"
    return ctx.db.query(sql) or "No tasks."


def task_complete(a, ctx):
    ctx.db.execute("UPDATE tasks SET done=1 WHERE id=?", (a["task_id"],))
    return f"Task #{a['task_id']} marked done."


def task_delete(a, ctx):
    ctx.db.execute("DELETE FROM tasks WHERE id=?", (a["task_id"],))
    return f"Task #{a['task_id']} deleted."


def reminder_set(a, ctx):
    tz = ZoneInfo(ctx.config.timezone)
    when = datetime.fromisoformat(a["when"])
    if when.tzinfo is None:
        when = when.replace(tzinfo=tz)
    if when <= datetime.now(tz):
        return "ERROR: that time is in the past."
    rid = ctx.db.execute("INSERT INTO reminders(chat_id, text, due_at) VALUES(?,?,?)",
                         (ctx.chat_id, a["text"], when.isoformat()))
    return f"Reminder #{rid} set for {when:%a %d %b %H:%M}."


def reminder_list(a, ctx):
    return ctx.db.query("SELECT id, text, due_at FROM reminders WHERE sent=0 ORDER BY due_at") \
        or "No upcoming reminders."


def reminder_cancel(a, ctx):
    ctx.db.execute("DELETE FROM reminders WHERE id=?", (a["reminder_id"],))
    return f"Reminder #{a['reminder_id']} cancelled."


def due_reminders(db) -> list[dict]:
    """Called every 30s by the bot: returns reminders to send now and marks them sent."""
    now = datetime.now().astimezone()
    out = []
    for r in db.query("SELECT * FROM reminders WHERE sent=0"):
        if datetime.fromisoformat(r["due_at"]) <= now:
            db.execute("UPDATE reminders SET sent=1 WHERE id=?", (r["id"],))
            out.append(r)
    return out


class TasksSkill(Skill):
    def __init__(self):
        super().__init__(
            name="Tasks & reminders",
            description="Personal to-do list and timed reminders sent on Telegram.",
            instructions=(
                "Use tasks for things to do, reminders for 'remind me at/in ...'. "
                "Convert relative times ('in 2 hours', 'tomorrow 9') to ISO datetimes "
                "using the current date and time."
            ),
            tools=[
                Tool("task_add", "Add a to-do item.",
                     schema({"title": {"type": "string"}, "notes": {"type": "string"},
                             "due": {"type": "string", "description": "ISO date/time, optional"},
                             "priority": {"type": "string", "enum": ["low", "normal", "high"]}},
                            ["title"]), task_add),
                Tool("task_list", "List to-do items.",
                     schema({"include_done": {"type": "boolean"}}), task_list),
                Tool("task_complete", "Mark a task as done.",
                     schema({"task_id": {"type": "integer"}}, ["task_id"]), task_complete),
                Tool("task_delete", "Delete a task.",
                     schema({"task_id": {"type": "integer"}}, ["task_id"]), task_delete),
                Tool("reminder_set", "Send the user a Telegram message at a given time.",
                     schema({"text": {"type": "string"},
                             "when": {"type": "string", "description": "ISO datetime"}},
                            ["text", "when"]), reminder_set),
                Tool("reminder_list", "List upcoming reminders.", schema({}), reminder_list),
                Tool("reminder_cancel", "Cancel a reminder.",
                     schema({"reminder_id": {"type": "integer"}}, ["reminder_id"]), reminder_cancel),
            ],
        )

    def setup(self, db, config):
        db.executescript(TABLES)
