"""Telegram front-end. Start with:  python -m assistant.main"""
import base64
import logging
import time
from datetime import time as dtime
from zoneinfo import ZoneInfo

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, InputFile, MenuButtonWebApp,
                      Update, WebAppInfo)
from telegram.constants import ChatAction
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

from . import google_auth, microsoft, strava, voice, web
from .agent import Agent
from .config import Config
from .db import DB
from .extract import can_read, text_from_file
from .skills import load_skills
from .skills.tasks import due_reminders

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("assistant")

BRIEFING_PROMPT = (
    "Give me my morning briefing. Check: today's calendar events, important unread emails "
    "from the last 24 hours (skip newsletters/promotions), open tasks that are due soon or "
    "overdue, recurring bills due in the next 5 days, today's planned workout (if a training "
    "program is set), and anything else due soon that you can see: flashcards due, content "
    "to film or publish, job application deadlines within a week, birthdays within a week, "
    "habits to do today and budget categories close to their limit. Keep it short and "
    "scannable, then suggest the 1-3 most important things to do today. Skip any part that "
    "has nothing in it or whose account isn't connected."
)
BRIEFING_LABEL = "(Asked for my morning briefing.)"
REVIEW_LABEL = "(Asked for my weekly training review.)"

WEEKLY_REVIEW_PROMPT = (
    "Time for my weekly training review. Compare the last 7 days (workout_history, "
    "strava_activities if Strava is connected, status_history) with my program and goals: "
    "what went well, what was missed, progress on key lifts/runs, and how my body status "
    "(sleep, energy, soreness, injuries) has been. Then propose next week's sessions with "
    "days and concrete targets, adjusted to my status and this week's calendar. Ask if I "
    "want them added to the calendar. Keep it short and motivating."
)

HELP = """Hi! I'm your personal assistant. Just talk to me normally, e.g.:

• "What's on my calendar tomorrow?"
• "Any important emails today? Draft a reply to Anna."
• "Remind me to call mom at 6pm"
• "Add 'renew passport' to my to-do list"
• "Research the best eSIM for Japan"
• "Cheapest flight Taipei → Stockholm in December?"
• "Translate this" (send a photo of a menu or sign)
• "Quiz me on Fin Inve" · "Write a report on … as a Word file"
• "Let's brainstorm video ideas" · "Mom's birthday is 3 May"
• "I spent 250 on lunch"
• "Did legs today: squats 3x5 at 100 kg"
• "Slept 6 hours, left knee aches" (I'll adapt your training)
You can also send voice messages, and I answer them with voice.

Commands:
/connect_google – link Gmail, Calendar & Drive
/briefing – get your daily briefing now
/review – weekly training review now
/connect_onedrive – link OneDrive
/connect_strava – link Strava (workouts from your watch)
/tasks – show open tasks
/skills – what I can do
/talk – hands-free voice mode
/voice – spoken replies on/off
/reset – clear our conversation memory (notes and tasks are kept)"""


