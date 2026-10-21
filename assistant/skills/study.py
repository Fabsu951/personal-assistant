"""Studies: flashcards with spaced repetition, quizzes and exam plans."""
from datetime import timedelta

from .base import Skill, Tool, schema, today

TABLES = """
CREATE TABLE IF NOT EXISTS flashcards (
    id INTEGER PRIMARY KEY AUTOINCREMENT, deck TEXT, front TEXT, back TEXT,
    due TEXT, interval INTEGER DEFAULT 0, ease REAL DEFAULT 2.5, reps INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def flashcards_add(a, ctx):
    due = today(ctx).isoformat()
    for c in a["cards"]:
        ctx.db.execute("INSERT INTO flashcards(deck, front, back, due) VALUES(?,?,?,?)",
                       (a["deck"].strip(), c["front"], c["back"], due))
    return f"{len(a['cards'])} card(s) added to '{a['deck']}'."


def flashcards_due(a, ctx):
    sql, params = "SELECT id, deck, front, back FROM flashcards WHERE due <= ?", [today(ctx).isoformat()]
    if a.get("deck"):
        sql += " AND deck LIKE ?"
        params.append(f"%{a['deck']}%")
    rows = ctx.db.query(sql + " ORDER BY due, id LIMIT ?", (*params, int(a.get("limit", 10))))
    return rows or "No cards due. 🎉"


def next_review(interval: int, ease: float, reps: int, grade: str) -> tuple[int, float, int]:
    """A simple SM-2 schedule: returns (days until next review, ease, reps)."""
    if grade == "again":
        return 0, max(1.3, ease - 0.2), 0
    if grade == "hard":
        return max(1, round(interval * 1.2)), max(1.3, ease - 0.15), reps + 1
    days = 1 if reps == 0 else 3 if reps == 1 else round(interval * ease)
    if grade == "easy":
        return round(days * 1.3) + 1, ease + 0.15, reps + 1
    return days, ease, reps + 1


def flashcard_grade(a, ctx):
    rows = ctx.db.query("SELECT * FROM flashcards WHERE id=?", (a["card_id"],))
    if not rows:
        return "Card not found."
    c = rows[0]
    interval, ease, reps = next_review(c["interval"], c["ease"], c["reps"], a["grade"])
    due = (today(ctx) + timedelta(days=interval)).isoformat()
    ctx.db.execute("UPDATE flashcards SET interval=?, ease=?, reps=?, due=? WHERE id=?",
                   (interval, ease, reps, due, c["id"]))
    return f"Next review {due}."


def flashcard_decks(a, ctx):
    return ctx.db.query(
        "SELECT deck, COUNT(*) AS cards, SUM(due <= ?) AS due_now FROM flashcards GROUP BY deck",
        (today(ctx).isoformat(),)) or "No flashcards yet."


def flashcard_delete(a, ctx):
    ctx.db.execute("DELETE FROM flashcards WHERE id=?", (a["card_id"],))
    return f"Card #{a['card_id']} deleted."


class StudySkill(Skill):
    def __init__(self):
        super().__init__(
            name="Studies & exams",
            description="Flashcards with spaced repetition, quizzes, explanations and exam plans.",
            instructions=(
                "Help the user learn, not just get answers. EXPLAIN concepts simply first, then "
                "deeper, with an example; check understanding with a question. FLASHCARDS: make "
                "short, single-fact cards from lecture notes, PDFs, photos or OneDrive/Drive files "
                "(for Mandarin: front = characters, back = pinyin + meaning). QUIZ: take "
                "flashcards_due, show ONLY the front, wait for the answer, then reveal the back, "
                "say if it was right and grade it (again/hard/good/easy) with flashcard_grade. "
                "Also make practice exam questions and grade the user's answers like a strict but "
                "kind teacher. EXAM PLANS: find exams in the calendar, split the material into "
                "sessions spread out until the exam (spaced, with repetition the last days), "
                "respect existing events, and offer to put the sessions in the calendar."
            ),
            tools=[
                Tool("flashcards_add", "Add flashcards to a deck.",
                     schema({"deck": {"type": "string", "description": "e.g. 'Fin Inve', 'Mandarin'"},
                             "cards": {"type": "array", "items": {
                                 "type": "object", "required": ["front", "back"],
                                 "properties": {"front": {"type": "string"}, "back": {"type": "string"}}}}},
                            ["deck", "cards"]), flashcards_add),
                Tool("flashcards_due", "Cards due for review now (spaced repetition).",
                     schema({"deck": {"type": "string"}, "limit": {"type": "integer"}}), flashcards_due),
                Tool("flashcard_grade", "Grade the user's answer to a card; schedules the next review.",
                     schema({"card_id": {"type": "integer"},
                             "grade": {"type": "string", "enum": ["again", "hard", "good", "easy"]}},
                            ["card_id", "grade"]), flashcard_grade),
                Tool("flashcard_decks", "List decks with card counts and how many are due.",
                     schema({}), flashcard_decks),
                Tool("flashcard_delete", "Delete a flashcard.",
                     schema({"card_id": {"type": "integer"}}, ["card_id"]), flashcard_delete),
            ],
        )

    def setup(self, db, config):
        db.executescript(TABLES)
