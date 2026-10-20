"""Web research plus a personal notes / knowledge base."""
from .base import Skill, Tool, schema

TABLES = """
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, content TEXT, tags TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def note_save(a, ctx):
    nid = ctx.db.execute("INSERT INTO notes(title, content, tags) VALUES(?,?,?)",
                         (a["title"], a["content"], a.get("tags", "")))
    return f"Note #{nid} saved."


def note_search(a, ctx):
    like = f"%{a['query']}%"
    rows = ctx.db.query(
        "SELECT id, title, tags, substr(content, 1, 200) AS preview, created_at FROM notes "
        "WHERE title LIKE ? OR content LIKE ? OR tags LIKE ? ORDER BY id DESC LIMIT 20",
        (like, like, like))
    return rows or "No matching notes."


def note_read(a, ctx):
    rows = ctx.db.query("SELECT * FROM notes WHERE id=?", (a["note_id"],))
    return rows[0] if rows else "Note not found."


def note_delete(a, ctx):
    ctx.db.execute("DELETE FROM notes WHERE id=?", (a["note_id"],))
    return f"Note #{a['note_id']} deleted."


class ResearchSkill(Skill):
    def __init__(self):
        super().__init__(
            name="Research & notes",
            description="Search the web and keep a personal knowledge base.",
            instructions=(
                "Use web_search for anything current (news, prices, opening hours, facts that "
                "change). Give short answers and mention your sources. When the user says "
                "'remember', 'note' or 'save this', store it with note_save; check notes "
                "(note_search) when they ask about something they told you before."
            ),
            tools=[
                Tool("note_save", "Save a note to the user's knowledge base.",
                     schema({"title": {"type": "string"}, "content": {"type": "string"},
                             "tags": {"type": "string", "description": "comma separated"}},
                            ["title", "content"]), note_save),
                Tool("note_search", "Search saved notes.",
                     schema({"query": {"type": "string"}}, ["query"]), note_search),
                Tool("note_read", "Read a full note.",
                     schema({"note_id": {"type": "integer"}}, ["note_id"]), note_read),
                Tool("note_delete", "Delete a note.",
                     schema({"note_id": {"type": "integer"}}, ["note_id"]), note_delete),
            ],
        )

    def setup(self, db, config):
        db.executescript(TABLES)

    def server_tools(self):
        # Anthropic runs the search for us; billed per search on your API account.
        return [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]
