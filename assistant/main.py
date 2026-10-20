"""Telegram front-end. Start with:  python -m assistant.main"""
import logging
from datetime import time as dtime
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

from . import google_auth
from .agent import Agent
from .config import Config
from .db import DB
from .skills import load_skills
from .skills.tasks import due_reminders

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("assistant")

BRIEFING_PROMPT = (
    "Give me my morning briefing. Check: today's calendar events, important unread emails "
    "from the last 24 hours (skip newsletters/promotions), open tasks that are due soon or "
    "overdue, and recurring bills due in the next 5 days. Keep it short and scannable, "
    "then suggest the 1-3 most important things to do today. Skip any part whose account "
    "isn't connected."
)

HELP = """Hi! I'm your personal assistant. Just talk to me normally, e.g.:

• "What's on my calendar tomorrow?"
• "Any important emails today? Draft a reply to Anna."
• "Remind me to call mom at 6pm"
• "Add 'renew passport' to my to-do list"
• "Research the best eSIM for Japan"
• "I spent 250 on lunch"

Commands:
/connect_google – link Gmail, Calendar & Drive
/briefing – get your daily briefing now
/tasks – show open tasks
/skills – what I can do
/reset – clear our conversation memory (notes and tasks are kept)"""


def split(text: str, n: int = 4000) -> list[str]:
    return [text[i:i + n] for i in range(0, len(text), n)] or [""]


class Bot:
    def __init__(self, config: Config):
        self.config = config
        self.db = DB(config.data_dir / "assistant.db")
        self.skills = load_skills(config.enabled_skills, self.db, config)
        self.agent = Agent(config, self.db, self.skills)

    # ------------------------------------------------------------ helpers
    def allowed(self, update: Update) -> bool:
        return bool(self.config.owner_id) and update.effective_user.id == self.config.owner_id

    async def guard(self, update: Update) -> bool:
        if self.allowed(update):
            return True
        if not self.config.owner_id:
            await update.effective_message.reply_text(
                f"Setup step: your Telegram ID is {update.effective_user.id}\n"
                "Put it in the OWNER_TELEGRAM_ID setting and restart me.")
        else:
            await update.effective_message.reply_text("Sorry, I'm a private assistant.")
        return False

    async def send_reply(self, chat_id: int, reply, bot) -> None:
        for chunk in split(reply.text):
            await bot.send_message(chat_id, chunk)
        for pid in reply.pending_ids:
            row = self.db.query("SELECT summary FROM pending_actions WHERE id=?", (pid,))[0]
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Approve", callback_data=f"ok:{pid}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"no:{pid}"),
            ]])
            await bot.send_message(chat_id, f"Needs your approval (#{pid}):\n\n{row['summary']}"[:4000],
                                   reply_markup=kb)

    async def ask_agent(self, chat_id: int, text: str, bot, remember=True) -> None:
        await bot.send_chat_action(chat_id, ChatAction.TYPING)
        try:
            reply = await self.agent.handle(chat_id, text, remember=remember)
        except Exception as e:
            log.exception("Agent error")
            await bot.send_message(chat_id, f"Something went wrong: {e}")
            return
        await self.send_reply(chat_id, reply, bot)

    # ----------------------------------------------------------- handlers
    async def on_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if await self.guard(update):
            await update.message.reply_text(HELP)

    async def on_reset(self, update: Update, ctx):
        if await self.guard(update):
            self.db.clear_history(update.effective_chat.id)
            await update.message.reply_text("Conversation memory cleared.")

    async def on_skills(self, update: Update, ctx):
        if await self.guard(update):
            lines = [f"• {s.name}: {s.description}" for s in self.skills]
            await update.message.reply_text("Skills switched on:\n" + "\n".join(lines))

    async def on_tasks(self, update: Update, ctx):
        if await self.guard(update):
            await self.ask_agent(update.effective_chat.id, "Show my open tasks.", ctx.bot)

    async def on_briefing(self, update: Update, ctx):
        if await self.guard(update):
            await self.ask_agent(update.effective_chat.id, BRIEFING_PROMPT, ctx.bot, remember=False)

    async def on_connect_google(self, update: Update, ctx):
        if not await self.guard(update):
            return
        try:
            url = google_auth.start(self.config, update.effective_chat.id)
        except Exception as e:
            await update.message.reply_text(f"Can't start Google connection: {e}")
            return
        await update.message.reply_text(
            "1) Open this link and allow access:\n" + url +
            "\n\n2) Google may warn the app is unverified – click 'Advanced' → 'Go to … (unsafe)'. "
            "That's fine: it's your own app.\n"
            "3) You'll end on a page that says it can't be reached. That's expected! "
            "Copy the FULL address from the browser bar (starts with http://localhost) "
            "and paste it here.")

    async def on_text(self, update: Update, ctx):
        if not await self.guard(update):
            return
        chat_id = update.effective_chat.id
        text = update.message.text or ""
        if google_auth.is_waiting(chat_id) and text.strip().startswith("http://localhost"):
            try:
                google_auth.finish(self.db, chat_id, text)
                await update.message.reply_text("Google connected ✅ Try: 'What's on my calendar today?'")
            except Exception as e:
                await update.message.reply_text(f"That didn't work: {e}\nTry /connect_google again.")
            return
        await self.ask_agent(chat_id, text, ctx.bot)

    async def on_button(self, update: Update, ctx):
        q = update.callback_query
        if not self.allowed(update):
            await q.answer("Not allowed")
            return
        await q.answer()
        kind, pid = q.data.split(":")
        result = await self.agent.resolve_action(int(pid), approve=(kind == "ok"))
        await q.edit_message_reply_markup(None)
        await q.message.reply_text(result[:4000])

    # ------------------------------------------------------------- jobs
    async def job_reminders(self, ctx: ContextTypes.DEFAULT_TYPE):
        for r in due_reminders(self.db):
            await ctx.bot.send_message(r["chat_id"] or self.config.owner_id, f"⏰ Reminder: {r['text']}")

    async def job_briefing(self, ctx: ContextTypes.DEFAULT_TYPE):
        if self.config.owner_id:
            await self.ask_agent(self.config.owner_id, BRIEFING_PROMPT, ctx.bot, remember=False)

    # -------------------------------------------------------------- run
    def run(self):
        app = Application.builder().token(self.config.telegram_token).build()
        app.add_handler(CommandHandler(["start", "help"], self.on_start))
        app.add_handler(CommandHandler("reset", self.on_reset))
        app.add_handler(CommandHandler("skills", self.on_skills))
        app.add_handler(CommandHandler("tasks", self.on_tasks))
        app.add_handler(CommandHandler("briefing", self.on_briefing))
        app.add_handler(CommandHandler("connect_google", self.on_connect_google))
        app.add_handler(CallbackQueryHandler(self.on_button))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))

        app.job_queue.run_repeating(self.job_reminders, interval=30, first=10)
        if self.config.briefing_time:
            hh, mm = map(int, self.config.briefing_time.split(":"))
            app.job_queue.run_daily(self.job_briefing,
                                    time=dtime(hh, mm, tzinfo=ZoneInfo(self.config.timezone)))
        log.info("Assistant running with skills: %s", ", ".join(s.name for s in self.skills))
        app.run_polling(allowed_updates=Update.ALL_TYPES)


def main():
    config = Config()
    missing = config.missing()
    if missing:
        raise SystemExit(f"Missing settings: {', '.join(missing)} (see README)")
    Bot(config).run()


if __name__ == "__main__":
    main()
