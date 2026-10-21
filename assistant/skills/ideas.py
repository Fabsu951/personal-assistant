"""Ideas: brainstorm partner and an idea bank to come back to."""
from .base import Skill, Tool, schema, today

TABLES = """
CREATE TABLE IF NOT EXISTS ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, details TEXT, tags TEXT,
    status TEXT DEFAULT 'new', created TEXT, updated TEXT
);
"""
STATUSES = ["new", "exploring", "doing", "done", "dropped"]


def idea_save(a, ctx):
    d = today(ctx).isoformat()
    iid = ctx.db.execute("INSERT INTO ideas(title, details, tags, created, updated) VALUES(?,?,?,?,?)",
                         (a["title"], a.get("details", ""), a.get("tags", ""), d, d))
    return f"Idea #{iid} saved."


def idea_list(a, ctx):
    sql, params = "SELECT id, title, tags, status, updated, substr(details, 1, 200) AS details FROM ideas WHERE 1=1", []
    if a.get("status"):
        sql += " AND status=?"
        params.append(a["status"])
    if a.get("query"):
        sql += " AND (title LIKE ? OR details LIKE ? OR tags LIKE ?)"
        params += [f"%{a['query']}%"] * 3
    return ctx.db.query(sql + " ORDER BY updated DESC LIMIT 30", tuple(params)) or "No ideas found."


def idea_update(a, ctx):
    rows = ctx.db.query("SELECT * FROM ideas WHERE id=?", (a["idea_id"],))
    if not rows:
        return "Idea not found."
    i = rows[0]
    details = i["details"] + (f"\n[{today(ctx)}] {a['add_details']}" if a.get("add_details") else "")
    ctx.db.execute("UPDATE ideas SET details=?, status=?, tags=?, updated=? WHERE id=?",
                   (details, a.get("status", i["status"]), a.get("tags", i["tags"]),
                    today(ctx).isoformat(), i["id"]))
    return f"Idea #{i['id']} updated."


class IdeasSkill(Skill):
    def __init__(self):
        super().__init__(
            name="Ideas & brainstorming",
            description="Brainstorm partner and an idea bank.",
            instructions=(
                "When brainstorming: first go wide (many varied ideas, including a few bold ones), "
                "then cluster, then rank by impact vs effort and pick a next step. Use techniques "
                "when stuck: SCAMPER, reverse the problem, first principles, 'what would make "
                "this 10x', constraints. Build on the user's ideas, play devil's advocate when "
                "asked, and be honest about weak spots. Save ideas the user likes with idea_save "
                "and bring up related saved ideas (idea_list) when relevant."
            ),
            tools=[
                Tool("idea_save", "Save an idea to the idea bank.",
                     schema({"title": {"type": "string"}, "details": {"type": "string"},
                             "tags": {"type": "string", "description": "comma separated"}},
                            ["title"]), idea_save),
                Tool("idea_list", "List/search saved ideas.",
                     schema({"query": {"type": "string"}, "status": {"type": "string", "enum": STATUSES}}),
                     idea_list),
                Tool("idea_update", "Add thoughts to an idea or change its status.",
                     schema({"idea_id": {"type": "integer"}, "add_details": {"type": "string"},
                             "status": {"type": "string", "enum": STATUSES}, "tags": {"type": "string"}},
                            ["idea_id"]), idea_update),
            ],
        )

    def setup(self, db, config):
        db.executescript(TABLES)
