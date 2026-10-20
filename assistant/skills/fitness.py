"""Training coach: keeps the training program, logs workouts and tracks progress."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .base import Skill, Tool, schema

TABLES = """
CREATE TABLE IF NOT EXISTS workouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, kind TEXT, duration_min INTEGER,
    notes TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS workout_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT, workout_id INTEGER, exercise TEXT,
    sets INTEGER, reps INTEGER, weight_kg REAL, distance_km REAL, minutes REAL
);
"""
PROGRAM_KEY = "fitness_program"


def _today(ctx) -> str:
    return datetime.now(ZoneInfo(ctx.config.timezone)).date().isoformat()


def program_set(a, ctx):
    ctx.db.set(PROGRAM_KEY, {"program": a["program"], "goal": a.get("goal", ""),
                             "updated": _today(ctx)})
    return "Training program saved."


def program_get(a, ctx):
    return ctx.db.get(PROGRAM_KEY) or "No training program saved yet."


def workout_log(a, ctx):
    wid = ctx.db.execute(
        "INSERT INTO workouts(date, kind, duration_min, notes) VALUES(?,?,?,?)",
        (a.get("date") or _today(ctx), a["kind"], a.get("duration_min"), a.get("notes", "")))
    for e in a.get("exercises", []):
        ctx.db.execute(
            "INSERT INTO workout_sets(workout_id, exercise, sets, reps, weight_kg, distance_km, "
            "minutes) VALUES(?,?,?,?,?,?,?)",
            (wid, e["exercise"].strip().lower(), e.get("sets"), e.get("reps"),
             e.get("weight_kg"), e.get("distance_km"), e.get("minutes")))
    return f"Workout #{wid} logged."


def workout_history(a, ctx):
    since = (datetime.fromisoformat(_today(ctx)) - timedelta(days=int(a.get("days", 14)))).date()
    workouts = ctx.db.query(
        "SELECT id, date, kind, duration_min, notes FROM workouts WHERE date >= ? "
        "ORDER BY date DESC, id DESC", (since.isoformat(),))
    for w in workouts:
        w["exercises"] = ctx.db.query(
            "SELECT exercise, sets, reps, weight_kg, distance_km, minutes FROM workout_sets "
            "WHERE workout_id=?", (w["id"],))
    return workouts or "No workouts logged in that period."


def exercise_progress(a, ctx):
    rows = ctx.db.query(
        "SELECT w.date, s.sets, s.reps, s.weight_kg, s.distance_km, s.minutes "
        "FROM workout_sets s JOIN workouts w ON w.id = s.workout_id "
        "WHERE s.exercise LIKE ? ORDER BY w.date", (f"%{a['exercise'].strip().lower()}%",))
    return rows[-30:] or "No logged sets for that exercise."


def workout_delete(a, ctx):
    ctx.db.execute("DELETE FROM workout_sets WHERE workout_id=?", (a["workout_id"],))
    ctx.db.execute("DELETE FROM workouts WHERE id=?", (a["workout_id"],))
    return f"Workout #{a['workout_id']} deleted."


EXERCISE = {
    "type": "object",
    "properties": {
        "exercise": {"type": "string", "description": "e.g. 'squat', 'bench press', 'run'"},
        "sets": {"type": "integer"}, "reps": {"type": "integer"},
        "weight_kg": {"type": "number"}, "distance_km": {"type": "number"},
        "minutes": {"type": "number"},
    },
    "required": ["exercise"],
}


class FitnessSkill(Skill):
    def __init__(self):
        super().__init__(
            name="Training coach",
            description="Keeps your training program, logs workouts and tracks progress.",
            instructions=(
                "When the user describes a training program, save it with program_set (keep "
                "their structure: days, exercises, sets x reps, goals). When they say they "
                "trained, log it with workout_log, one entry per exercise, using consistent "
                "exercise names. For 'what should I do today', read program_get and recent "
                "workout_history and pick the next session. Suggest progression (e.g. +2.5 kg "
                "when all reps were hit last time) based on exercise_progress, and point out "
                "missed sessions kindly. To schedule training, use reminders or the calendar."
            ),
            tools=[
                Tool("program_set", "Save (replace) the user's training program.",
                     schema({"program": {"type": "string",
                                         "description": "Full program, e.g. weekly schedule"},
                             "goal": {"type": "string"}}, ["program"]), program_set),
                Tool("program_get", "Read the saved training program.", schema({}), program_get),
                Tool("workout_log", "Log a completed workout.",
                     schema({"kind": {"type": "string",
                                      "description": "e.g. 'legs', 'upper body', 'run'"},
                             "date": {"type": "string", "description": "ISO date, default today"},
                             "duration_min": {"type": "integer"},
                             "exercises": {"type": "array", "items": EXERCISE},
                             "notes": {"type": "string", "description": "How it felt, etc."}},
                            ["kind"]), workout_log),
                Tool("workout_history", "List logged workouts from the last N days.",
                     schema({"days": {"type": "integer", "description": "Default 14"}}),
                     workout_history),
                Tool("exercise_progress", "Show the logged history of one exercise over time.",
                     schema({"exercise": {"type": "string"}}, ["exercise"]), exercise_progress),
                Tool("workout_delete", "Delete a logged workout.",
                     schema({"workout_id": {"type": "integer"}}, ["workout_id"]), workout_delete),
            ],
        )

    def setup(self, db, config):
        db.executescript(TABLES)
