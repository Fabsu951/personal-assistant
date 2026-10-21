"""Career: job/internship applications, CVs, cover letters, interview practice."""
from .base import Skill, Tool, schema, today

TABLES = """
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT, role TEXT, status TEXT DEFAULT 'interested',
    deadline TEXT, link TEXT, contact TEXT, notes TEXT, applied_on TEXT, updated TEXT
);
"""
STATUSES = ["interested", "applied", "interview", "offer", "rejected", "withdrawn"]


def application_add(a, ctx):
    aid = ctx.db.execute(
        "INSERT INTO applications(company, role, status, deadline, link, contact, notes, applied_on, "
        "updated) VALUES(?,?,?,?,?,?,?,?,?)",
        (a["company"], a.get("role", ""), a.get("status", "interested"), a.get("deadline"),
         a.get("link", ""), a.get("contact", ""), a.get("notes", ""),
         today(ctx).isoformat() if a.get("status") == "applied" else None, today(ctx).isoformat()))
    return f"Application #{aid} saved."


def application_update(a, ctx):
    rows = ctx.db.query("SELECT * FROM applications WHERE id=?", (a["application_id"],))
    if not rows:
        return "Application not found."
    r = rows[0]
    notes = r["notes"] + (f"\n[{today(ctx)}] {a['add_note']}" if a.get("add_note") else "")
    status = a.get("status", r["status"])
    applied_on = r["applied_on"] or (today(ctx).isoformat() if status == "applied" else None)
    ctx.db.execute("UPDATE applications SET status=?, deadline=?, contact=?, notes=?, applied_on=?, "
                   "updated=? WHERE id=?",
                   (status, a.get("deadline", r["deadline"]), a.get("contact", r["contact"]), notes,
                    applied_on, today(ctx).isoformat(), r["id"]))
    return f"Application #{r['id']} updated ({status})."


def application_list(a, ctx):
    sql = "SELECT id, company, role, status, deadline, applied_on, link, substr(notes, -200) AS notes FROM applications"
    if not a.get("include_closed"):
        sql += " WHERE status NOT IN ('rejected', 'withdrawn')"
    return ctx.db.query(sql + " ORDER BY deadline IS NULL, deadline, id") or "No applications tracked."


class CareerSkill(Skill):
    def __init__(self):
        super().__init__(
            name="Career & job search",
            description="Application tracker, CVs, cover letters, interview practice, LinkedIn.",
            instructions=(
                "Track jobs/internships the user is interested in or applies to, with deadlines. "
                "For an application: get the job ad (text, link or web_search), research the "
                "company, then tailor the CV and cover letter to the ad's key requirements with "
                "concrete achievements (ask for the user's CV once and save it as a note), and "
                "deliver them with document_create. INTERVIEWS: list likely questions, help build "
                "STAR answers, and run mock interviews one question at a time with honest "
                "feedback. Also: LinkedIn profile and networking messages, salary research, "
                "follow-up emails after interviews (drafts in Gmail)."
            ),
            tools=[
                Tool("application_add", "Track a job/internship.",
                     schema({"company": {"type": "string"}, "role": {"type": "string"},
                             "status": {"type": "string", "enum": STATUSES},
                             "deadline": {"type": "string", "description": "YYYY-MM-DD"},
                             "link": {"type": "string"}, "contact": {"type": "string"},
                             "notes": {"type": "string"}}, ["company"]), application_add),
                Tool("application_update", "Update status/deadline or add a note to an application.",
                     schema({"application_id": {"type": "integer"},
                             "status": {"type": "string", "enum": STATUSES},
                             "deadline": {"type": "string"}, "contact": {"type": "string"},
                             "add_note": {"type": "string"}}, ["application_id"]), application_update),
                Tool("application_list", "List tracked applications (open ones unless asked).",
                     schema({"include_closed": {"type": "boolean"}}), application_list),
            ],
        )

    def setup(self, db, config):
        db.executescript(TABLES)