MAX_FILE = 20 * 1024 * 1024    # Telegram bots can download up to 20 MB
MAX_IMAGE = 5 * 1024 * 1024    # Claude's limit per image
IMAGE_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp")


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
        await self.send_files(chat_id, reply.files, bot)
        await self.send_approvals(chat_id, reply.pending_ids, bot)

    async def send_files(self, chat_id: int, files: list, bot) -> None:
        for name, data in files:
            await bot.send_document(chat_id, InputFile(data, filename=name))

    async def send_approvals(self, chat_id: int, pending_ids: list[int], bot) -> None:
        for pid in pending_ids:
            row = self.db.query("SELECT summary FROM pending_actions WHERE id=?", (pid,))[0]
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Approve", callback_data=f"ok:{pid}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"no:{pid}"),
            ]])
            await bot.send_message(chat_id, f"Needs your approval (#{pid}):\n\n{row['summary']}"[:4000],
                                   reply_markup=kb)

    def voice_mode(self) -> str:
        return self.db.get("voice_replies", self.config.voice_replies)

    async def ask_agent(self, chat_id: int, text: str, bot, remember=True, spoken=False,
                        attachments=None, use_history=None, record_as=None) -> None:
        await bot.send_chat_action(chat_id, ChatAction.TYPING)
        t0 = time.monotonic()
        try:
            reply = await self.agent.handle(chat_id, text, remember=remember, spoken=spoken,
                                            attachments=attachments, use_history=use_history,
                                            record_as=record_as)
        except Exception as e:
            log.exception("Agent error")
            await bot.send_message(chat_id, f"Something went wrong: {e}")
            return
        t1 = time.monotonic()
        await self.send_reply(chat_id, reply, bot)  # text first: shows up while the audio is made
        if voice.wants_voice(self.voice_mode(), spoken) and self.config.openai_api_key:
            try:
                await bot.send_chat_action(chat_id, ChatAction.RECORD_VOICE)
                audio = await voice.speak(self.config, reply.text,
                                          voice=self.db.get("tts_voice"), style=self.db.get("tts_style"))
                await bot.send_voice(chat_id, audio)
                log.info("timing: thinking %.1fs, speech %.1fs", t1 - t0, time.monotonic() - t1)
            except Exception:  # the text reply already arrived
                log.exception("Text-to-speech failed")

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
            await self.ask_agent(update.effective_chat.id, BRIEFING_PROMPT, ctx.bot,
                                 use_history=False, record_as=BRIEFING_LABEL)

    def talk_url(self) -> str:
        return f"{self.config.web_url}/talk"

    async def on_talk(self, update: Update, ctx):
        if not await self.guard(update):
            return
        if not self.config.web_url:
            await update.message.reply_text(
                "The voice page isn't switched on yet. In Railway: worker → Settings → Networking "
                "→ Generate Domain (port 8080). Then send /talk again.")
            return
        key = web.make_key(self.config.telegram_token, self.config.owner_id)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎙 Talk to me", web_app=WebAppInfo(self.talk_url()))],
            [InlineKeyboardButton("🌐 Open in browser", url=f"{self.talk_url()}?k={key}")],
        ])
        await update.message.reply_text(
            "Hands-free mode: tap the microphone once, then just talk. I answer out loud and "
            "listen again. You'll also find it under the 🎙 button next to the message field.",
            reply_markup=kb)

    async def on_review(self, update: Update, ctx):
        if await self.guard(update):
            await self.ask_agent(update.effective_chat.id, WEEKLY_REVIEW_PROMPT, ctx.bot,
                                 record_as=REVIEW_LABEL)

    async def on_connect_strava(self, update: Update, ctx):
        if not await self.guard(update):
            return
        try:
            url = strava.start(self.config)
        except Exception as e:
            await update.message.reply_text(f"Can't start Strava connection: {e}")
            return
        await update.message.reply_text(
            "1) Open this link and click 'Authorize':\n" + url +
            "\n\n2) You'll end on a page that says it can't be reached. That's expected! "
            "Copy the FULL address from the browser bar (starts with http://localhost) "
            "and paste it here.")

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
        if text.strip().startswith("http://localhost") and strava.is_strava_redirect(text):
            try:
                strava.finish(self.db, self.config, text)
                await update.message.reply_text("Strava connected ✅ Try: 'What did I train this week?'")
            except Exception as e:
                await update.message.reply_text(f"That didn't work: {e}\nTry /connect_strava again.")
            return
        if google_auth.is_waiting(chat_id) and text.strip().startswith("http://localhost"):
            try:
                google_auth.finish(self.db, chat_id, text)
                await update.message.reply_text("Google connected ✅ Try: 'What's on my calendar today?'")
            except Exception as e:
                await update.message.reply_text(f"That didn't work: {e}\nTry /connect_google again.")
            return
        await self.ask_agent(chat_id, text, ctx.bot)

    async def on_voice(self, update: Update, ctx):
        if not await self.guard(update):
            return
        chat_id = update.effective_chat.id
        media = update.message.voice or update.message.audio
        await ctx.bot.send_chat_action(chat_id, ChatAction.TYPING)
        t0 = time.monotonic()
        try:
            file = await media.get_file()
            audio = bytes(await file.download_as_bytearray())
            text = await voice.transcribe(self.config, audio,
                                          getattr(media, "file_name", None) or "voice.ogg")
        except Exception as e:
            log.exception("Transcription failed")
            await update.message.reply_text(f"I couldn't listen to that voice message: {e}")
            return
        if not text:
            await update.message.reply_text("I couldn't hear any words in that voice message.")
            return
        log.info("timing: listening %.1fs", time.monotonic() - t0)
        await update.message.reply_text(f"🎤 \"{text[:500]}\"")  # so mishearings are visible
        await self.ask_agent(chat_id, text, ctx.bot, spoken=True)

    async def on_file(self, update: Update, ctx):
        """Photos (menus, signs, receipts...), PDFs and documents sent in the chat."""
        if not await self.guard(update):
            return
        msg, chat_id = update.message, update.effective_chat.id
        if msg.photo:
            media, mime, name = msg.photo[-1], "image/jpeg", "photo.jpg"
        else:
            media = msg.document
            mime, name = media.mime_type or "", media.file_name or "file"
        if (media.file_size or 0) > MAX_FILE:
            await msg.reply_text("That file is too big for me (max 20 MB).")
            return
        await ctx.bot.send_chat_action(chat_id, ChatAction.TYPING)
        data = bytes(await (await media.get_file()).download_as_bytearray())
        b64 = base64.b64encode(data).decode()
        if mime in IMAGE_TYPES and len(data) <= MAX_IMAGE:
            block = {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}}
        elif mime == "application/pdf":
            block = {"type": "document", "source": {"type": "base64", "media_type": mime, "data": b64}}
        elif can_read(name):
            try:
                block = {"type": "text", "text": f"[File: {name}]\n{text_from_file(name, data)[:30000]}"}
            except Exception:
                log.exception("Could not read %s", name)
                await msg.reply_text(f"I couldn't open {name}; the file may be damaged.")
                return
        else:
            await msg.reply_text("I can read photos, PDFs, Word, Excel, PowerPoint and text files. "
                                 "Big images: send them as a photo instead of a file.")
            return
        caption = msg.caption or ("(Sent without a comment. Work out what it is and help: e.g. "
                                  "translate it if it's in another language, or log it if it's a receipt.)")
        await self.ask_agent(chat_id, caption, ctx.bot, attachments=[block])

    async def on_connect_onedrive(self, update: Update, ctx):
        if not await self.guard(update):
            return
        chat_id = update.effective_chat.id
        try:
            flow = await microsoft.start(self.config)
        except Exception as e:
            await update.message.reply_text(f"Can't start OneDrive connection: {e}")
            return
        await update.message.reply_text(
            f"1) Open {flow['verification_uri']}\n2) Enter this code (tap to copy below)\n"
            "3) Sign in with the Microsoft account that has your OneDrive and accept.\n"
            "I'll tell you here when it's done.")
        await update.message.reply_text(flow["user_code"])

        async def finish():
            try:
                await microsoft.wait_for_login(self.db, self.config, flow)
                await ctx.bot.send_message(chat_id, "OneDrive connected ✅ Try: 'What's in my OneDrive?'")
            except Exception as e:
                await ctx.bot.send_message(chat_id, f"OneDrive connection failed: {e}")
        ctx.application.create_task(finish())

    async def on_voice_setting(self, update: Update, ctx):
        if not await self.guard(update):
            return
        if ctx.args and ctx.args[0].lower() in voice.MODES:
            self.db.set("voice_replies", ctx.args[0].lower())
        await update.message.reply_text(
            f"Spoken replies: {self.voice_mode()}\n\n"
            "/voice auto – I answer voice messages with voice\n"
            "/voice always – I always answer with voice too\n"
            "/voice off – text only")

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
            # saved, so a reply like "thanks" or "move that" knows what the briefing said
            await self.ask_agent(self.config.owner_id, BRIEFING_PROMPT, ctx.bot,
                                 use_history=False, record_as=BRIEFING_LABEL)

    async def job_weekly_review(self, ctx: ContextTypes.DEFAULT_TYPE):
        if self.config.owner_id:  # remembered, so you can answer "yes, add them"
            await self.ask_agent(self.config.owner_id, WEEKLY_REVIEW_PROMPT, ctx.bot,
                                 record_as=REVIEW_LABEL)

    # -------------------------------------------------------------- run
    async def post_init(self, app: Application) -> None:
        """Runs inside the bot's event loop: start the voice page next to the bot."""
        self.web = web.WebApp(self)
        await self.web.start()
        if self.config.web_url and self.config.owner_id:
            try:  # the button next to the message field opens the voice page
                await app.bot.set_chat_menu_button(
                    chat_id=self.config.owner_id,
                    menu_button=MenuButtonWebApp("🎙 Talk", WebAppInfo(self.talk_url())))
            except Exception:
                log.exception("Could not set the voice page menu button")

    async def post_shutdown(self, app: Application) -> None:
        await self.web.stop()

    def run(self):
        app = (Application.builder().token(self.config.telegram_token)
               .post_init(self.post_init).post_shutdown(self.post_shutdown).build())
        self.app = app
        app.add_handler(CommandHandler(["start", "help"], self.on_start))
        app.add_handler(CommandHandler("reset", self.on_reset))
        app.add_handler(CommandHandler("skills", self.on_skills))
        app.add_handler(CommandHandler("tasks", self.on_tasks))
        app.add_handler(CommandHandler("briefing", self.on_briefing))
        app.add_handler(CommandHandler("connect_google", self.on_connect_google))
        app.add_handler(CommandHandler("connect_strava", self.on_connect_strava))
        app.add_handler(CommandHandler("review", self.on_review))
        app.add_handler(CommandHandler("voice", self.on_voice_setting))
        app.add_handler(CommandHandler("talk", self.on_talk))
        app.add_handler(CommandHandler("connect_onedrive", self.on_connect_onedrive))
        app.add_handler(CallbackQueryHandler(self.on_button))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, self.on_voice))
        app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, self.on_file))

        app.job_queue.run_repeating(self.job_reminders, interval=30, first=10)
        if self.config.briefing_time.lower() != "off":
            hh, mm = map(int, self.config.briefing_time.split(":"))
            app.job_queue.run_daily(self.job_briefing,
                                    time=dtime(hh, mm, tzinfo=ZoneInfo(self.config.timezone)))
        if "fitness" in self.config.enabled_skills and self.config.weekly_review_time.lower() != "off":
            hh, mm = map(int, self.config.weekly_review_time.split(":"))
            app.job_queue.run_daily(self.job_weekly_review, days=(0,),  # 0 = Sunday
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
