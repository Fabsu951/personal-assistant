"""Food: meal log with estimated macros, recipes, meal plans and a shopping list."""
from datetime import timedelta

from .base import Skill, Tool, schema, today

TABLES = """
CREATE TABLE IF NOT EXISTS meals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, description TEXT,
    kcal REAL, protein_g REAL, carbs_g REAL, fat_g REAL
);
CREATE TABLE IF NOT EXISTS shopping (
    id INTEGER PRIMARY KEY AUTOINCREMENT, item TEXT, done INTEGER DEFAULT 0
);
"""


def meal_log(a, ctx):
    mid = ctx.db.execute(
        "INSERT INTO meals(day, description, kcal, protein_g, carbs_g, fat_g) VALUES(?,?,?,?,?,?)",
        (a.get("date") or today(ctx).isoformat(), a["description"], a.get("kcal"),
         a.get("protein_g"), a.get("carbs_g"), a.get("fat_g")))
    return f"Meal #{mid} logged."


def nutrition_summary(a, ctx):
    since = (today(ctx) - timedelta(days=int(a.get("days", 1)) - 1)).isoformat()
    days = ctx.db.query(
        "SELECT day, ROUND(SUM(kcal)) AS kcal, ROUND(SUM(protein_g)) AS protein_g, "
        "ROUND(SUM(carbs_g)) AS carbs_g, ROUND(SUM(fat_g)) AS fat_g, COUNT(*) AS meals "
        "FROM meals WHERE day >= ? GROUP BY day ORDER BY day", (since,))
    meals = ctx.db.query("SELECT id, day, description, kcal, protein_g FROM meals WHERE day >= ? "
                         "ORDER BY day, id", (since,))
    return {"per_day": days, "meals": meals[-30:]} if meals else "No meals logged in that period."


def meal_delete(a, ctx):
    ctx.db.execute("DELETE FROM meals WHERE id=?", (a["meal_id"],))
    return f"Meal #{a['meal_id']} deleted."


def shopping_add(a, ctx):
    for item in a["items"]:
        ctx.db.execute("INSERT INTO shopping(item) VALUES(?)", (item,))
    return f"Added {len(a['items'])} item(s) to the shopping list."


def shopping_list(a, ctx):
    return ctx.db.query("SELECT id, item FROM shopping WHERE done=0 ORDER BY id") or "Shopping list is empty."


def shopping_done(a, ctx):
    if a.get("all"):
        ctx.db.execute("UPDATE shopping SET done=1 WHERE done=0")
        return "Shopping list cleared."
    for i in a.get("item_ids", []):
        ctx.db.execute("UPDATE shopping SET done=1 WHERE id=?", (i,))
    return f"Ticked off {len(a.get('item_ids', []))} item(s)."


class NutritionSkill(Skill):
    def __init__(self):
        super().__init__(
            name="Food & nutrition",
            description="Meal log with calories/protein, recipes, meal plans, shopping list.",
            instructions=(
                "When the user says or shows (photo) what they ate, estimate kcal, protein, carbs "
                "and fat, log it with meal_log and say it's an estimate. Relate intake to their "
                "training goal (program_get) and body weight (status_history): e.g. protein about "
                "1.6-2.2 g per kg for strength training. RECIPES: quick, cheap, high-protein ideas "
                "from what they have at home or can buy locally (they live in Taiwan: night "
                "markets, 7-Eleven, local supermarkets count too). MEAL PLANS: turn them into a "
                "shopping list with shopping_add. Never give medical diet advice; suggest a "
                "doctor or dietitian for health conditions."
            ),
            tools=[
                Tool("meal_log", "Log a meal with estimated nutrition.",
                     schema({"description": {"type": "string"}, "kcal": {"type": "number"},
                             "protein_g": {"type": "number"}, "carbs_g": {"type": "number"},
                             "fat_g": {"type": "number"},
                             "date": {"type": "string", "description": "YYYY-MM-DD, default today"}},
                            ["description"]), meal_log),
                Tool("nutrition_summary", "Calories and macros per day for the last N days (default 1 = today).",
                     schema({"days": {"type": "integer"}}), nutrition_summary),
                Tool("meal_delete", "Delete a logged meal.",
                     schema({"meal_id": {"type": "integer"}}, ["meal_id"]), meal_delete),
                Tool("shopping_add", "Add items to the shopping list.",
                     schema({"items": {"type": "array", "items": {"type": "string"}}}, ["items"]),
                     shopping_add),
                Tool("shopping_list", "Show the shopping list.", schema({}), shopping_list),
                Tool("shopping_done", "Tick off bought items (or all).",
                     schema({"item_ids": {"type": "array", "items": {"type": "integer"}},
                             "all": {"type": "boolean"}}), shopping_done),
            ],
        )

    def setup(self, db, config):
        db.executescript(TABLES)
