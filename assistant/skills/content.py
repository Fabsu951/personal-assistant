"""Content creation: video/post pipeline, scripts, captions and a publishing plan."""
from .base import Skill, Tool, schema, today

TABLES = """
CREATE TABLE IF NOT EXISTS content (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, platform TEXT, status TEXT DEFAULT 'idea',
    publish_date TEXT, script TEXT, notes TEXT, link TEXT, updated TEXT
);
"""
STATUSES = ["idea", "scripted", "filmed", "edited", "scheduled", "published"]


def content_add(a, ctx):
    cid = ctx.db.execute(
        "INSERT INTO content(title, platform, status, publish_date, script, notes, updated) "
        "VALUES(?,?,?,?,?,?,?)",
        (a["title"], a.get("platform", ""), a.get("status", "idea"), a.get("publish_date"),
         a.get("script", ""), a.get("notes", ""), today(ctx).isoformat()))
    return f"Content #{cid} added."


def content_update(a, ctx):
    rows = ctx.db.query("SELECT * FROM content WHERE id=?", (a["content_id"],))
    if not rows:
        return "Content item not found."
    c = rows[0] | {k: v for k, v in a.items() if k != "content_id" and v is not None}
    ctx.db.execute("UPDATE content SET title=?, platform=?, status=?, publish_date=?, script=?, "
                   "notes=?, link=?, updated=? WHERE id=?",
                   (c["title"], c["platform"], c["status"], c["publish_date"], c["script"],
                    c["notes"], c["link"], today(ctx).isoformat(), c["id"]))
    return f"Content #{c['id']} updated ({c['status']})."


def content_list(a, ctx):
    sql, params = ("SELECT id, title, platform, status, publish_date, link, "
                   "substr(notes, 1, 150) AS notes FROM content WHERE 1=1"), []
    if a.get("status"):
        sql += " AND status=?"
        params.append(a["status"])
    elif not a.get("include_published"):
        sql += " AND status != 'published'"
    return ctx.db.query(sql + " ORDER BY publish_date IS NULL, publish_date, id LIMIT 50",
                        tuple(params)) or "Nothing in the content plan."


def content_script(a, ctx):
    rows = ctx.db.query("SELECT * FROM content WHERE id=?", (a["content_id"],))
    return rows[0] if rows else "Content item not found."


class ContentSkill(Skill):
    def __init__(self):
        super().__init__(
            name="Content & social media",
            description="Video and post pipeline, scripts, hooks, captions and publishing plan.",
            instructions=(
                "Track every video/post in the content plan from idea to published, with "
                "publish dates (check the calendar for filming/publishing slots). SHORT VIDEOS "
                "(TikTok/Reels/Shorts): a scroll-stopping hook in the first 2 seconds, one clear "
                "point, a script with shot list and on-screen text, a call to action; suggest 3 "
                "hook variants. Save scripts in the item (content_update script=...). CAPTIONS: "
                "per platform, with a few relevant hashtags. LINKEDIN: strong first line, short "
                "paragraphs, a personal angle, a question at the end. Suggest how to repurpose "
                "one piece across platforms, and ideas based on what performed well (ask the user "
                "for numbers)."
            ),
            tools=[
                Tool("content_add", "Add a video/post to the content plan.",
                     schema({"title": {"type": "string"},
                             "platform": {"type": "string", "description": "e.g. TikTok, YouTube, LinkedIn"},
                             "status": {"type": "string", "enum": STATUSES},
                             "publish_date": {"type": "string", "description": "YYYY-MM-DD"},
                             "script": {"type": "string"}, "notes": {"type": "string"}},
                            ["title"]), content_add),
                Tool("content_update", "Update a content item (status, date, script, link...).",
                     schema({"content_id": {"type": "integer"}, "title": {"type": "string"},
                             "platform": {"type": "string"}, "status": {"type": "string", "enum": STATUSES},
                             "publish_date": {"type": "string"}, "script": {"type": "string"},
                             "notes": {"type": "string"}, "link": {"type": "string"}},
                            ["content_id"]), content_update),
                Tool("content_list", "The content plan (not yet published, unless asked).",
                     schema({"status": {"type": "string", "enum": STATUSES},
                             "include_published": {"type": "boolean"}}), content_list),
                Tool("content_script", "Full details and script of one content item.",
                     schema({"content_id": {"type": "integer"}}, ["content_id"]), content_script),
            ],
        )

    def setup(self, db, config):
        db.executescript(TABLES)
