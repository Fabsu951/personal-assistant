"""Training coach: program, workout log, daily body status, Strava, progress."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .. import strava
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
CREATE TABLE IF NOT EXISTS body_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, weight_kg REAL, sleep_hours REAL,
    energy INTEGER, soreness INTEGER, resting_hr INTEGER, injuries TEXT, notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""
STATUS_FIELDS = ["weight_kg", "sleep_hours", "energy", "soreness", "resting_hr", "injuries", "notes"]
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


def status_log(a, ctx):
    values = [a.get(f) for f in STATUS_FIELDS]
    sid = ctx.db.execute(
        f"INSERT INTO body_status(date, {', '.join(STATUS_FIELDS)}) VALUES(?{',?' * len(STATUS_FIELDS)})",
        (a.get("date") or _today(ctx), *values))
    return f"Status #{sid} logged."


def status_history(a, ctx):
    since = (datetime.fromisoformat(_today(ctx)) - timedelta(days=int(a.get("days", 14)))).date()
    rows = ctx.db.query(
        f"SELECT date, {', '.join(STATUS_FIELDS)} FROM body_status WHERE date >= ? "
        "ORDER BY date, id", (since.isoformat(),))
    # leave out empty fields so the model sees only what was actually reported
    return [{k: v for k, v in r.items() if v not in (None, "")} for r in rows] \
        or "No status logged in that period."


def strava_activities(a, ctx):
    return strava.activities(ctx.db, ctx.config, int(a.get("days", 14))) \
        or "No Strava activities in that period."


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
            description="Training program, workout log, body status, Strava and progress.",
            instructions=(
                "When the user describes a training program, save it with program_set (keep "
                "their structure: days, exercises, sets x reps, goals). When they say they "
                "trained, log it with workout_log, one entry per exercise, using consistent "
                "exercise names. For 'what should I do today', read program_get and recent "
                "workout_history and pick the next session. Suggest progression (e.g. +2.5 kg "
                "when all reps were hit last time) based on exercise_progress, and point out "
                "missed sessions kindly. To schedule training, use reminders or the calendar. "
                "When the user mentions sleep, weight, energy, soreness, pain or injuries, log "
                "it with status_log (energy and soreness on a 1-10 scale). Before planning a "
                "session, check status_history: after poor sleep, low energy or high soreness "
                "suggest a lighter session; with an injury, avoid loading that body part and "
                "suggest alternatives (you are not a doctor: for real pain, advise seeing one). "
                "Runs, rides etc. from the user's watch come from Strava (strava_activities): "
                "count them as done sessions and don't log them again with workout_log."
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
                Tool("status_log", "Log how the user's body feels today (any fields they mention).",
                     schema({"date": {"type": "string", "description": "ISO date, default today"},
                             "weight_kg": {"type": "number"}, "sleep_hours": {"type": "number"},
                             "energy": {"type": "integer", "description": "1 (empty) - 10 (great)"},
                             "soreness": {"type": "integer", "description": "1 (none) - 10 (very sore)"},
                             "resting_hr": {"type": "integer"},
                             "injuries": {"type": "string", "description": "e.g. 'left knee aches'"},
                             "notes": {"type": "string"}}), status_log),
                Tool("status_history", "Body status (sleep, weight, energy, injuries) over N days.",
                     schema({"days": {"type": "integer", "description": "Default 14"}}),
                     status_history),
                Tool("strava_activities",
                     "Activities synced to Strava (from the user's watch) over the last N days.",
                     schema({"days": {"type": "integer", "description": "Default 14"}}),
                     strava_activities),
                Tool("workout_delete", "Delete a logged workout.",
                     schema({"workout_id": {"type": "integer"}}, ["workout_id"]), workout_delete),
            ],
        )

    def setup(self, db, config):
        db.executescript(TABLES)
